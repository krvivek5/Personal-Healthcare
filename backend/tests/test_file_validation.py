"""
M4-2: Unit tests for the file validation module (app.core.file_validation).

All tests use in-memory fake UploadFile objects — no real files or MinIO.

Covers:
- Allowed MIME types with correct magic bytes → passes
- Disallowed MIME type → 422
- MIME/magic mismatch → 422
- Oversized file (exceeds 20 MiB) → 413
- Empty file → 422
- Exact boundary: 20 MiB (allowed) and 20 MiB + 1 byte (rejected)
"""

from __future__ import annotations

import io

import pytest

from app.core.file_validation import (
    ALLOWED_CONTENT_TYPES,
    MAX_FILE_SIZE_BYTES,
    validate_upload,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

# Magic bytes for each supported type
_PDF_MAGIC = b"%PDF-1.4 "
_JPEG_MAGIC = b"\xff\xd8\xff\xe0" + b"\x00" * 10
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10


class FakeUploadFile:
    """Minimal fake of fastapi.UploadFile for testing validate_upload."""

    def __init__(self, content: bytes, content_type: str) -> None:
        self._buf = io.BytesIO(content)
        self.content_type = content_type
        self.filename = "testfile"

    async def read(self, size: int = -1) -> bytes:
        return self._buf.read(size)

    async def seek(self, position: int) -> None:
        self._buf.seek(position)


def make_file(content: bytes, content_type: str) -> FakeUploadFile:
    return FakeUploadFile(content, content_type)


# ── Valid uploads ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_pdf_with_correct_magic():
    """Valid PDF with correct magic bytes returns (application/pdf, size)."""
    content = _PDF_MAGIC + b"fake body"
    f = make_file(content, "application/pdf")
    ct, size = await validate_upload(f)
    assert ct == "application/pdf"
    assert size == len(content)


@pytest.mark.asyncio
async def test_validate_jpeg_with_correct_magic():
    """Valid JPEG with correct magic bytes returns (image/jpeg, size)."""
    content = _JPEG_MAGIC + b"fake jpeg body"
    f = make_file(content, "image/jpeg")
    ct, size = await validate_upload(f)
    assert ct == "image/jpeg"
    assert size == len(content)


@pytest.mark.asyncio
async def test_validate_png_with_correct_magic():
    """Valid PNG with correct magic bytes returns (image/png, size)."""
    content = _PNG_MAGIC + b"fake png body"
    f = make_file(content, "image/png")
    ct, size = await validate_upload(f)
    assert ct == "image/png"
    assert size == len(content)


@pytest.mark.asyncio
async def test_allowed_content_types_coverage():
    """Ensure ALLOWED_CONTENT_TYPES contains exactly the three expected types."""
    assert ALLOWED_CONTENT_TYPES == frozenset(
        {"application/pdf", "image/jpeg", "image/png"}
    )


# ── Disallowed MIME type ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_disallowed_mime_type_returns_422():
    """Disallowed MIME type (e.g. text/plain) is rejected immediately with 422."""
    from fastapi import HTTPException

    f = make_file(b"some content", "text/plain")
    with pytest.raises(HTTPException) as exc_info:
        await validate_upload(f)
    assert exc_info.value.status_code == 422
    assert "Unsupported file type" in exc_info.value.detail


@pytest.mark.asyncio
async def test_application_octet_stream_rejected():
    """application/octet-stream is disallowed even with a valid magic sequence."""
    from fastapi import HTTPException

    f = make_file(_PDF_MAGIC + b"content", "application/octet-stream")
    with pytest.raises(HTTPException) as exc_info:
        await validate_upload(f)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_empty_content_type_rejected():
    """An empty content_type string is treated as disallowed."""
    from fastapi import HTTPException

    f = make_file(_PDF_MAGIC, "")
    with pytest.raises(HTTPException) as exc_info:
        await validate_upload(f)
    assert exc_info.value.status_code == 422


# ── Magic-byte / MIME mismatch ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pdf_mime_with_jpeg_magic_returns_422():
    """Declaring application/pdf but supplying JPEG bytes → 422."""
    from fastapi import HTTPException

    f = make_file(_JPEG_MAGIC + b"fake", "application/pdf")
    with pytest.raises(HTTPException) as exc_info:
        await validate_upload(f)
    assert exc_info.value.status_code == 422
    assert "magic bytes" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_jpeg_mime_with_png_magic_returns_422():
    """Declaring image/jpeg but supplying PNG bytes → 422."""
    from fastapi import HTTPException

    f = make_file(_PNG_MAGIC + b"fake", "image/jpeg")
    with pytest.raises(HTTPException) as exc_info:
        await validate_upload(f)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_png_mime_with_pdf_magic_returns_422():
    """Declaring image/png but supplying PDF bytes → 422."""
    from fastapi import HTTPException

    f = make_file(_PDF_MAGIC + b"fake", "image/png")
    with pytest.raises(HTTPException) as exc_info:
        await validate_upload(f)
    assert exc_info.value.status_code == 422


# ── Size validation ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_oversized_file_returns_413():
    """A file exceeding 20 MiB is rejected with 413."""
    from fastapi import HTTPException

    # Build content just over the limit
    oversized = _PDF_MAGIC + b"x" * (MAX_FILE_SIZE_BYTES + 1)
    f = make_file(oversized, "application/pdf")
    with pytest.raises(HTTPException) as exc_info:
        await validate_upload(f)
    assert exc_info.value.status_code == 413


@pytest.mark.asyncio
async def test_file_exactly_at_limit_passes():
    """A file of exactly 20 MiB is accepted."""
    payload = _PDF_MAGIC + b"x" * (MAX_FILE_SIZE_BYTES - len(_PDF_MAGIC))
    assert len(payload) == MAX_FILE_SIZE_BYTES
    f = make_file(payload, "application/pdf")
    ct, size = await validate_upload(f)
    assert size == MAX_FILE_SIZE_BYTES


@pytest.mark.asyncio
async def test_file_one_byte_over_limit_rejected():
    """A file of exactly 20 MiB + 1 byte is rejected with 413."""
    from fastapi import HTTPException

    payload = _PDF_MAGIC + b"x" * (MAX_FILE_SIZE_BYTES - len(_PDF_MAGIC) + 1)
    assert len(payload) == MAX_FILE_SIZE_BYTES + 1
    f = make_file(payload, "application/pdf")
    with pytest.raises(HTTPException) as exc_info:
        await validate_upload(f)
    assert exc_info.value.status_code == 413


# ── Empty file ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_file_returns_422():
    """An empty file (zero bytes) is rejected with 422."""
    from fastapi import HTTPException

    f = make_file(b"", "application/pdf")
    with pytest.raises(HTTPException) as exc_info:
        await validate_upload(f)
    assert exc_info.value.status_code == 422
    assert "empty" in exc_info.value.detail.lower()
