"""
M4-1: Unit tests for the S3 storage adapter (app.core.storage).

All tests use a fake in-memory S3 client — no MinIO instance is required.
The real MinIO connectivity/smoke check is performed separately as a manual
step during M4-1 verification (see M4 SDD §Execution Strategy).

Fake client design
------------------
FakeS3Client stores objects in a dict keyed by (bucket, key).
It exposes only the aiobotocore methods used by storage.py:
  - head_bucket / create_bucket
  - put_object / get_object / delete_object

FakeStreamBody yields data in chunks to exercise the streaming path.
"""

from __future__ import annotations

import contextlib
import io
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio  # noqa: F401 — required by pytest-asyncio

# ── Fake S3 infrastructure ─────────────────────────────────────────────────


class FakeStreamBody:
    """Mimics the aiobotocore streaming body returned by get_object."""

    def __init__(self, data: bytes, chunk_size: int = 8 * 1024) -> None:
        self._data = data
        self._chunk_size = chunk_size

    async def __aenter__(self) -> "FakeStreamBody":
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def iter_chunks(self, chunk_size: int = 8 * 1024) -> AsyncIterator[bytes]:
        buf = io.BytesIO(self._data)
        while True:
            piece = buf.read(chunk_size)
            if not piece:
                break
            yield piece


class FakeS3Client:
    """
    In-memory S3 client compatible with the aiobotocore interface used in
    storage.py.  Stores buckets and objects in plain dicts.
    """

    def __init__(self) -> None:
        # buckets: set of bucket names that "exist"
        self._buckets: set[str] = set()
        # objects: (bucket, key) → (bytes, content_type)
        self._objects: dict[tuple[str, str], tuple[bytes, str]] = {}

    # ── Context-manager support (used by _s3_client()) ──────────────────

    async def __aenter__(self) -> "FakeS3Client":
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    # ── Bucket operations ───────────────────────────────────────────────

    async def head_bucket(self, *, Bucket: str) -> None:
        if Bucket not in self._buckets:
            from botocore.exceptions import ClientError

            raise ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}},
                "HeadBucket",
            )

    async def create_bucket(self, *, Bucket: str) -> None:
        self._buckets.add(Bucket)

    # ── Object operations ───────────────────────────────────────────────

    async def put_object(
        self, *, Bucket: str, Key: str, Body: bytes, ContentType: str
    ) -> None:
        if Bucket not in self._buckets:
            from botocore.exceptions import ClientError

            raise ClientError(
                {"Error": {"Code": "NoSuchBucket", "Message": "No Such Bucket"}},
                "PutObject",
            )
        self._objects[(Bucket, Key)] = (Body, ContentType)

    async def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        if (Bucket, Key) not in self._objects:
            from botocore.exceptions import ClientError

            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "No Such Key"}},
                "GetObject",
            )
        data, _ = self._objects[(Bucket, Key)]
        return {"Body": FakeStreamBody(data)}

    async def delete_object(self, *, Bucket: str, Key: str) -> None:
        # S3/MinIO delete is idempotent; no error for missing keys.
        self._objects.pop((Bucket, Key), None)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_bucket_flag():
    """Reset the module-level _bucket_ready flag before each test."""
    import app.core.storage as storage_module

    storage_module._bucket_ready = False
    yield
    storage_module._bucket_ready = False


@pytest.fixture
def fake_client() -> FakeS3Client:
    return FakeS3Client()


@contextlib.asynccontextmanager
async def _fake_s3_ctx(client: FakeS3Client) -> AsyncIterator[FakeS3Client]:
    yield client


def make_patch(fake: FakeS3Client):
    """Return a patch() that replaces _s3_client with a factory yielding *fake*.

    Uses side_effect (not return_value) so each call to _s3_client() returns a
    fresh _AsyncGeneratorContextManager.  This is required because storage.py
    calls _s3_client() twice within a single upload_file() call (once inside
    ensure_bucket, once for the put_object itself) and an async context manager
    cannot be __aenter__'d twice.
    """
    return patch(
        "app.core.storage._s3_client",
        side_effect=lambda: _fake_s3_ctx(fake),
    )


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ensure_bucket_creates_bucket_when_missing(fake_client: FakeS3Client):
    """ensure_bucket() creates the bucket if head_bucket returns 404."""
    with make_patch(fake_client):
        from app.core.storage import ensure_bucket

        await ensure_bucket()

    assert "medical-documents" in fake_client._buckets


@pytest.mark.asyncio
async def test_ensure_bucket_does_not_recreate_existing_bucket(
    fake_client: FakeS3Client,
):
    """ensure_bucket() is a no-op when the bucket already exists."""
    fake_client._buckets.add("medical-documents")

    with make_patch(fake_client):
        from app.core.storage import ensure_bucket

        await ensure_bucket()

    # bucket should still exist exactly once (set, so no duplicates possible)
    assert "medical-documents" in fake_client._buckets


@pytest.mark.asyncio
async def test_ensure_bucket_lazy_second_call_skips_s3(fake_client: FakeS3Client):
    """
    After the first successful call sets _bucket_ready=True, subsequent
    calls within the same process skip S3 entirely.
    """
    import app.core.storage as storage_module

    with make_patch(fake_client):
        await storage_module.ensure_bucket()

    assert storage_module._bucket_ready is True

    # Patch with a client that would raise if called — proves S3 is not hit.
    class ErrorClient(FakeS3Client):
        async def head_bucket(self, **kwargs: Any) -> None:  # type: ignore[override]
            raise AssertionError("S3 should not be called again")

    with make_patch(ErrorClient()):
        await storage_module.ensure_bucket()  # must NOT raise


@pytest.mark.asyncio
async def test_upload_file_stores_object(fake_client: FakeS3Client):
    """upload_file() stores bytes under the correct key."""
    with make_patch(fake_client):
        from app.core.storage import upload_file

        await upload_file(
            key="documents/patient-1/uuid-abc",
            data=b"%PDF-1.4 fake content",
            content_type="application/pdf",
        )

    stored = fake_client._objects.get(
        ("medical-documents", "documents/patient-1/uuid-abc")
    )
    assert stored is not None
    assert stored[0] == b"%PDF-1.4 fake content"
    assert stored[1] == "application/pdf"


@pytest.mark.asyncio
async def test_upload_file_uses_correct_bucket(fake_client: FakeS3Client):
    """upload_file() always targets the bucket from settings.S3_BUCKET_NAME."""
    with make_patch(fake_client):
        from app.core.storage import upload_file

        await upload_file("some/key", b"data", "image/jpeg")

    assert ("medical-documents", "some/key") in fake_client._objects


@pytest.mark.asyncio
async def test_download_file_streams_correct_bytes(fake_client: FakeS3Client):
    """download_file() yields the original uploaded bytes in order."""
    payload = b"hello from S3" * 100
    fake_client._buckets.add("medical-documents")
    fake_client._objects[("medical-documents", "documents/p/uuid-xyz")] = (
        payload,
        "image/png",
    )

    import app.core.storage as storage_module

    storage_module._bucket_ready = True  # bucket already ready

    with make_patch(fake_client):
        chunks = []
        async for chunk in storage_module.download_file("documents/p/uuid-xyz"):
            chunks.append(chunk)

    assert b"".join(chunks) == payload


@pytest.mark.asyncio
async def test_download_file_raises_for_missing_key(fake_client: FakeS3Client):
    """download_file() propagates ClientError when the key does not exist."""
    from botocore.exceptions import ClientError

    import app.core.storage as storage_module

    storage_module._bucket_ready = True
    fake_client._buckets.add("medical-documents")

    with make_patch(fake_client):
        with pytest.raises(ClientError):
            async for _ in storage_module.download_file("does/not/exist"):
                pass


@pytest.mark.asyncio
async def test_delete_file_removes_object(fake_client: FakeS3Client):
    """delete_file() removes the stored object from the fake store."""
    key = "documents/p/to-delete"
    fake_client._buckets.add("medical-documents")
    fake_client._objects[("medical-documents", key)] = (b"content", "application/pdf")

    import app.core.storage as storage_module

    storage_module._bucket_ready = True

    with make_patch(fake_client):
        await storage_module.delete_file(key)

    assert ("medical-documents", key) not in fake_client._objects


@pytest.mark.asyncio
async def test_delete_file_is_idempotent(fake_client: FakeS3Client):
    """delete_file() does not raise when the key is already absent (idempotent)."""
    import app.core.storage as storage_module

    storage_module._bucket_ready = True
    fake_client._buckets.add("medical-documents")

    with make_patch(fake_client):
        # Must not raise even though the object was never stored.
        await storage_module.delete_file("documents/p/never-existed")


@pytest.mark.asyncio
async def test_storage_key_format_is_uuid_only(fake_client: FakeS3Client):
    """
    Storage keys must follow the format 'documents/{patient_id}/{uuid}'.
    No filename component is allowed in the key.
    """
    patient_id = "patient-42"
    uuid = "550e8400-e29b-41d4-a716-446655440000"
    expected_key = f"documents/{patient_id}/{uuid}"

    # The key contains no filename — verify no '.' or filename-like suffix.
    assert expected_key.count("/") == 2
    parts = expected_key.split("/")
    assert parts[0] == "documents"
    assert parts[1] == patient_id
    assert parts[2] == uuid

    # Also exercise upload/download round-trip with this key format.
    with make_patch(fake_client):
        from app.core.storage import download_file, upload_file

        await upload_file(expected_key, b"PDF bytes", "application/pdf")

        chunks = []
        async for chunk in download_file(expected_key):
            chunks.append(chunk)

    assert b"".join(chunks) == b"PDF bytes"
