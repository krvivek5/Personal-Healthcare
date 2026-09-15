"""
M3 Slice 3 — Tests for document upload extraction lifecycle.

Architecture under test:
  POST /api/v1/documents
    → file validation (existing M2)
    → S3 upload (mocked)
    → MedicalDocument creation (real DB)
    → DispatchingExtractor invocation
    → DocumentExtraction persistence (real DB)
    → DocumentResponse returned with extraction_status

Coverage:
  Extraction lifecycle:
    - Valid native-text PDF → COMPLETED
    - Malformed PDF → FAILED
    - Image-only PDF (no text layer) → FAILED
    - JPEG upload → UNSUPPORTED (no extractor registered)
    - PNG upload → UNSUPPORTED
    - Extraction failure does NOT prevent 201 / document creation
    - DocumentExtraction linked to correct document_id
    - DocumentExtraction.patient_id == MedicalDocument.patient_id
    - No duplicate extraction rows on repeated persist_extraction calls
    - extraction_status exposed in DocumentResponse
    - storage_key absent from all responses

  Backward compatibility:
    - All pre-Slice-3 response fields present unchanged
    - GET/LIST endpoints unaffected
    - DB insert failure before extraction → no orphaned extraction row

Infrastructure:
  - S3 always mocked.
  - Real PostgreSQL via async_client fixture.
  - Separate DB session opened via async_session_factory for verification.
  - Synthetic PDF bytes only — no real patient data.
"""

from __future__ import annotations

import io
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.base import async_session_factory
from app.db.models import DocumentExtraction, MedicalDocument
from app.health.extraction import ExtractionResult
from tests.test_auth import create_test_token

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Synthetic document bytes
# ---------------------------------------------------------------------------

_PDF_MAGIC = b"%PDF-1.4 "
_JPEG_MAGIC = b"\xff\xd8\xff\xe0" + b"\x00" * 20
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20


def _minimal_native_pdf(text: str = "Creatinine 0.9 mg/dL") -> bytes:
    """Smallest structurally-valid PDF that pypdf can extract text from."""
    content_stream = (f"BT\n/F1 12 Tf\n72 720 Td\n({text}) Tj\nET\n").encode("latin-1")
    stream_len = len(content_stream)

    body = (
        "%PDF-1.4\n"
        "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n\n"
        "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n\n"
        "3 0 obj\n"
        "<< /Type /Page /Parent 2 0 R "
        "/MediaBox [0 0 612 792] "
        "/Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>\n"
        "endobj\n\n"
        f"4 0 obj\n<< /Length {stream_len} >>\nstream\n"
    ).encode("latin-1")

    body += content_stream
    body += b"\nendstream\nendobj\n\n"
    body += (
        "5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
    ).encode("latin-1")

    xref_pos = len(body)
    body += (
        "xref\n0 6\n"
        "0000000000 65535 f \n"
        "0000000009 00000 n \n"
        "0000000058 00000 n \n"
        "0000000115 00000 n \n"
        "0000000266 00000 n \n"
        f"{'0000000000':0>10} 00000 n \n"
        "trailer\n<< /Size 6 /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode("latin-1")
    return body


def _malformed_pdf_bytes() -> bytes:
    return _PDF_MAGIC + b"not a valid pdf body\xff\xfe"


def _image_only_pdf_bytes() -> bytes:
    """Minimal PDF with empty content stream — no extractable text."""
    body = (
        "%PDF-1.4\n"
        "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n\n"
        "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n\n"
        "3 0 obj\n"
        "<< /Type /Page /Parent 2 0 R "
        "/MediaBox [0 0 612 792] "
        "/Contents 4 0 R /Resources << >> >>\n"
        "endobj\n\n"
        "4 0 obj\n<< /Length 0 >>\nstream\n"
    ).encode("latin-1")
    body += b"\nendstream\nendobj\n\n"
    xref_pos = len(body)
    body += (
        "xref\n0 5\n"
        "0000000000 65535 f \n"
        "0000000009 00000 n \n"
        "0000000058 00000 n \n"
        "0000000115 00000 n \n"
        "0000000230 00000 n \n"
        f"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"
    ).encode("latin-1")
    return body


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _make_upload(
    content: bytes,
    filename: str = "report.pdf",
    content_type: str = "application/pdf",
) -> dict:
    return {"file": (filename, io.BytesIO(content), content_type)}


def _patched_s3():
    async def _fake_upload(key, data, ct):
        return None

    async def _fake_delete(key):
        return None

    async def _fake_download(key):
        yield b"fake"

    return (
        patch("app.api.documents.storage.upload_file", side_effect=_fake_upload),
        patch("app.api.documents.storage.delete_file", side_effect=_fake_delete),
        patch(
            "app.api.documents.storage.download_file",
            side_effect=_fake_download,
        ),
    )


async def _upload(
    async_client: AsyncClient,
    token: str,
    content: bytes,
    filename: str = "report.pdf",
    content_type: str = "application/pdf",
    document_type: str = "lab_report",
):
    up_p, del_p, dl_p = _patched_s3()
    with up_p, del_p, dl_p:
        return await async_client.post(
            "/api/v1/documents",
            headers=_headers(token),
            files=_make_upload(content, filename, content_type),
            data={"document_type": document_type},
        )


async def _fetch_extraction(doc_id: uuid.UUID) -> DocumentExtraction | None:
    """Open a fresh read session to check the extraction row."""
    async with async_session_factory() as session:
        stmt = select(DocumentExtraction).where(
            DocumentExtraction.document_id == doc_id
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def _fetch_doc(doc_id: uuid.UUID) -> MedicalDocument | None:
    async with async_session_factory() as session:
        stmt = select(MedicalDocument).where(MedicalDocument.id == doc_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Extraction lifecycle tests
# ---------------------------------------------------------------------------


async def test_native_pdf_upload_completed_extraction(
    async_client: AsyncClient,
):
    """Valid native-text PDF → upload 201 + extraction_status=COMPLETED."""
    token = create_test_token(user_id=str(uuid.uuid4()))
    pdf_bytes = _minimal_native_pdf("HbA1c: 5.6%")

    response = await _upload(async_client, token, pdf_bytes)
    assert response.status_code == 201, response.text
    assert response.json()["extraction_status"] == "COMPLETED"


async def test_malformed_pdf_upload_failed_extraction(
    async_client: AsyncClient,
):
    """Malformed PDF → upload 201 + extraction_status=FAILED."""
    token = create_test_token(user_id=str(uuid.uuid4()))
    response = await _upload(async_client, token, _malformed_pdf_bytes())
    assert response.status_code == 201, response.text
    assert response.json()["extraction_status"] == "FAILED"


async def test_image_only_pdf_unsupported_extraction(async_client: AsyncClient):
    """PDF with no text layer → upload 201 + extraction_status=UNSUPPORTED."""
    token = create_test_token(user_id=str(uuid.uuid4()))
    response = await _upload(async_client, token, _image_only_pdf_bytes())
    assert response.status_code == 201, response.text
    assert response.json()["extraction_status"] == "UNSUPPORTED"


async def test_jpeg_upload_unsupported_extraction(async_client: AsyncClient):
    """JPEG → upload 201 + extraction_status=UNSUPPORTED."""
    token = create_test_token(user_id=str(uuid.uuid4()))
    response = await _upload(
        async_client,
        token,
        _JPEG_MAGIC + b"data",
        filename="scan.jpg",
        content_type="image/jpeg",
        document_type="medical_record",
    )
    assert response.status_code == 201, response.text
    assert response.json()["extraction_status"] == "UNSUPPORTED"


async def test_png_upload_unsupported_extraction(async_client: AsyncClient):
    """PNG → upload 201 + extraction_status=UNSUPPORTED."""
    token = create_test_token(user_id=str(uuid.uuid4()))
    response = await _upload(
        async_client,
        token,
        _PNG_MAGIC + b"data",
        filename="image.png",
        content_type="image/png",
        document_type="other",
    )
    assert response.status_code == 201, response.text
    assert response.json()["extraction_status"] == "UNSUPPORTED"


async def test_document_persists_when_extractor_returns_failed(
    async_client: AsyncClient,
):
    """MedicalDocument row persists even when extraction returns FAILED."""
    token = create_test_token(user_id=str(uuid.uuid4()))
    failed_result = ExtractionResult.failed(
        method="pypdf", version="pypdf/0.0", error="simulated failure"
    )

    up_p, del_p, dl_p = _patched_s3()
    with up_p, del_p, dl_p:
        with patch(
            "app.api.documents._extractor.extract_text",
            new_callable=AsyncMock,
            return_value=failed_result,
        ):
            response = await async_client.post(
                "/api/v1/documents",
                headers=_headers(token),
                files=_make_upload(_PDF_MAGIC + b" body"),
                data={"document_type": "lab_report"},
            )

    assert response.status_code == 201, response.text
    doc_id = uuid.UUID(response.json()["id"])
    doc = await _fetch_doc(doc_id)
    assert doc is not None


async def test_extraction_row_linked_to_correct_document(
    async_client: AsyncClient,
):
    """DocumentExtraction.document_id == uploaded MedicalDocument.id."""
    token = create_test_token(user_id=str(uuid.uuid4()))
    pdf_bytes = _minimal_native_pdf("Cholesterol: 180 mg/dL")

    response = await _upload(async_client, token, pdf_bytes)
    assert response.status_code == 201, response.text
    doc_id = uuid.UUID(response.json()["id"])

    extraction = await _fetch_extraction(doc_id)
    assert extraction is not None
    assert extraction.document_id == doc_id


async def test_extraction_inherits_patient_id_from_document(
    async_client: AsyncClient,
):
    """Tenant integrity: extraction.patient_id == document.patient_id."""
    token = create_test_token(user_id=str(uuid.uuid4()))
    pdf_bytes = _minimal_native_pdf("TSH: 2.4 mIU/L")

    response = await _upload(async_client, token, pdf_bytes)
    assert response.status_code == 201, response.text
    doc_id = uuid.UUID(response.json()["id"])

    doc = await _fetch_doc(doc_id)
    extraction = await _fetch_extraction(doc_id)

    assert doc is not None
    assert extraction is not None
    assert extraction.patient_id == doc.patient_id


async def test_no_duplicate_extraction_rows(async_client: AsyncClient):
    """persist_extraction called twice for same document → only one row."""
    from app.health.documents import persist_extraction

    token = create_test_token(user_id=str(uuid.uuid4()))
    pdf_bytes = _minimal_native_pdf("Glucose: 95 mg/dL")

    response = await _upload(async_client, token, pdf_bytes)
    assert response.status_code == 201, response.text
    doc_id = uuid.UUID(response.json()["id"])

    # Call persist_extraction a second time via service (not the API).
    result2 = ExtractionResult.failed(
        method="pypdf", version="pypdf/test", error="re-run"
    )
    async with async_session_factory() as session:
        doc_stmt = select(MedicalDocument).where(MedicalDocument.id == doc_id)
        doc = (await session.execute(doc_stmt)).scalar_one()
        await persist_extraction(session, doc, result2)

        # Verify still only one row.
        count_stmt = select(DocumentExtraction).where(
            DocumentExtraction.document_id == doc_id
        )
        rows = (await session.execute(count_stmt)).scalars().all()

    assert len(rows) == 1
    assert rows[0].extraction_status == "FAILED"


async def test_extraction_status_in_response(async_client: AsyncClient):
    """extraction_status field appears in the DocumentResponse JSON."""
    token = create_test_token(user_id=str(uuid.uuid4()))
    pdf_bytes = _minimal_native_pdf("BUN: 14 mg/dL")

    response = await _upload(async_client, token, pdf_bytes)
    assert response.status_code == 201, response.text
    data = response.json()

    assert "extraction_status" in data
    assert data["extraction_status"] in {"COMPLETED", "FAILED", "UNSUPPORTED"}


async def test_storage_key_absent_in_response(async_client: AsyncClient):
    """storage_key must not appear in response after Slice 3."""
    token = create_test_token(user_id=str(uuid.uuid4()))
    pdf_bytes = _minimal_native_pdf("CBC normal")

    response = await _upload(async_client, token, pdf_bytes)
    assert response.status_code == 201, response.text
    assert "storage_key" not in response.json()
    assert "storage_key" not in response.text


# ---------------------------------------------------------------------------
# Backward compatibility tests
# ---------------------------------------------------------------------------


async def test_existing_response_fields_present(async_client: AsyncClient):
    """All pre-Slice-3 DocumentResponse fields still present."""
    token = create_test_token(user_id=str(uuid.uuid4()))
    pdf_bytes = _minimal_native_pdf("Sodium: 140 mEq/L")

    response = await _upload(async_client, token, pdf_bytes)
    assert response.status_code == 201, response.text
    data = response.json()

    required = {
        "id",
        "patient_id",
        "file_name",
        "display_name",
        "document_type",
        "content_type",
        "file_size_bytes",
        "source_type",
        "verification_state",
        "uploaded_at",
        "created_at",
        "updated_at",
    }
    for field in required:
        assert field in data, f"Missing field: {field}"
    assert data["source_type"] == "PATIENT_REPORTED"


async def test_get_document_endpoint_unchanged(async_client: AsyncClient):
    """GET /documents/{id} still works after Slice 3."""
    token = create_test_token(user_id=str(uuid.uuid4()))
    pdf_bytes = _minimal_native_pdf("Potassium: 4.2 mEq/L")

    response = await _upload(async_client, token, pdf_bytes)
    assert response.status_code == 201, response.text
    doc_id = response.json()["id"]

    up_p, del_p, dl_p = _patched_s3()
    with up_p, del_p, dl_p:
        get_resp = await async_client.get(
            f"/api/v1/documents/{doc_id}", headers=_headers(token)
        )
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == doc_id


async def test_list_documents_endpoint_unchanged(async_client: AsyncClient):
    """GET /documents contains uploaded doc after Slice 3."""
    token = create_test_token(user_id=str(uuid.uuid4()))
    pdf_bytes = _minimal_native_pdf("Albumin: 4.1 g/dL")

    response = await _upload(async_client, token, pdf_bytes)
    assert response.status_code == 201, response.text
    doc_id = response.json()["id"]

    up_p, del_p, dl_p = _patched_s3()
    with up_p, del_p, dl_p:
        list_resp = await async_client.get("/api/v1/documents", headers=_headers(token))
    assert list_resp.status_code == 200
    ids = [d["id"] for d in list_resp.json()]
    assert doc_id in ids


async def test_db_insert_failure_before_extraction_no_orphan_extraction(
    async_client: AsyncClient,
):
    """DB insert failure → 500, no extraction row created for missing document."""
    token = create_test_token(user_id=str(uuid.uuid4()))
    pdf_bytes = _minimal_native_pdf("WBC: 7.2 K/uL")

    async def fake_upload(key, data, ct):
        return None

    async def fake_delete(key):
        return None

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
            files=_make_upload(pdf_bytes),
            data={"document_type": "lab_report"},
        )

    assert resp.status_code == 500

    # Extraction logic was never reached: no orphaned rows.
    # Since no MedicalDocument was created, any extraction must reference one.
    async with async_session_factory() as session:
        ext_stmt = select(DocumentExtraction)
        all_extractions = (await session.execute(ext_stmt)).scalars().all()

        for ext in all_extractions:
            doc_stmt = select(MedicalDocument).where(
                MedicalDocument.id == ext.document_id
            )
            doc = (await session.execute(doc_stmt)).scalar_one_or_none()
            assert doc is not None, (
                f"Orphaned extraction row found: document_id={ext.document_id}"
            )
