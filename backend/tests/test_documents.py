"""
M4 backend tests: documents API and service.

All S3 interactions are mocked via patch — no MinIO instance required.
Database operations use the real (dockerized) PostgreSQL via the async_client
fixture (same as existing tests).

Covers:
  Happy path:
    - Upload PDF → 201, DocumentResponse returned
    - GET /documents → list includes uploaded doc
    - GET /documents/{id} → 200 with owner
    - GET /documents/{id}/download → streams correct bytes
    - PATCH /documents/{id} → updated metadata
    - DELETE /documents/{id} → 204

  Security & isolation:
    - storage_key absent from all API responses
    - GET/PATCH/DELETE with non-owner token → 403
    - MIME/magic mismatch → 422

  Bounded read & limit:
    - Oversized file → 413
    - Disallowed MIME → 422

  Content-Disposition safety:
    - Filename with CR/LF/injection characters is sanitised

  Storage/DB consistency:
    - Upload: S3 succeeds, DB insert fails → compensating S3 delete, 500
    - Delete: S3 delete fails → DB row preserved, 500
    - Delete: DB delete fails after S3 delete → 500
"""

from __future__ import annotations

import io
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from tests.test_auth import create_test_token

# Magic bytes for testing
_PDF_MAGIC = b"%PDF-1.4 "
_JPEG_MAGIC = b"\xff\xd8\xff\xe0" + b"\x00" * 20

pytestmark = pytest.mark.asyncio

# ── Helpers ────────────────────────────────────────────────────────────────────


def _pdf_bytes(extra: bytes = b" fake body") -> bytes:
    return _PDF_MAGIC + extra


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _make_upload(
    content: bytes = _pdf_bytes(),
    filename: str = "report.pdf",
    content_type: str = "application/pdf",
) -> dict:
    """Build the files dict for httpx multipart upload."""
    return {"file": (filename, io.BytesIO(content), content_type)}


def _patched_s3(
    upload_side_effect=None,
    download_chunks: list[bytes] | None = None,
    delete_side_effect=None,
):
    """Context manager patches for storage functions."""
    async def _fake_upload(key, data, ct):
        if upload_side_effect:
            raise upload_side_effect
        return None

    async def _fake_delete(key):
        if delete_side_effect:
            raise delete_side_effect
        return None

    async def _fake_download(key):
        for chunk in (download_chunks or [b"fake pdf bytes"]):
            yield chunk

    return (
        patch("app.api.documents.storage.upload_file", side_effect=_fake_upload),
        patch("app.api.documents.storage.delete_file", side_effect=_fake_delete),
        patch("app.api.documents.storage.download_file", side_effect=_fake_download),
    )


# ── Happy-path tests ────────────────────────────────────────────────────────────


async def test_upload_pdf_returns_201(async_client: AsyncClient):
    """Upload a valid PDF → 201 and DocumentResponse."""
    token = create_test_token(user_id=str(uuid.uuid4()))

    up_patch, del_patch, dl_patch = _patched_s3()
    with up_patch, del_patch, dl_patch:
        response = await async_client.post(
            "/api/v1/documents",
            headers=_headers(token),
            files=_make_upload(),
            data={"document_type": "lab_report", "display_name": "Blood Test"},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["id"] is not None
    assert data["document_type"] == "lab_report"
    assert data["display_name"] == "Blood Test"
    assert data["content_type"] == "application/pdf"
    assert data["source_type"] == "PATIENT_REPORTED"


async def test_storage_key_absent_from_response(async_client: AsyncClient):
    """storage_key must never appear in any DocumentResponse."""
    token = create_test_token(user_id=str(uuid.uuid4()))

    up_patch, del_patch, dl_patch = _patched_s3()
    with up_patch, del_patch, dl_patch:
        response = await async_client.post(
            "/api/v1/documents",
            headers=_headers(token),
            files=_make_upload(),
            data={"document_type": "other"},
        )

    assert response.status_code == 201
    body = response.json()
    assert "storage_key" not in body
    # Also verify the raw JSON string doesn't contain it
    assert "storage_key" not in response.text


async def test_list_documents_includes_uploaded(async_client: AsyncClient):
    """GET /documents returns the document we just uploaded."""
    token = create_test_token(user_id=str(uuid.uuid4()))

    up_patch, del_patch, dl_patch = _patched_s3()
    with up_patch, del_patch, dl_patch:
        upload_resp = await async_client.post(
            "/api/v1/documents",
            headers=_headers(token),
            files=_make_upload(),
            data={"document_type": "prescription"},
        )
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["id"]

    with up_patch, del_patch, dl_patch:
        list_resp = await async_client.get("/api/v1/documents", headers=_headers(token))
    assert list_resp.status_code == 200
    ids = [d["id"] for d in list_resp.json()]
    assert doc_id in ids
    # Confirm storage_key absent from list items
    for item in list_resp.json():
        assert "storage_key" not in item


async def test_get_document_by_owner(async_client: AsyncClient):
    """GET /documents/{id} with owner token → 200."""
    token = create_test_token(user_id=str(uuid.uuid4()))

    up_patch, del_patch, dl_patch = _patched_s3()
    with up_patch, del_patch, dl_patch:
        upload_resp = await async_client.post(
            "/api/v1/documents",
            headers=_headers(token),
            files=_make_upload(),
            data={"document_type": "medical_record"},
        )
    doc_id = upload_resp.json()["id"]

    with up_patch, del_patch, dl_patch:
        get_resp = await async_client.get(
            f"/api/v1/documents/{doc_id}", headers=_headers(token)
        )
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == doc_id
    assert "storage_key" not in get_resp.json()


async def test_download_streams_correct_bytes(async_client: AsyncClient):
    """GET /documents/{id}/download streams the file bytes."""
    token = create_test_token(user_id=str(uuid.uuid4()))

    content = _pdf_bytes(b" authentic content")
    up_patch, del_patch, dl_patch = _patched_s3(download_chunks=[content])
    with up_patch, del_patch, dl_patch:
        upload_resp = await async_client.post(
            "/api/v1/documents",
            headers=_headers(token),
            files=_make_upload(content=content),
            data={"document_type": "lab_report"},
        )
    doc_id = upload_resp.json()["id"]

    with up_patch, del_patch, dl_patch:
        dl_resp = await async_client.get(
            f"/api/v1/documents/{doc_id}/download", headers=_headers(token)
        )
    assert dl_resp.status_code == 200
    assert dl_resp.content == content
    assert "Content-Disposition" in dl_resp.headers


async def test_patch_document_updates_metadata(async_client: AsyncClient):
    """PATCH /documents/{id} → updated display_name reflected in response."""
    token = create_test_token(user_id=str(uuid.uuid4()))

    up_patch, del_patch, dl_patch = _patched_s3()
    with up_patch, del_patch, dl_patch:
        upload_resp = await async_client.post(
            "/api/v1/documents",
            headers=_headers(token),
            files=_make_upload(),
            data={"document_type": "diagnostic_report", "display_name": "Old Name"},
        )
    doc_id = upload_resp.json()["id"]

    with up_patch, del_patch, dl_patch:
        patch_resp = await async_client.patch(
            f"/api/v1/documents/{doc_id}",
            headers=_headers(token),
            json={"display_name": "New Name", "notes": "Updated"},
        )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["display_name"] == "New Name"
    assert patch_resp.json()["notes"] == "Updated"


async def test_delete_document_returns_204(async_client: AsyncClient):
    """DELETE /documents/{id} → 204 on success."""
    token = create_test_token(user_id=str(uuid.uuid4()))

    up_patch, del_patch, dl_patch = _patched_s3()
    with up_patch, del_patch, dl_patch:
        upload_resp = await async_client.post(
            "/api/v1/documents",
            headers=_headers(token),
            files=_make_upload(),
            data={"document_type": "other"},
        )
    doc_id = upload_resp.json()["id"]

    with up_patch, del_patch, dl_patch:
        del_resp = await async_client.delete(
            f"/api/v1/documents/{doc_id}", headers=_headers(token)
        )
    assert del_resp.status_code == 204

    # Confirm it no longer appears in list
    with up_patch, del_patch, dl_patch:
        list_resp = await async_client.get("/api/v1/documents", headers=_headers(token))
    ids = [d["id"] for d in list_resp.json()]
    assert doc_id not in ids


# ── Security & isolation tests ────────────────────────────────────────────────


async def test_get_document_non_owner_returns_403(async_client: AsyncClient):
    """GET /documents/{id} with non-owner token → 403."""
    owner_token = create_test_token(user_id=str(uuid.uuid4()))
    other_token = create_test_token(user_id=str(uuid.uuid4()))

    up_patch, del_patch, dl_patch = _patched_s3()
    with up_patch, del_patch, dl_patch:
        upload_resp = await async_client.post(
            "/api/v1/documents",
            headers=_headers(owner_token),
            files=_make_upload(),
            data={"document_type": "other"},
        )
    doc_id = upload_resp.json()["id"]

    with up_patch, del_patch, dl_patch:
        get_resp = await async_client.get(
            f"/api/v1/documents/{doc_id}", headers=_headers(other_token)
        )
    assert get_resp.status_code == 403
    assert get_resp.json()["detail"] == "Not authorized to access this resource"


async def test_patch_non_owner_returns_403(async_client: AsyncClient):
    """PATCH /documents/{id} by non-owner → 403."""
    owner_token = create_test_token(user_id=str(uuid.uuid4()))
    other_token = create_test_token(user_id=str(uuid.uuid4()))

    up_patch, del_patch, dl_patch = _patched_s3()
    with up_patch, del_patch, dl_patch:
        upload_resp = await async_client.post(
            "/api/v1/documents",
            headers=_headers(owner_token),
            files=_make_upload(),
            data={"document_type": "other"},
        )
    doc_id = upload_resp.json()["id"]

    with up_patch, del_patch, dl_patch:
        patch_resp = await async_client.patch(
            f"/api/v1/documents/{doc_id}",
            headers=_headers(other_token),
            json={"display_name": "Hacked"},
        )
    assert patch_resp.status_code == 403


async def test_delete_non_owner_returns_403(async_client: AsyncClient):
    """DELETE /documents/{id} by non-owner → 403."""
    owner_token = create_test_token(user_id=str(uuid.uuid4()))
    other_token = create_test_token(user_id=str(uuid.uuid4()))

    up_patch, del_patch, dl_patch = _patched_s3()
    with up_patch, del_patch, dl_patch:
        upload_resp = await async_client.post(
            "/api/v1/documents",
            headers=_headers(owner_token),
            files=_make_upload(),
            data={"document_type": "other"},
        )
    doc_id = upload_resp.json()["id"]

    with up_patch, del_patch, dl_patch:
        del_resp = await async_client.delete(
            f"/api/v1/documents/{doc_id}", headers=_headers(other_token)
        )
    assert del_resp.status_code == 403


async def test_mime_magic_mismatch_returns_422(async_client: AsyncClient):
    """Upload with MIME/magic mismatch → 422 before any S3 interaction."""
    token = create_test_token(user_id=str(uuid.uuid4()))

    # Claim application/pdf but provide JPEG bytes
    up_patch, del_patch, dl_patch = _patched_s3()
    with up_patch, del_patch, dl_patch:
        resp = await async_client.post(
            "/api/v1/documents",
            headers=_headers(token),
            files=_make_upload(content=_JPEG_MAGIC + b"data", content_type="application/pdf"),
            data={"document_type": "lab_report"},
        )
    assert resp.status_code == 422
    assert "magic bytes" in resp.json()["detail"].lower()


# ── Bounded read & limit tests ────────────────────────────────────────────────


async def test_upload_oversized_file_returns_413(async_client: AsyncClient):
    """Upload file > 20 MiB → 413."""
    from app.core.file_validation import MAX_FILE_SIZE_BYTES

    token = create_test_token(user_id=str(uuid.uuid4()))
    oversized = _PDF_MAGIC + b"x" * (MAX_FILE_SIZE_BYTES + 1)

    up_patch, del_patch, dl_patch = _patched_s3()
    with up_patch, del_patch, dl_patch:
        resp = await async_client.post(
            "/api/v1/documents",
            headers=_headers(token),
            files=_make_upload(content=oversized),
            data={"document_type": "other"},
        )
    assert resp.status_code == 413


async def test_upload_disallowed_mime_returns_422(async_client: AsyncClient):
    """Upload with text/plain MIME → 422."""
    token = create_test_token(user_id=str(uuid.uuid4()))

    up_patch, del_patch, dl_patch = _patched_s3()
    with up_patch, del_patch, dl_patch:
        resp = await async_client.post(
            "/api/v1/documents",
            headers=_headers(token),
            files=_make_upload(content=b"plain text", content_type="text/plain"),
            data={"document_type": "other"},
        )
    assert resp.status_code == 422


# ── Content-Disposition safety ─────────────────────────────────────────────────


async def test_download_unsafe_filename_sanitised(async_client: AsyncClient):
    """Filename with CR/LF/injection characters does not corrupt Content-Disposition."""
    token = create_test_token(user_id=str(uuid.uuid4()))
    # A filename with CR+LF (classic header injection attempt)
    evil_filename = "report\r\nX-Injected: evil\r\n"

    up_patch, del_patch, dl_patch = _patched_s3()
    with up_patch, del_patch, dl_patch:
        upload_resp = await async_client.post(
            "/api/v1/documents",
            headers=_headers(token),
            files=_make_upload(filename=evil_filename),
            data={"document_type": "other"},
        )
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["id"]

    with up_patch, del_patch, dl_patch:
        dl_resp = await async_client.get(
            f"/api/v1/documents/{doc_id}/download", headers=_headers(token)
        )
    assert dl_resp.status_code == 200
    cd = dl_resp.headers.get("content-disposition", "")
    # Ensure CR or LF are absent from the header value
    assert "\r" not in cd
    assert "\n" not in cd


# ── Storage / DB consistency tests ────────────────────────────────────────────


async def test_upload_db_failure_triggers_s3_compensating_delete(
    async_client: AsyncClient,
):
    """
    Upload: S3 upload succeeds, DB insert fails →
    compensating S3 delete is attempted and 500 is returned.
    """
    token = create_test_token(user_id=str(uuid.uuid4()))

    deleted_keys: list[str] = []

    async def fake_upload(key, data, ct):
        pass

    async def fake_delete(key):
        deleted_keys.append(key)

    with (
        patch("app.api.documents.storage.upload_file", side_effect=fake_upload),
        patch("app.api.documents.storage.delete_file", side_effect=fake_delete),
        patch(
            "app.api.documents.create_document",
            side_effect=Exception("DB exploded"),
        ),
    ):
        resp = await async_client.post(
            "/api/v1/documents",
            headers=_headers(token),
            files=_make_upload(),
            data={"document_type": "other"},
        )

    assert resp.status_code == 500
    # Compensating delete must have been called
    assert len(deleted_keys) == 1


async def test_delete_s3_failure_preserves_db_row(async_client: AsyncClient):
    """
    Delete: S3 delete fails → DB row preserved, 500 returned.
    Verify the document still exists after the failed delete.
    """
    from botocore.exceptions import ClientError

    token = create_test_token(user_id=str(uuid.uuid4()))

    up_patch, del_patch, dl_patch = _patched_s3()
    with up_patch, del_patch, dl_patch:
        upload_resp = await async_client.post(
            "/api/v1/documents",
            headers=_headers(token),
            files=_make_upload(),
            data={"document_type": "other"},
        )
    doc_id = upload_resp.json()["id"]

    # Now simulate S3 delete failure
    s3_error = ClientError(
        {"Error": {"Code": "InternalError", "Message": "S3 down"}}, "DeleteObject"
    )

    async def failing_delete(key):
        raise s3_error

    with (
        patch("app.api.documents.storage.delete_file", side_effect=failing_delete),
    ):
        del_resp = await async_client.delete(
            f"/api/v1/documents/{doc_id}", headers=_headers(token)
        )
    assert del_resp.status_code == 500

    # DB row must still be accessible
    with up_patch, del_patch, dl_patch:
        get_resp = await async_client.get(
            f"/api/v1/documents/{doc_id}", headers=_headers(token)
        )
    assert get_resp.status_code == 200


async def test_delete_db_failure_after_s3_success_returns_500(
    async_client: AsyncClient,
):
    """
    Delete: S3 delete succeeds, DB delete fails → 500.
    No silent success reported.
    """
    token = create_test_token(user_id=str(uuid.uuid4()))

    up_patch, del_patch, dl_patch = _patched_s3()
    with up_patch, del_patch, dl_patch:
        upload_resp = await async_client.post(
            "/api/v1/documents",
            headers=_headers(token),
            files=_make_upload(),
            data={"document_type": "other"},
        )
    doc_id = upload_resp.json()["id"]

    async def fake_s3_delete(key):
        pass

    with (
        patch("app.api.documents.storage.delete_file", side_effect=fake_s3_delete),
        patch(
            "app.api.documents.delete_document",
            side_effect=Exception("DB delete exploded"),
        ),
    ):
        del_resp = await async_client.delete(
            f"/api/v1/documents/{doc_id}", headers=_headers(token)
        )
    assert del_resp.status_code == 500
    # Response should mention failure, not be a 204
    assert del_resp.status_code != 204


# ── Unauthenticated access ─────────────────────────────────────────────────────


async def test_unauthenticated_upload_rejected(async_client: AsyncClient):
    resp = await async_client.post(
        "/api/v1/documents",
        files=_make_upload(),
        data={"document_type": "other"},
    )
    assert resp.status_code == 401


async def test_unauthenticated_list_rejected(async_client: AsyncClient):
    resp = await async_client.get("/api/v1/documents")
    assert resp.status_code == 401


async def test_nonexistent_document_returns_404(async_client: AsyncClient):
    """GET /documents/{id} for non-existent ID → 404."""
    token = create_test_token(user_id=str(uuid.uuid4()))
    up_patch, del_patch, dl_patch = _patched_s3()
    with up_patch, del_patch, dl_patch:
        resp = await async_client.get(
            f"/api/v1/documents/{uuid.uuid4()}",
            headers=_headers(token),
        )
    assert resp.status_code == 404
