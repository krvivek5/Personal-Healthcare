"""
Thin async S3-compatible storage adapter using aiobotocore.

Design decisions:
- All public functions use lazy/first-use bucket initialization via ensure_bucket().
  MinIO does not need to be reachable when the backend starts or when unrelated
  endpoints are served.
- The bucket is created only when the first document operation occurs.
- _bucket_ready is a module-level flag so ensure_bucket() is a one-shot check
  per process (not per request).
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

from aiobotocore.session import get_session  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from app.core.config import settings

# ── Chunk size for streaming downloads (8 KiB) ─────────────────────────────
_CHUNK_SIZE = 8 * 1024

# ── Lazy bucket-ready flag ──────────────────────────────────────────────────
# Reset to False between tests if needed by overriding _bucket_ready directly.
_bucket_ready: bool = False


# ── Internal: session context ───────────────────────────────────────────────


@contextlib.asynccontextmanager
async def _s3_client() -> AsyncIterator[Any]:
    """Yield a configured aiobotocore S3 client."""
    session = get_session()
    async with session.create_client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        # MinIO uses path-style addressing (endpoint/<bucket>/<key>).
        config=_boto_config(),
    ) as client:
        yield client


def _boto_config() -> Any:
    """Return a botocore Config object with path-style addressing."""
    from botocore.config import Config  # type: ignore[import-untyped]

    return Config(s3={"addressing_style": "path"})


# ── Public API ───────────────────────────────────────────────────────────────


async def ensure_bucket() -> None:
    """
    Create the configured bucket if it does not exist.

    Uses lazy/first-use initialization: this function is called by upload_file,
    download_file, and delete_file on their first invocation.  It is a no-op
    on subsequent calls within the same process.

    Requires MinIO to be reachable only when a document operation is first
    attempted, not at application startup.
    """
    global _bucket_ready
    if _bucket_ready:
        return

    bucket = settings.S3_BUCKET_NAME
    async with _s3_client() as client:
        try:
            await client.head_bucket(Bucket=bucket)
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]  # type: ignore[index]
            if error_code in ("404", "NoSuchBucket"):
                await client.create_bucket(Bucket=bucket)
            else:
                raise

    _bucket_ready = True


async def upload_file(key: str, data: bytes, content_type: str) -> None:
    """
    Upload *data* to the given *key* in the configured S3 bucket.

    Args:
        key:          S3 object key, e.g. ``documents/{patient_id}/{uuid}``.
        data:         Raw file bytes to upload.
        content_type: MIME type, e.g. ``application/pdf``.

    Raises:
        ClientError: on S3 communication or permission errors.
    """
    await ensure_bucket()
    async with _s3_client() as client:
        await client.put_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=key,
            Body=data,
            ContentType=content_type,
        )


async def download_file(key: str) -> AsyncIterator[bytes]:
    """
    Stream the object at *key* from the configured S3 bucket.

    Yields chunks of ``_CHUNK_SIZE`` bytes so the caller can stream the
    response to the HTTP client without loading the whole object into memory.

    Args:
        key: S3 object key to retrieve.

    Raises:
        ClientError: if the object does not exist or cannot be retrieved.
    """
    await ensure_bucket()
    async with _s3_client() as client:
        response = await client.get_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=key,
        )
        async with response["Body"] as stream:
            async for chunk in stream.iter_chunks(chunk_size=_CHUNK_SIZE):
                yield chunk


async def delete_file(key: str) -> None:
    """
    Delete the object at *key* from the configured S3 bucket.

    MinIO returns a 204 for both existing and non-existing keys (idempotent),
    so this function succeeds even if the object was already absent.

    Args:
        key: S3 object key to delete.

    Raises:
        ClientError: on S3 communication or permission errors.
    """
    await ensure_bucket()
    async with _s3_client() as client:
        await client.delete_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=key,
        )
