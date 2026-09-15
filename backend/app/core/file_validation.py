"""
File validation for medical document uploads.

Design:
- Bounded reads: the file is read incrementally in chunks; validation never
  loads an arbitrarily large file into memory.
- Magic-byte verification: the first chunk is inspected against the declared
  MIME type so that a renamed file cannot bypass content-type checks.
- Size limit: cumulative bytes are tracked; the upload is rejected with 413
  as soon as the 20 MiB cap is exceeded.
- After validation succeeds the caller must rewind/reopen the upload before
  streaming it to S3 (FastAPI UploadFile.seek(0)).

Supported formats
-----------------
| MIME type         | Magic signature                         |
|-------------------|-----------------------------------------|
| application/pdf   | %PDF  (0x25 0x50 0x44 0x46)             |
| image/jpeg        | FF D8 FF                                |
| image/png         | 89 50 4E 47 0D 0A 1A 0A                 |
"""

from __future__ import annotations

from fastapi import HTTPException, UploadFile, status

# ── Constants ──────────────────────────────────────────────────────────────────

MAX_FILE_SIZE_BYTES: int = 20 * 1024 * 1024  # 20 MiB
_CHUNK_SIZE: int = 64 * 1024  # 64 KiB read chunks

ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/png",
    }
)

# Magic-byte signatures: (offset, expected_prefix)
_MAGIC: dict[str, bytes] = {
    "application/pdf": b"%PDF",
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
}


# ── Public API ─────────────────────────────────────────────────────────────────


async def validate_upload(file: UploadFile) -> tuple[str, int]:
    """
    Validate *file* for MIME type, magic bytes, and size.

    Reads the file incrementally to avoid loading large files into memory.
    The caller must call ``await file.seek(0)`` after this function returns
    before streaming the file data to S3.

    Args:
        file: FastAPI ``UploadFile`` from a multipart request.

    Returns:
        ``(content_type, file_size_bytes)`` on success.

    Raises:
        HTTPException(422): declared MIME type is not allowed, or the file
            content does not match the declared MIME type.
        HTTPException(413): file exceeds the 20 MiB size limit.
    """
    declared_ct = (file.content_type or "").strip().lower()

    # 1. Reject disallowed declared MIME type immediately (before any reads).
    if declared_ct not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Unsupported file type: '{declared_ct}'. "
                f"Allowed types: {sorted(ALLOWED_CONTENT_TYPES)}"
            ),
        )

    total_bytes = 0
    first_chunk = True
    expected_magic = _MAGIC[declared_ct]

    while True:
        chunk: bytes = await file.read(_CHUNK_SIZE)
        if not chunk:
            break

        # 2. Magic-byte check on the very first chunk.
        if first_chunk:
            if not chunk.startswith(expected_magic):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"File content does not match declared type '{declared_ct}'. "
                        "The file signature (magic bytes) is invalid."
                    ),
                )
            first_chunk = False

        # 3. Cumulative size check.
        total_bytes += len(chunk)
        if total_bytes > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"File exceeds the maximum allowed size of "
                    f"{MAX_FILE_SIZE_BYTES // (1024 * 1024)} MiB."
                ),
            )

    if first_chunk:
        # File was empty — no chunk was ever read.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file is empty.",
        )

    return declared_ct, total_bytes
