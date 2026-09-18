"""Integration tests for Document Chunking Pipeline (Milestone 4 Slice 2).

Covers:
- Database persistence of DocumentChunk rows
- Composite FK (document_id, patient_id) adherence
- Savepoint rollback isolation: proves pre-existing chunks survive replacement failures
- Stale chunk replacement and idempotency
- Extraction status gating: FAILED/UNSUPPORTED/empty text produces zero chunks
- Cascade deletion from MedicalDocument to DocumentChunk
- Cross-patient tenant isolation
- Full upload API integration with multi-page PDF
- Non-fatal upload behavior when chunking fails
"""

from __future__ import annotations

import io
import uuid
from datetime import date
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from pypdf import PdfReader, PdfWriter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import async_session_factory, engine
from app.db.models import DocumentChunk, DocumentExtraction, MedicalDocument, Patient
from app.health.chunking import (
    PAGE_DELIMITER,
    ChunkDraft,
    DocumentChunker,
    chunk_and_persist_document,
)
from app.health.documents import persist_extraction
from app.health.extraction import ExtractionResult
from tests.test_auth import create_test_token

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def dispose_engine_after_test():
    yield
    await engine.dispose()


# ---------------------------------------------------------------------------
# Synthetic PDF helpers
# ---------------------------------------------------------------------------


def _minimal_pdf_bytes(text: str = "Creatinine 0.9 mg/dL") -> bytes:
    """Small single-page valid PDF with embedded text stream."""
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


def _multipage_pdf_bytes(page_texts: list[str]) -> bytes:
    """Build a multi-page PDF by combining single-page streams using PdfWriter."""
    writer = PdfWriter()
    for t in page_texts:
        page_bytes = _minimal_pdf_bytes(t)
        reader = PdfReader(io.BytesIO(page_bytes))
        writer.add_page(reader.pages[0])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Database seed helper
# ---------------------------------------------------------------------------


async def _create_patient_and_document(
    session: AsyncSession,
) -> tuple[Patient, MedicalDocument]:
    patient = Patient(user_id=uuid.uuid4())
    session.add(patient)
    await session.flush()

    doc = MedicalDocument(
        patient_id=patient.id,
        storage_key=f"raw/{patient.id}/{uuid.uuid4()}.pdf",
        file_name="lab_report.pdf",
        display_name="Comprehensive Metabolic Panel",
        document_type="lab_report",
        content_type="application/pdf",
        file_size_bytes=1024,
        source_type="PATIENT_REPORTED",
        document_date=date(2025, 10, 14),
    )
    session.add(doc)
    await session.flush()
    return patient, doc


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


async def test_chunk_and_persist_lifecycle():
    """Verify end-to-end chunk persistence with column mappings and composite FK."""
    async with async_session_factory() as session:
        _, doc = await _create_patient_and_document(session)

        # Create COMPLETED extraction
        page1_text = "Sodium: 140 mEq/L. Potassium: 4.2 mEq/L."
        page2_text = "Chloride: 102 mEq/L. Bicarbonate: 24 mEq/L."
        extracted_text = page1_text + PAGE_DELIMITER + page2_text

        result = ExtractionResult.completed(
            text=extracted_text,
            method="pypdf",
            version="pypdf/6.0.0",
        )
        extraction = await persist_extraction(session, doc, result)

        chunks = await chunk_and_persist_document(session, doc, extraction)
        await session.commit()

        assert len(chunks) == 2

        # Verify DB rows
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == doc.id)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        res = await session.execute(stmt)
        db_chunks = list(res.scalars().all())

        assert len(db_chunks) == 2
        assert db_chunks[0].patient_id == doc.patient_id
        assert db_chunks[0].chunk_index == 0
        assert db_chunks[0].page_number == 1
        assert db_chunks[0].chunk_text == page1_text
        assert db_chunks[0].embedding is None

        assert db_chunks[1].patient_id == doc.patient_id
        assert db_chunks[1].chunk_index == 1
        assert db_chunks[1].page_number == 2
        assert db_chunks[1].chunk_text == page2_text
        assert db_chunks[1].embedding is None


async def test_savepoint_rollback_preserves_preexisting_chunks():
    """Prove savepoint rollback leaves pre-existing chunks intact on failure."""
    async with async_session_factory() as session:
        _, doc = await _create_patient_and_document(session)

        # Step 1: Persist initial 2 valid chunks
        initial_text = "Initial Page 1" + PAGE_DELIMITER + "Initial Page 2"
        ext1 = await persist_extraction(
            session,
            doc,
            ExtractionResult.completed(
                text=initial_text, method="pypdf", version="pypdf/6.0.0"
            ),
        )
        initial_chunks = await chunk_and_persist_document(session, doc, ext1)
        await session.commit()
        assert len(initial_chunks) == 2

        # Step 2: Attempt replacement with a mock chunker that produces an
        # illegal empty chunk (triggers ck_document_chunks_non_empty_text)
        class FailingChunker(DocumentChunker):
            def chunk_document_text(
                self, text: str, default_page_number: int | None = None
            ) -> list[ChunkDraft]:
                # Returns an illegal empty text draft
                return [ChunkDraft(chunk_index=0, chunk_text="", page_number=1)]

        new_ext = await persist_extraction(
            session,
            doc,
            ExtractionResult.completed(
                text="Some new valid text", method="pypdf", version="pypdf/6.0.0"
            ),
        )

        with pytest.raises(IntegrityError):
            await chunk_and_persist_document(
                session, doc, new_ext, chunker=FailingChunker()
            )

        # Step 3: Verify savepoint rolled back and pre-existing chunks are preserved!
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == doc.id)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        res = await session.execute(stmt)
        remaining_chunks = list(res.scalars().all())

        assert len(remaining_chunks) == 2
        assert remaining_chunks[0].chunk_text == "Initial Page 1"
        assert remaining_chunks[1].chunk_text == "Initial Page 2"


async def test_stale_chunk_replacement_idempotency():
    """Verify re-chunking cleanly replaces old rows without constraint conflicts."""
    async with async_session_factory() as session:
        _, doc = await _create_patient_and_document(session)

        # Initial chunking: 1 chunk
        ext1 = await persist_extraction(
            session,
            doc,
            ExtractionResult.completed(
                text="Initial report line",
                method="text/plain",
                version="text-plain/1.0",
            ),
        )
        chunks1 = await chunk_and_persist_document(session, doc, ext1)
        await session.commit()
        assert len(chunks1) == 1

        # Re-chunking with 2 pages: old 1 chunk purged, 2 new chunks inserted
        ext2 = await persist_extraction(
            session,
            doc,
            ExtractionResult.completed(
                text="Page 1 update" + PAGE_DELIMITER + "Page 2 update",
                method="pypdf",
                version="pypdf/6.0.0",
            ),
        )
        await chunk_and_persist_document(session, doc, ext2)
        await session.commit()

        stmt = select(DocumentChunk).where(DocumentChunk.document_id == doc.id)
        res = await session.execute(stmt)
        all_chunks = list(res.scalars().all())
        assert len(all_chunks) == 2

        # Re-running with same extraction produces identical rows (idempotence)
        await chunk_and_persist_document(session, doc, ext2)
        await session.commit()
        res = await session.execute(stmt)
        assert len(list(res.scalars().all())) == 2


async def test_failed_and_unsupported_gating():
    """FAILED/UNSUPPORTED extractions delete stale chunks and return empty."""
    async with async_session_factory() as session:
        _, doc = await _create_patient_and_document(session)

        # First populate chunks
        ext1 = await persist_extraction(
            session,
            doc,
            ExtractionResult.completed(
                text="Valid report text", method="text/plain", version="text-plain/1.0"
            ),
        )
        await chunk_and_persist_document(session, doc, ext1)
        await session.commit()

        stmt = select(DocumentChunk).where(DocumentChunk.document_id == doc.id)
        res = await session.execute(stmt)
        assert len(list(res.scalars().all())) == 1

        # Now update extraction to FAILED
        ext_failed = await persist_extraction(
            session,
            doc,
            ExtractionResult.failed(
                method="pypdf", version="pypdf/6.0.0", error="Corrupt PDF bytes"
            ),
        )
        chunks_failed = await chunk_and_persist_document(session, doc, ext_failed)
        await session.commit()

        assert chunks_failed == []
        res = await session.execute(stmt)
        # Stale chunks purged!
        assert len(list(res.scalars().all())) == 0


async def test_cascade_deletion():
    """Deleting MedicalDocument cascades to delete its DocumentChunk rows."""
    async with async_session_factory() as session:
        _, doc = await _create_patient_and_document(session)
        ext = await persist_extraction(
            session,
            doc,
            ExtractionResult.completed(
                text="Lab findings to be cascaded",
                method="text/plain",
                version="text-plain/1.0",
            ),
        )
        await chunk_and_persist_document(session, doc, ext)
        await session.commit()

        # Check chunks exist
        stmt = select(DocumentChunk).where(DocumentChunk.document_id == doc.id)
        res = await session.execute(stmt)
        assert len(list(res.scalars().all())) == 1

        # Delete parent document
        await session.delete(doc)
        await session.commit()

        # Verify chunks cascaded
        res = await session.execute(stmt)
        assert len(list(res.scalars().all())) == 0


async def test_cross_patient_tenant_isolation():
    """Verify tenant isolation: Patient B cannot access Patient A's chunks."""
    async with async_session_factory() as session:
        patient_a, doc_a = await _create_patient_and_document(session)
        patient_b, doc_b = await _create_patient_and_document(session)

        ext_a = await persist_extraction(
            session,
            doc_a,
            ExtractionResult.completed(
                text="Patient A private note",
                method="text/plain",
                version="text-plain/1.0",
            ),
        )
        await chunk_and_persist_document(session, doc_a, ext_a)
        await session.commit()

        # Query chunks for Patient B targeting doc_a -> 0 rows
        stmt = select(DocumentChunk).where(
            DocumentChunk.document_id == doc_a.id,
            DocumentChunk.patient_id == patient_b.id,
        )
        res = await session.execute(stmt)
        assert len(list(res.scalars().all())) == 0


# ---------------------------------------------------------------------------
# Upload API integration tests
# ---------------------------------------------------------------------------


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


async def test_upload_api_generates_multipage_chunks(async_client: AsyncClient):
    """POST /documents with multi-page PDF automatically creates chunk rows."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)

    page1_text = "Platelet Count: 250 x10^3/uL. Normal."
    page2_text = "Hemoglobin A1c: 5.4%. Non-diabetic."
    pdf_bytes = _multipage_pdf_bytes([page1_text, page2_text])

    up_p, del_p, dl_p = _patched_s3()
    with up_p, del_p, dl_p:
        response = await async_client.post(
            "/api/v1/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("report.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
            data={"document_type": "lab_report"},
        )

    assert response.status_code == 201, response.text
    doc_id = uuid.UUID(response.json()["id"])

    # Verify chunks in DB
    async with async_session_factory() as session:
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == doc_id)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        res = await session.execute(stmt)
        chunks = list(res.scalars().all())

        assert len(chunks) == 2
        assert chunks[0].chunk_index == 0
        assert chunks[0].page_number == 1
        assert page1_text in chunks[0].chunk_text

        assert chunks[1].chunk_index == 1
        assert chunks[1].page_number == 2
        assert page2_text in chunks[1].chunk_text


async def test_upload_api_non_fatal_chunking_failure(async_client: AsyncClient):
    """If chunking fails during upload, upload still succeeds (201)."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)
    pdf_bytes = _minimal_pdf_bytes("Serum Creatinine 1.0 mg/dL")

    up_p, del_p, dl_p = _patched_s3()
    chunk_p = patch(
        "app.api.documents.chunk_and_persist_document",
        side_effect=RuntimeError("Simulated unexpected chunker crash"),
    )

    with up_p, del_p, dl_p, chunk_p:
        response = await async_client.post(
            "/api/v1/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("report.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
            data={"document_type": "lab_report"},
        )

    # Upload succeeded!
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["extraction_status"] == "COMPLETED"
    doc_id = uuid.UUID(body["id"])

    # Canonical document and extraction are in DB
    async with async_session_factory() as session:
        stmt = select(DocumentExtraction).where(
            DocumentExtraction.document_id == doc_id
        )
        res = await session.execute(stmt)
        extraction = res.scalar_one_or_none()
        assert extraction is not None
        assert extraction.extraction_status == "COMPLETED"

        # Chunks were rolled back/never saved
        stmt_chunks = select(DocumentChunk).where(DocumentChunk.document_id == doc_id)
        res_chunks = await session.execute(stmt_chunks)
        assert len(list(res_chunks.scalars().all())) == 0


async def test_upload_api_generates_single_page_chunks(
    async_client: AsyncClient,
):
    """POST /documents with 1-page PDF produces chunk with page_number=1."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)
    pdf_bytes = _minimal_pdf_bytes("Serum Creatinine 0.9 mg/dL. Normal.")

    up_p, del_p, dl_p = _patched_s3()
    with up_p, del_p, dl_p:
        response = await async_client.post(
            "/api/v1/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("single.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
            data={"document_type": "lab_report"},
        )

    assert response.status_code == 201, response.text
    doc_id = uuid.UUID(response.json()["id"])

    async with async_session_factory() as session:
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == doc_id)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        res = await session.execute(stmt)
        chunks = list(res.scalars().all())

        assert len(chunks) == 1
        assert chunks[0].chunk_index == 0
        assert chunks[0].page_number == 1
        assert "Serum Creatinine" in chunks[0].chunk_text


async def test_plain_text_and_legacy_extraction_has_none_page_number():
    """Plain text or legacy extractions produce chunks with page_number=None."""
    async with async_session_factory() as session:
        _, doc = await _create_patient_and_document(session)

        # 1. Plain text extraction (method='text/plain')
        ext_plain = await persist_extraction(
            session,
            doc,
            ExtractionResult.completed(
                text="Clinical progress note: Patient is recovering well.",
                method="text/plain",
                version="text-plain/1.0",
            ),
        )
        chunks_plain = await chunk_and_persist_document(session, doc, ext_plain)
        await session.commit()

        assert len(chunks_plain) == 1
        assert chunks_plain[0].chunk_index == 0
        assert chunks_plain[0].page_number is None
        assert "Clinical progress note" in chunks_plain[0].chunk_text

        # 2. Legacy extraction without pypdf
        ext_legacy = await persist_extraction(
            session,
            doc,
            ExtractionResult.completed(
                text="Legacy note without page delimiters.",
                method="legacy_extractor",
                version="legacy/1.0",
            ),
        )
        chunks_legacy = await chunk_and_persist_document(session, doc, ext_legacy)
        await session.commit()

        assert len(chunks_legacy) == 1
        assert chunks_legacy[0].chunk_index == 0
        assert chunks_legacy[0].page_number is None


async def test_upload_api_db_constraint_failure_rolls_back_and_session_usable(
    async_client: AsyncClient,
):
    """Real PostgreSQL constraint failure during chunking triggers rollback safely."""
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)
    pdf_bytes = _minimal_pdf_bytes("Valid text content")

    up_p, del_p, dl_p = _patched_s3()

    # Chunker returns an illegal empty chunk draft, triggering real PostgreSQL
    # check constraint ck_document_chunks_non_empty_text during flush.
    class IllegalEmptyChunker(DocumentChunker):
        def chunk_document_text(
            self, text: str, default_page_number=None
        ) -> list[ChunkDraft]:
            return [ChunkDraft(chunk_index=0, chunk_text="", page_number=1)]

    async def _failing_chunk_and_persist(db, doc, ext):
        return await chunk_and_persist_document(
            db, doc, ext, chunker=IllegalEmptyChunker()
        )

    with up_p, del_p, dl_p:
        with patch(
            "app.api.documents.chunk_and_persist_document",
            side_effect=_failing_chunk_and_persist,
        ):
            response = await async_client.post(
                "/api/v1/documents",
                headers={"Authorization": f"Bearer {token}"},
                files={
                    "file": ("report.pdf", io.BytesIO(pdf_bytes), "application/pdf")
                },
                data={"document_type": "lab_report"},
            )

    # 1. Upload succeeded with HTTP 201 because chunking failure was non-fatal
    assert response.status_code == 201, response.text
    body = response.json()
    # 2. Session refresh succeeded without PendingRollbackError
    assert body["extraction_status"] == "COMPLETED"
    doc_id = uuid.UUID(body["id"])

    # 3. Canonical document and extraction are durable in DB
    async with async_session_factory() as session:
        stmt = select(DocumentExtraction).where(
            DocumentExtraction.document_id == doc_id
        )
        res = await session.execute(stmt)
        extraction = res.scalar_one_or_none()
        assert extraction is not None
        assert extraction.extraction_status == "COMPLETED"

        # 4. Chunks were cleanly rolled back
        stmt_chunks = select(DocumentChunk).where(DocumentChunk.document_id == doc_id)
        res_chunks = await session.execute(stmt_chunks)
        assert len(list(res_chunks.scalars().all())) == 0


async def test_upload_api_chunk_commit_failure_rolls_back_and_prevents_error(
    async_client: AsyncClient,
):
    """If db.commit() fails when persisting chunks, rollback cleans session."""
    from sqlalchemy.exc import OperationalError

    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)
    pdf_bytes = _minimal_pdf_bytes("Valid report data")

    up_p, del_p, dl_p = _patched_s3()

    # Let persist_extraction commit, but make the subsequent chunk commit fail
    real_commit = AsyncSession.commit
    commit_calls = 0

    async def _failing_chunk_commit(session_self):
        nonlocal commit_calls
        commit_calls += 1
        # Call 1: create_document commit
        # Call 2: persist_extraction commit
        # Call 3: chunk commit -> fail!
        if commit_calls == 3:
            raise OperationalError(
                "COMMIT",
                {},
                Exception("Simulated DB connection lost during chunk commit"),
            )
        return await real_commit(session_self)

    with up_p, del_p, dl_p:
        with patch.object(AsyncSession, "commit", new=_failing_chunk_commit):
            response = await async_client.post(
                "/api/v1/documents",
                headers={"Authorization": f"Bearer {token}"},
                files={
                    "file": ("report.pdf", io.BytesIO(pdf_bytes), "application/pdf")
                },
                data={"document_type": "lab_report"},
            )

    # Thanks to await db.rollback(), db.refresh does NOT raise PendingRollbackError,
    # and the upload returns HTTP 201 with extraction status!
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["extraction_status"] == "COMPLETED"
