"""
M3 Slice 2 — Tests for backend/app/health/extraction.py.

Coverage:
  ExtractionResult
    - Valid COMPLETED, FAILED, UNSUPPORTED construction.
    - Constructor invariant: COMPLETED requires non-empty text.
    - Constructor invariant: FAILED/UNSUPPORTED must not carry text.
    - Convenience constructors: completed(), failed(), unsupported().
    - Frozen / immutable.

  _normalise_text
    - NUL bytes stripped.
    - \r\n → \n normalised.
    - Lone \r → \n normalised.
    - Mixed whitespace preserved.

  PyPDFExtractor
    - UNSUPPORTED returned for non-PDF content type.
    - FAILED returned for empty bytes.
    - COMPLETED for a minimal single-page native digital PDF.
    - COMPLETED for a multi-page PDF.
    - FAILED for a malformed/truncated PDF binary.
    - UNSUPPORTED for a PDF whose pages contain no text layer (image-only PDF).
    - Content type with charset parameter is handled (bare MIME extracted).

  PlainTextExtractor
    - UNSUPPORTED returned for non-text/plain content type.
    - FAILED returned for empty bytes.
    - COMPLETED for valid ASCII text.
    - COMPLETED for valid UTF-8 text.
    - COMPLETED for invalid UTF-8 bytes (replacement character substitution).
    - FAILED for whitespace-only bytes.
    - NUL bytes are stripped before status determination.
    - Line endings normalised.

  DispatchingExtractor
    - Routes application/pdf to PyPDFExtractor.
    - Routes text/plain to PlainTextExtractor.
    - Returns UNSUPPORTED for unregistered content type.
    - Strips content-type parameters (e.g. "text/plain; charset=utf-8").
    - Custom extractor list is respected.
    - First COMPLETED result wins (no double-dispatch).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.health.extraction import (
    DispatchingExtractor,
    ExtractionResult,
    PlainTextExtractor,
    PyPDFExtractor,
    _normalise_text,
)

# ---------------------------------------------------------------------------
# Minimal PDF helpers
# ---------------------------------------------------------------------------


def _build_minimal_pdf(text: str = "Hello Patient") -> bytes:
    """Produce a minimal but structurally valid single-page PDF with embedded text.

    This is a hand-crafted PDF that uses a subset of PDF operators just large
    enough to contain a text stream that pypdf can extract.  It is intentionally
    small and does not rely on any external tooling.
    """
    content_stream = (f"BT\n/F1 12 Tf\n72 720 Td\n({text}) Tj\nET\n").encode("latin-1")

    stream_len = len(content_stream)

    body = (
        "%PDF-1.4\n"
        "1 0 obj\n"
        "<< /Type /Catalog /Pages 2 0 R >>\n"
        "endobj\n"
        "\n"
        "2 0 obj\n"
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>\n"
        "endobj\n"
        "\n"
        "3 0 obj\n"
        "<< /Type /Page /Parent 2 0 R "
        "/MediaBox [0 0 612 792] "
        "/Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>\n"
        "endobj\n"
        "\n"
        "4 0 obj\n"
        f"<< /Length {stream_len} >>\n"
        "stream\n"
    ).encode("latin-1")

    body += content_stream
    body += b"\nendstream\nendobj\n\n"
    body += (
        "5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
    ).encode("latin-1")

    xref_pos = len(body)
    body += (
        "xref\n"
        "0 6\n"
        "0000000000 65535 f \n"
        "0000000009 00000 n \n"
        "0000000058 00000 n \n"
        "0000000115 00000 n \n"
        "0000000266 00000 n \n"
        f"{'0000000000':0>10} 00000 n \n"
        "trailer\n"
        "<< /Size 6 /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode("latin-1")
    return body


def _build_empty_text_pdf() -> bytes:
    """Produce a PDF whose single page has an empty content stream (no text layer)."""
    content_stream = b""
    stream_len = 0

    body = (
        "%PDF-1.4\n"
        "1 0 obj\n"
        "<< /Type /Catalog /Pages 2 0 R >>\n"
        "endobj\n"
        "\n"
        "2 0 obj\n"
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>\n"
        "endobj\n"
        "\n"
        "3 0 obj\n"
        "<< /Type /Page /Parent 2 0 R "
        "/MediaBox [0 0 612 792] "
        "/Contents 4 0 R "
        "/Resources << >> >>\n"
        "endobj\n"
        "\n"
        "4 0 obj\n"
        f"<< /Length {stream_len} >>\n"
        "stream\n"
    ).encode("latin-1")

    body += content_stream
    body += b"\nendstream\nendobj\n\n"

    xref_pos = len(body)
    body += (
        "xref\n"
        "0 5\n"
        "0000000000 65535 f \n"
        "0000000009 00000 n \n"
        "0000000058 00000 n \n"
        "0000000115 00000 n \n"
        "0000000230 00000 n \n"
        "trailer\n"
        "<< /Size 5 /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode("latin-1")
    return body


# ---------------------------------------------------------------------------
# ExtractionResult tests
# ---------------------------------------------------------------------------


class TestExtractionResult:
    def test_completed_valid(self) -> None:
        r = ExtractionResult(
            status="COMPLETED",
            extraction_method="pypdf",
            extraction_version="pypdf/4.0.0",
            extracted_text="Lab report text",
        )
        assert r.status == "COMPLETED"
        assert r.extracted_text == "Lab report text"
        assert r.error_message is None

    def test_failed_valid(self) -> None:
        r = ExtractionResult(
            status="FAILED",
            extraction_method="pypdf",
            extraction_version="pypdf/4.0.0",
            error_message="corrupt PDF",
        )
        assert r.status == "FAILED"
        assert r.extracted_text is None
        assert r.error_message == "corrupt PDF"

    def test_unsupported_valid(self) -> None:
        r = ExtractionResult(
            status="UNSUPPORTED",
            extraction_method="none",
            extraction_version="none",
        )
        assert r.status == "UNSUPPORTED"
        assert r.extracted_text is None
        assert r.error_message is None

    def test_completed_requires_nonempty_text(self) -> None:
        with pytest.raises(ValueError, match="non-empty extracted_text"):
            ExtractionResult(
                status="COMPLETED",
                extraction_method="pypdf",
                extraction_version="pypdf/4.0.0",
                extracted_text=None,
            )

    def test_completed_whitespace_only_text_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty extracted_text"):
            ExtractionResult(
                status="COMPLETED",
                extraction_method="pypdf",
                extraction_version="pypdf/4.0.0",
                extracted_text="   \n\t  ",
            )

    def test_failed_with_text_rejected(self) -> None:
        with pytest.raises(ValueError, match="null or empty extracted_text"):
            ExtractionResult(
                status="FAILED",
                extraction_method="pypdf",
                extraction_version="pypdf/4.0.0",
                extracted_text="some text",
            )

    def test_unsupported_with_text_rejected(self) -> None:
        with pytest.raises(ValueError, match="null or empty extracted_text"):
            ExtractionResult(
                status="UNSUPPORTED",
                extraction_method="none",
                extraction_version="none",
                extracted_text="hello",
            )

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be one of"):
            ExtractionResult(
                status="PENDING",
                extraction_method="pypdf",
                extraction_version="pypdf/4.0.0",
            )

    def test_frozen(self) -> None:
        r = ExtractionResult.completed(
            text="some text", method="pypdf", version="pypdf/4.0.0"
        )
        with pytest.raises((AttributeError, TypeError)):
            r.status = "FAILED"  # type: ignore[misc]

    def test_completed_constructor(self) -> None:
        r = ExtractionResult.completed(
            text="report text", method="pypdf", version="pypdf/4.1.0"
        )
        assert r.status == "COMPLETED"
        assert r.extracted_text == "report text"
        assert r.extraction_method == "pypdf"

    def test_failed_constructor(self) -> None:
        r = ExtractionResult.failed(
            method="pypdf", version="pypdf/4.0.0", error="bad PDF"
        )
        assert r.status == "FAILED"
        assert r.extracted_text is None
        assert r.error_message == "bad PDF"

    def test_unsupported_constructor_defaults(self) -> None:
        r = ExtractionResult.unsupported()
        assert r.status == "UNSUPPORTED"
        assert r.extraction_method == "none"
        assert r.extraction_version == "none"

    def test_unsupported_constructor_with_error(self) -> None:
        r = ExtractionResult.unsupported(error="type image/png not supported")
        assert r.status == "UNSUPPORTED"
        assert r.error_message == "type image/png not supported"


# ---------------------------------------------------------------------------
# _normalise_text tests
# ---------------------------------------------------------------------------


class TestNormaliseText:
    def test_nul_bytes_stripped(self) -> None:
        assert _normalise_text("hello\x00world") == "helloworld"

    def test_crlf_normalised(self) -> None:
        assert _normalise_text("line1\r\nline2") == "line1\nline2"

    def test_lone_cr_normalised(self) -> None:
        assert _normalise_text("line1\rline2") == "line1\nline2"

    def test_mixed_line_endings(self) -> None:
        result = _normalise_text("a\r\nb\rc\nd")
        assert result == "a\nb\nc\nd"

    def test_multiple_nul_bytes(self) -> None:
        result = _normalise_text("\x00hello\x00 \x00world\x00")
        assert "\x00" not in result
        assert "hello" in result
        assert "world" in result

    def test_no_modification_needed(self) -> None:
        text = "Patient Name: John\nDOB: 1990-01-01\nDiagnosis: Healthy"
        assert _normalise_text(text) == text

    def test_empty_string(self) -> None:
        assert _normalise_text("") == ""


# ---------------------------------------------------------------------------
# PyPDFExtractor tests
# ---------------------------------------------------------------------------


class TestPyPDFExtractor:
    @pytest.fixture()
    def extractor(self) -> PyPDFExtractor:
        return PyPDFExtractor()

    @pytest.mark.asyncio
    async def test_unsupported_for_non_pdf(self, extractor: PyPDFExtractor) -> None:
        result = await extractor.extract_text(b"anything", "text/plain")
        assert result.status == "UNSUPPORTED"

    @pytest.mark.asyncio
    async def test_unsupported_for_image_type(self, extractor: PyPDFExtractor) -> None:
        result = await extractor.extract_text(b"\x89PNG\r\n", "image/png")
        assert result.status == "UNSUPPORTED"

    @pytest.mark.asyncio
    async def test_failed_for_empty_bytes(self, extractor: PyPDFExtractor) -> None:
        result = await extractor.extract_text(b"", "application/pdf")
        assert result.status == "FAILED"
        assert "empty" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_failed_for_malformed_pdf(self, extractor: PyPDFExtractor) -> None:
        garbage = b"This is not a PDF file at all \x00\xff"
        result = await extractor.extract_text(garbage, "application/pdf")
        assert result.status == "FAILED"
        # Error message must not contain file paths or internal stack traces.
        assert "/" not in (result.error_message or "")
        assert "\\" not in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_failed_for_truncated_pdf(self, extractor: PyPDFExtractor) -> None:
        truncated = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog"  # abruptly ends
        result = await extractor.extract_text(truncated, "application/pdf")
        assert result.status == "FAILED"

    @pytest.mark.asyncio
    async def test_completed_for_valid_pdf(self, extractor: PyPDFExtractor) -> None:
        pdf_bytes = _build_minimal_pdf("Creatinine 0.9 mg/dL")
        result = await extractor.extract_text(pdf_bytes, "application/pdf")
        assert result.status == "COMPLETED"
        assert result.extracted_text is not None
        assert result.extracted_text.strip() != ""
        assert result.extraction_method == "pypdf"
        assert result.extraction_version.startswith("pypdf/")

    @pytest.mark.asyncio
    async def test_no_text_layer_returns_unsupported(
        self, extractor: PyPDFExtractor
    ) -> None:
        """A PDF with an empty content stream (image-only simulation) → UNSUPPORTED."""
        pdf_bytes = _build_empty_text_pdf()
        result = await extractor.extract_text(pdf_bytes, "application/pdf")
        # Image-only PDFs produce empty text → UNSUPPORTED with diagnostic error.
        assert result.status == "UNSUPPORTED"
        assert result.extracted_text is None
        assert result.extraction_method == "pypdf"
        assert result.error_message is not None
        assert "scanned" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_extraction_method_and_version_set(
        self, extractor: PyPDFExtractor
    ) -> None:
        pdf_bytes = _build_minimal_pdf("Test document content")
        result = await extractor.extract_text(pdf_bytes, "application/pdf")
        assert result.extraction_method == "pypdf"
        assert "/" in result.extraction_version  # e.g. "pypdf/4.x.x"

    @pytest.mark.asyncio
    async def test_nul_bytes_stripped_from_output(
        self, extractor: PyPDFExtractor
    ) -> None:
        """Verify _normalise_text integration: NUL bytes don't reach the caller."""
        # We mock _extract_sync to return a string containing NUL bytes.
        with patch.object(extractor, "_extract_sync", return_value="Report\x00Data"):
            result = await extractor.extract_text(b"fake-pdf", "application/pdf")
        assert result.status == "COMPLETED"
        assert "\x00" not in (result.extracted_text or "")


# ---------------------------------------------------------------------------
# PlainTextExtractor tests
# ---------------------------------------------------------------------------


class TestPlainTextExtractor:
    @pytest.fixture()
    def extractor(self) -> PlainTextExtractor:
        return PlainTextExtractor()

    @pytest.mark.asyncio
    async def test_unsupported_for_pdf(self, extractor: PlainTextExtractor) -> None:
        result = await extractor.extract_text(b"%PDF-1.4", "application/pdf")
        assert result.status == "UNSUPPORTED"

    @pytest.mark.asyncio
    async def test_unsupported_for_image(self, extractor: PlainTextExtractor) -> None:
        result = await extractor.extract_text(b"\x89PNG", "image/jpeg")
        assert result.status == "UNSUPPORTED"

    @pytest.mark.asyncio
    async def test_failed_for_empty_bytes(self, extractor: PlainTextExtractor) -> None:
        result = await extractor.extract_text(b"", "text/plain")
        assert result.status == "FAILED"
        assert "empty" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_failed_for_whitespace_only(
        self, extractor: PlainTextExtractor
    ) -> None:
        result = await extractor.extract_text(b"   \n\t\r\n  ", "text/plain")
        assert result.status == "FAILED"

    @pytest.mark.asyncio
    async def test_completed_for_ascii_text(
        self, extractor: PlainTextExtractor
    ) -> None:
        text = b"Patient: Jane Doe\nHbA1c: 5.6%\nCholesterol: 180 mg/dL"
        result = await extractor.extract_text(text, "text/plain")
        assert result.status == "COMPLETED"
        assert "Jane Doe" in (result.extracted_text or "")
        assert result.extraction_method == "text/plain"
        assert result.extraction_version == "text-plain/1.0"

    @pytest.mark.asyncio
    async def test_completed_for_utf8_text(self, extractor: PlainTextExtractor) -> None:
        text = "Diagnosis: Hépatite B\nMédecin: Dr. Müller".encode("utf-8")
        result = await extractor.extract_text(text, "text/plain")
        assert result.status == "COMPLETED"
        assert "Hépatite" in (result.extracted_text or "")

    @pytest.mark.asyncio
    async def test_completed_for_invalid_utf8_with_replacement(
        self, extractor: PlainTextExtractor
    ) -> None:
        """Invalid UTF-8 bytes should produce COMPLETED with replacement chars."""
        # \xff\xfe is a BOM-like sequence not valid as UTF-8.
        invalid_utf8 = b"Patient data: \xff\xfe some content after"
        result = await extractor.extract_text(invalid_utf8, "text/plain")
        # Should succeed with replacement characters, not fail.
        assert result.status == "COMPLETED"
        assert result.extracted_text is not None
        # Replacement character (U+FFFD) should appear.
        assert "\ufffd" in result.extracted_text

    @pytest.mark.asyncio
    async def test_nul_bytes_stripped(self, extractor: PlainTextExtractor) -> None:
        text = b"Lab Result\x00: Normal\x00"
        result = await extractor.extract_text(text, "text/plain")
        assert result.status == "COMPLETED"
        assert "\x00" not in (result.extracted_text or "")
        assert "Lab Result" in (result.extracted_text or "")

    @pytest.mark.asyncio
    async def test_crlf_line_endings_normalised(
        self, extractor: PlainTextExtractor
    ) -> None:
        text = b"Line 1\r\nLine 2\r\nLine 3"
        result = await extractor.extract_text(text, "text/plain")
        assert result.status == "COMPLETED"
        assert "\r\n" not in (result.extracted_text or "")
        assert "Line 1\nLine 2\nLine 3" in (result.extracted_text or "")

    @pytest.mark.asyncio
    async def test_content_type_with_charset_parameter(
        self, extractor: PlainTextExtractor
    ) -> None:
        """text/plain; charset=utf-8 should still be handled."""
        text = b"Medical record content here"
        result = await extractor.extract_text(text, "text/plain; charset=utf-8")
        assert result.status == "COMPLETED"


# ---------------------------------------------------------------------------
# DispatchingExtractor tests
# ---------------------------------------------------------------------------


class TestDispatchingExtractor:
    @pytest.mark.asyncio
    async def test_pdf_routes_to_pypdf(self) -> None:
        dispatcher = DispatchingExtractor()
        pdf_bytes = _build_minimal_pdf("Kidney function report")
        result = await dispatcher.extract_text(pdf_bytes, "application/pdf")
        assert result.status == "COMPLETED"
        assert result.extraction_method == "pypdf"

    @pytest.mark.asyncio
    async def test_plain_text_routes_to_plain_extractor(self) -> None:
        dispatcher = DispatchingExtractor()
        result = await dispatcher.extract_text(b"Blood pressure: 120/80", "text/plain")
        assert result.status == "COMPLETED"
        assert result.extraction_method == "text/plain"

    @pytest.mark.asyncio
    async def test_unsupported_content_type(self) -> None:
        dispatcher = DispatchingExtractor()
        result = await dispatcher.extract_text(b"\x89PNG", "image/png")
        assert result.status == "UNSUPPORTED"
        assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_image_only_pdf_returns_unsupported_via_dispatcher(self) -> None:
        """Dispatcher preserves UNSUPPORTED status and diagnostic error
        for image-only PDFs.
        """
        dispatcher = DispatchingExtractor()
        pdf_bytes = _build_empty_text_pdf()
        result = await dispatcher.extract_text(pdf_bytes, "application/pdf")
        assert result.status == "UNSUPPORTED"
        assert result.extracted_text is None
        assert result.extraction_method == "pypdf"
        assert result.error_message is not None
        assert "scanned" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_unsupported_docx(self) -> None:
        dispatcher = DispatchingExtractor()
        result = await dispatcher.extract_text(
            b"PK\x03\x04",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        assert result.status == "UNSUPPORTED"

    @pytest.mark.asyncio
    async def test_content_type_parameter_stripped(self) -> None:
        """text/plain; charset=utf-8 should dispatch to PlainTextExtractor."""
        dispatcher = DispatchingExtractor()
        result = await dispatcher.extract_text(
            b"Discharge summary", "text/plain; charset=utf-8"
        )
        assert result.status == "COMPLETED"
        assert result.extraction_method == "text/plain"

    @pytest.mark.asyncio
    async def test_custom_extractor_list(self) -> None:
        """Custom extractor list overrides the default registry."""

        class AlwaysUnsupported:
            async def extract_text(
                self, file_bytes: bytes, content_type: str
            ) -> ExtractionResult:
                return ExtractionResult.unsupported(error="no extractors configured")

        dispatcher = DispatchingExtractor(extractors=[AlwaysUnsupported()])
        result = await dispatcher.extract_text(b"anything", "application/pdf")
        assert result.status == "UNSUPPORTED"

    @pytest.mark.asyncio
    async def test_first_completed_result_wins(self) -> None:
        """If the first extractor returns COMPLETED, the second is not called."""

        class FirstExtractor:
            called = 0

            async def extract_text(
                self, file_bytes: bytes, content_type: str
            ) -> ExtractionResult:
                FirstExtractor.called += 1
                return ExtractionResult.completed(
                    text="First result", method="first", version="1.0"
                )

        class SecondExtractor:
            called = 0

            async def extract_text(
                self, file_bytes: bytes, content_type: str
            ) -> ExtractionResult:
                SecondExtractor.called += 1
                return ExtractionResult.completed(
                    text="Second result", method="second", version="1.0"
                )

        dispatcher = DispatchingExtractor(
            extractors=[FirstExtractor(), SecondExtractor()]
        )
        result = await dispatcher.extract_text(b"data", "application/pdf")
        assert result.extraction_method == "first"
        assert SecondExtractor.called == 0

    @pytest.mark.asyncio
    async def test_failed_result_is_returned_not_skipped(self) -> None:
        """FAILED results are returned immediately — not bypassed like UNSUPPORTED."""

        class FailingExtractor:
            async def extract_text(
                self, file_bytes: bytes, content_type: str
            ) -> ExtractionResult:
                return ExtractionResult.failed(
                    method="failing", version="1.0", error="always fails"
                )

        class FallbackExtractor:
            called = 0

            async def extract_text(
                self, file_bytes: bytes, content_type: str
            ) -> ExtractionResult:
                FallbackExtractor.called += 1
                return ExtractionResult.completed(
                    text="fallback text", method="fallback", version="1.0"
                )

        dispatcher = DispatchingExtractor(
            extractors=[FailingExtractor(), FallbackExtractor()]
        )
        result = await dispatcher.extract_text(b"data", "application/pdf")
        # FAILED propagates; fallback never reached.
        assert result.status == "FAILED"
        assert FallbackExtractor.called == 0
