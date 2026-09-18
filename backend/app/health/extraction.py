"""
M3 Slice 2 — Pluggable Document Extractor.

Architecture contract (m3-architecture-lock.md):
  - Supported formats: application/pdf, text/plain.
  - No OCR, no image understanding, no external extraction APIs.
  - No background workers / Celery / Redis.
  - Implementations are in-process and swappable via the DocumentExtractor Protocol.
  - ExtractionResult is the sole data-transfer object between the engine and callers.

Extraction method identifiers:
  - "pypdf"       — native digital PDF via the pypdf library.
  - "text/plain"  — UTF-8 plain text decode.

Extraction version follows "<method>/<library-version>" for forward traceability.

NUL-byte handling:
  - Any NUL bytes (\x00) in the output are stripped.  PostgreSQL TEXT columns
    reject embedded NULs and their presence in clinical documents is always
    an artefact of binary framing, never meaningful plain text.

Line-ending normalisation:
  - \r\n and lone \r are normalised to \n before returning text.

Safety invariant:
  - Extractors must NEVER raise unchecked exceptions to callers.  All errors
    are captured and returned as FAILED ExtractionResult instances with a
    sanitised, non-path-leaking error_message.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from importlib.metadata import version as _pkg_version
from typing import Optional, Protocol

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Extraction version helpers
# ---------------------------------------------------------------------------

_PYPDF_VERSION: str = "unknown"
try:
    _PYPDF_VERSION = _pkg_version("pypdf")
except Exception:  # pragma: no cover — optional at import time
    pass


def _pypdf_version_string() -> str:
    return f"pypdf/{_PYPDF_VERSION}"


def _plain_text_version_string() -> str:
    return "text-plain/1.0"


# ---------------------------------------------------------------------------
# ExtractionResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractionResult:
    """Immutable result produced by any DocumentExtractor implementation.

    Lifecycle invariants (mirrors the DB CHECK constraints in Slice 1):
      - status == "COMPLETED"   → extracted_text is non-None and non-empty.
      - status == "FAILED"      → extracted_text is None;  error_message set.
      - status == "UNSUPPORTED" → extracted_text is None;  error_message optional.
    """

    status: str  # "COMPLETED" | "FAILED" | "UNSUPPORTED"
    extraction_method: str
    extraction_version: str
    extracted_text: Optional[str] = field(default=None)
    error_message: Optional[str] = field(default=None)

    def __post_init__(self) -> None:
        _VALID = {"COMPLETED", "FAILED", "UNSUPPORTED"}
        if self.status not in _VALID:
            raise ValueError(
                f"ExtractionResult.status must be one of {_VALID!r}, "
                f"got {self.status!r}"
            )
        if self.status == "COMPLETED":
            if not self.extracted_text or not self.extracted_text.strip():
                raise ValueError(
                    "ExtractionResult with status='COMPLETED' requires "
                    "non-empty extracted_text"
                )
        else:
            # FAILED / UNSUPPORTED
            if self.extracted_text and self.extracted_text.strip():
                raise ValueError(
                    f"ExtractionResult with status='{self.status}' must have "
                    "null or empty extracted_text"
                )

    # ------------------------------------------------------------------
    # Convenience constructors
    # ------------------------------------------------------------------

    @classmethod
    def completed(
        cls,
        *,
        text: str,
        method: str,
        version: str,
    ) -> "ExtractionResult":
        """Return a COMPLETED result.  *text* must be non-empty."""
        return cls(
            status="COMPLETED",
            extraction_method=method,
            extraction_version=version,
            extracted_text=text,
        )

    @classmethod
    def failed(
        cls,
        *,
        method: str,
        version: str,
        error: str,
    ) -> "ExtractionResult":
        """Return a FAILED result with a sanitised error message."""
        return cls(
            status="FAILED",
            extraction_method=method,
            extraction_version=version,
            error_message=error,
        )

    @classmethod
    def unsupported(
        cls,
        *,
        method: str = "none",
        version: str = "none",
        error: Optional[str] = None,
    ) -> "ExtractionResult":
        """Return an UNSUPPORTED result for content types this engine cannot handle."""
        return cls(
            status="UNSUPPORTED",
            extraction_method=method,
            extraction_version=version,
            error_message=error,
        )


# ---------------------------------------------------------------------------
# DocumentExtractor Protocol
# ---------------------------------------------------------------------------


class DocumentExtractor(Protocol):
    """Interface for all concrete text-extraction back-ends.

    Callers must be able to swap implementations without changing the call site.
    The Protocol is checked structurally; no explicit registration is needed.
    """

    async def extract_text(
        self,
        file_bytes: bytes,
        content_type: str,
    ) -> ExtractionResult:
        """Extract plain text from *file_bytes* whose MIME type is *content_type*.

        Returns:
          ExtractionResult with status COMPLETED, FAILED, or UNSUPPORTED.
          Must NEVER raise; all error paths return a FAILED or UNSUPPORTED result.
        """
        ...


# ---------------------------------------------------------------------------
# Shared text normalisation
# ---------------------------------------------------------------------------


def _normalise_text(raw: str) -> str:
    """Strip NUL bytes and normalise line endings.

    - Removes embedded NUL characters (\x00), which PostgreSQL TEXT rejects
      and which never carry meaningful clinical text.
    - Converts \r\n and lone \r to \n for consistent storage.
    """
    cleaned = raw.replace("\x00", "")
    normalised = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    return normalised


# ---------------------------------------------------------------------------
# PyPDF extractor  (application/pdf — native digital text PDFs only)
# ---------------------------------------------------------------------------


class PyPDFExtractor:
    """Extract text from native digital PDFs using the `pypdf` library.

    Scope constraints (from m3-architecture-lock.md):
      - No OCR.  Scanned/image PDFs that contain no embedded text layers produce
        an UNSUPPORTED result rather than attempting optical recognition.
      - No external API calls.
      - All extraction is synchronous and in-process; the async wrapper is a
        thin shim so that callers can use a uniform interface.
    """

    SUPPORTED_CONTENT_TYPE = "application/pdf"

    def __init__(self) -> None:
        self._method = "pypdf"
        self._version = _pypdf_version_string()

    async def extract_text(
        self,
        file_bytes: bytes,
        content_type: str,
    ) -> ExtractionResult:
        if content_type != self.SUPPORTED_CONTENT_TYPE:
            return ExtractionResult.unsupported(
                method=self._method,
                version=self._version,
                error=f"PyPDFExtractor does not handle content type: {content_type!r}",
            )

        if not file_bytes:
            return ExtractionResult.failed(
                method=self._method,
                version=self._version,
                error="PDF extraction failed: empty file bytes provided",
            )

        try:
            text = self._extract_sync(file_bytes)
        except Exception as exc:
            # Sanitise: do not surface file-system paths or internal stack details.
            logger.warning("pypdf extraction error: %s", type(exc).__name__)
            return ExtractionResult.failed(
                method=self._method,
                version=self._version,
                error=f"PDF extraction failed: {type(exc).__name__}",
            )

        normalised = _normalise_text(text)
        if not normalised.strip():
            return ExtractionResult.unsupported(
                method=self._method,
                version=self._version,
                error=(
                    "PDF extraction produced no text content. "
                    "The document may be a scanned image or contain only graphics."
                ),
            )

        return ExtractionResult.completed(
            text=normalised,
            method=self._method,
            version=self._version,
        )

    # ------------------------------------------------------------------
    # Synchronous extraction (isolated to ease unit-testing and profiling)
    # ------------------------------------------------------------------

    def _extract_sync(self, file_bytes: bytes) -> str:
        """Parse *file_bytes* with pypdf and concatenate all page text.

        Raises pypdf exceptions on malformed/encrypted PDFs so that the
        caller's try/except can capture and convert them to FAILED results.
        """
        from pypdf import PdfReader  # local import to defer until needed

        from app.health.chunking import PAGE_DELIMITER

        reader = PdfReader(io.BytesIO(file_bytes))
        parts: list[str] = []
        for page in reader.pages:
            page_text = page.extract_text() or ""
            parts.append(page_text)
        return PAGE_DELIMITER.join(parts)


# ---------------------------------------------------------------------------
# Plain-text extractor  (text/plain)
# ---------------------------------------------------------------------------


class PlainTextExtractor:
    """Decode plain-text files (text/plain) as UTF-8.

    Handles:
      - Valid UTF-8 byte sequences.
      - Invalid UTF-8 sequences replaced with the Unicode replacement character
        (U+FFFD) rather than raising; clinical text with encoding artefacts is
        preferable to a hard FAILED status.
      - Empty files → FAILED result.
    """

    SUPPORTED_CONTENT_TYPE = "text/plain"

    def __init__(self) -> None:
        self._method = "text/plain"
        self._version = _plain_text_version_string()

    async def extract_text(
        self,
        file_bytes: bytes,
        content_type: str,
    ) -> ExtractionResult:
        if not content_type.startswith(self.SUPPORTED_CONTENT_TYPE):
            err = f"PlainTextExtractor does not handle content type: {content_type!r}"
            return ExtractionResult.unsupported(
                method=self._method,
                version=self._version,
                error=err,
            )

        if not file_bytes:
            return ExtractionResult.failed(
                method=self._method,
                version=self._version,
                error="Plain text extraction failed: empty file bytes provided",
            )

        try:
            raw = file_bytes.decode("utf-8", errors="replace")
        except Exception as exc:
            logger.warning("Plain text decode error: %s", type(exc).__name__)
            return ExtractionResult.failed(
                method=self._method,
                version=self._version,
                error=f"Plain text decode failed: {type(exc).__name__}",
            )

        normalised = _normalise_text(raw)
        if not normalised.strip():
            return ExtractionResult.failed(
                method=self._method,
                version=self._version,
                error="Plain text extraction produced no text content",
            )

        return ExtractionResult.completed(
            text=normalised,
            method=self._method,
            version=self._version,
        )


# ---------------------------------------------------------------------------
# DispatchingExtractor — content-type registry
# ---------------------------------------------------------------------------


class DispatchingExtractor:
    """Routes extraction to the correct concrete extractor by content type.

    This is the primary entry point for all document extraction callers.
    New format support is added by registering an additional extractor
    without modifying call sites.

    The registry is consulted in insertion order; the first matching extractor
    wins.  Unrecognised content types return UNSUPPORTED without error.
    """

    def __init__(self, extractors: Optional[list[DocumentExtractor]] = None) -> None:
        if extractors is not None:
            self._extractors: list[DocumentExtractor] = extractors
        else:
            # Default registry: PDF first, then plain text.
            self._extractors = [
                PyPDFExtractor(),
                PlainTextExtractor(),
            ]

    async def extract_text(
        self,
        file_bytes: bytes,
        content_type: str,
    ) -> ExtractionResult:
        """Dispatch to the first registered extractor that accepts *content_type*.

        Returns UNSUPPORTED if no extractor claims the content type.
        """
        # Normalise content type to bare MIME type (strip parameters like charset).
        bare_mime = content_type.split(";")[0].strip().lower()

        for extractor in self._extractors:
            supported = getattr(extractor, "SUPPORTED_CONTENT_TYPE", None)
            if supported is not None and not bare_mime.startswith(supported):
                continue

            result = await extractor.extract_text(file_bytes, bare_mime)
            if result.status != "UNSUPPORTED":
                return result

            # If the extractor was targeted for this content type and returned
            # UNSUPPORTED (e.g. image-only PDF), return that specific result
            # rather than falling through to generic unhandled errors.
            if supported is not None:
                return result

        return ExtractionResult.unsupported(
            error=f"No extractor registered for content type: {content_type!r}",
        )
