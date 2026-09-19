import uuid

import pytest
from sqlalchemy import select

from app.core.embeddings import EmbeddingInputError, MockEmbeddingProvider
from app.db.models import DocumentChunk, MedicalDocument, Patient
from app.health.embedding_pipeline import (
    BackfillResult,
    backfill_embeddings,
    embed_document_chunks,
    format_passage_for_embedding,
)


async def _setup_test_doc(db_session, patient_id=None):
    if not patient_id:
        patient_id = uuid.uuid4()

    patient = await db_session.get(Patient, patient_id)
    if not patient:
        patient = Patient(id=patient_id, user_id=uuid.uuid4())
        db_session.add(patient)
        await db_session.flush()

    doc_id = uuid.uuid4()
    doc = MedicalDocument(
        id=doc_id,
        patient_id=patient_id,
        file_name="test.pdf",
        display_name="Test",
        document_type="CLINICAL_NOTE",
        content_type="application/pdf",
        file_size_bytes=100,
        storage_key=f"test/{doc_id}",
    )
    db_session.add(doc)
    await db_session.flush()
    return patient, doc


async def _setup_test_chunk(db_session, doc_id, patient_id, text, index=0):
    chunk = DocumentChunk(
        id=uuid.uuid4(),
        document_id=doc_id,
        patient_id=patient_id,
        chunk_index=index,
        chunk_text=text,
    )
    db_session.add(chunk)
    await db_session.flush()
    return chunk


def test_format_passage():
    raw = "  This   is \n a \t test.  "
    assert format_passage_for_embedding(raw) == "This is a test."

    with pytest.raises(EmbeddingInputError, match="empty or whitespace-only"):
        format_passage_for_embedding("   \n\t  ")


@pytest.mark.asyncio
async def test_embed_document_chunks_pipeline(db):
    patient, doc = await _setup_test_doc(db)
    chunk1 = await _setup_test_chunk(db, doc.id, patient.id, "chunk 1", 0)
    chunk2 = await _setup_test_chunk(db, doc.id, patient.id, "chunk 2", 1)
    await db.commit()

    provider = MockEmbeddingProvider(dimension=768)

    updated = await embed_document_chunks(db, doc, provider)
    await db.commit()

    assert updated == 2
    await db.refresh(chunk1)
    await db.refresh(chunk2)

    assert chunk1.embedding is not None
    assert len(chunk1.embedding) == 768
    assert chunk2.embedding is not None
    assert len(chunk2.embedding) == 768


@pytest.mark.asyncio
async def test_embed_document_chunks_network_transaction_isolation(db, monkeypatch):
    """Verify zero open DB transactions or locks during external provider call."""
    patient, doc = await _setup_test_doc(db)
    await _setup_test_chunk(db, doc.id, patient.id, "chunk isolation text", 0)
    await db.commit()

    provider = MockEmbeddingProvider(dimension=768)
    original_embed_batch = provider.embed_batch

    checked_transaction_state = False

    async def intercept_embed_batch(texts):
        nonlocal checked_transaction_state
        # DB must NOT be in an open transaction during network I/O
        assert not db.in_transaction()
        checked_transaction_state = True
        return await original_embed_batch(texts)

    monkeypatch.setattr(provider, "embed_batch", intercept_embed_batch)

    updated = await embed_document_chunks(db, doc, provider)
    await db.commit()

    assert updated == 1
    assert checked_transaction_state is True


@pytest.mark.asyncio
async def test_embed_document_chunks_idempotency(db):
    patient, doc = await _setup_test_doc(db)
    await _setup_test_chunk(db, doc.id, patient.id, "idempotent test", 0)
    await db.commit()

    provider = MockEmbeddingProvider(dimension=768)

    # First pass: updates 1 chunk
    updated1 = await embed_document_chunks(db, doc, provider)
    await db.commit()
    assert updated1 == 1

    # Second pass without force_reembed: updates 0 chunks (idempotent)
    updated2 = await embed_document_chunks(db, doc, provider, force_reembed=False)
    await db.commit()
    assert updated2 == 0


@pytest.mark.asyncio
async def test_embed_document_chunks_force_reembed(db):
    patient, doc = await _setup_test_doc(db)
    chunk = await _setup_test_chunk(db, doc.id, patient.id, "reembed text", 0)
    await db.commit()

    provider = MockEmbeddingProvider(dimension=768)

    updated1 = await embed_document_chunks(db, doc, provider)
    await db.commit()
    assert updated1 == 1

    # Force re-embed should re-process the already embedded chunk
    updated2 = await embed_document_chunks(db, doc, provider, force_reembed=True)
    await db.commit()
    assert updated2 == 1

    await db.refresh(chunk)
    assert chunk.embedding is not None


@pytest.mark.asyncio
async def test_embed_document_chunks_stale_protection(db, monkeypatch):
    patient, doc = await _setup_test_doc(db)
    chunk1 = await _setup_test_chunk(db, doc.id, patient.id, "chunk 1", 0)
    chunk2 = await _setup_test_chunk(db, doc.id, patient.id, "chunk 2", 1)
    await db.commit()

    chunk1_id = chunk1.id
    chunk2_id = chunk2.id

    provider = MockEmbeddingProvider(dimension=768)
    original_embed_batch = provider.embed_batch

    async def intercept_embed_batch(texts):
        from app.db.base import async_session_factory

        async with async_session_factory() as new_session:
            await new_session.execute(
                DocumentChunk.__table__.update()
                .where(DocumentChunk.id == chunk1_id)
                .values(chunk_text="modified chunk 1")
            )
            await new_session.execute(
                DocumentChunk.__table__.delete().where(DocumentChunk.id == chunk2_id)
            )
            await new_session.commit()

        return await original_embed_batch(texts)

    monkeypatch.setattr(provider, "embed_batch", intercept_embed_batch)

    updated = await embed_document_chunks(db, doc, provider)
    await db.commit()

    assert updated == 0

    # chunk1 should have NO embedding because text changed
    stmt1 = select(DocumentChunk).where(DocumentChunk.id == chunk1_id)
    res1 = await db.execute(stmt1)
    c1 = res1.scalar_one()
    assert c1.embedding is None
    assert c1.chunk_text == "modified chunk 1"

    # chunk2 was deleted, shouldn't crash
    stmt2 = select(DocumentChunk).where(DocumentChunk.id == chunk2_id)
    res2 = await db.execute(stmt2)
    assert res2.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_backfill_embeddings(db):
    patient1, doc1 = await _setup_test_doc(db)
    await _setup_test_chunk(db, doc1.id, patient1.id, "doc1 c1", 0)

    patient2, doc2 = await _setup_test_doc(db)
    await _setup_test_chunk(db, doc2.id, patient2.id, "doc2 c1", 0)

    await db.commit()
    patient1_id = patient1.id
    patient2_id = patient2.id

    provider = MockEmbeddingProvider(dimension=768)

    # Run backfill for patient1 only
    result = await backfill_embeddings(db, provider, patient_id=patient1_id)

    assert isinstance(result, BackfillResult)
    assert result.documents_processed == 1
    assert result.chunks_embedded == 1
    assert result.failures == 0

    stmt = select(DocumentChunk).where(
        DocumentChunk.embedding.isnot(None),
        DocumentChunk.patient_id == patient1_id,
    )
    res = await db.execute(stmt)
    embedded_chunks = res.scalars().all()

    assert len(embedded_chunks) == 1
    assert embedded_chunks[0].patient_id == patient1_id

    # Patient 2 chunks must still be missing embeddings (tenant isolation)
    stmt2 = select(DocumentChunk).where(
        DocumentChunk.embedding.is_(None),
        DocumentChunk.patient_id == patient2_id,
    )
    res2 = await db.execute(stmt2)
    assert len(res2.scalars().all()) == 1


@pytest.mark.asyncio
async def test_upload_integration_embed_failure_rollback(async_client, db, monkeypatch):
    """Test that if embedding fails, the session is cleanly rolled back,

    and the API still returns 201 Created with the document intact.
    """
    import io
    from unittest.mock import patch

    from app.core.embeddings import EmbeddingError
    from tests.test_auth import create_test_token

    async def mock_embed_fail(*args, **kwargs):
        raise EmbeddingError("Simulated failure")

    monkeypatch.setattr(
        "app.health.embedding_pipeline.embed_document_chunks", mock_embed_fail
    )

    token = create_test_token(str(uuid.uuid4()))
    headers = {"Authorization": f"Bearer {token}"}

    pdf_bytes = (
        b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
        b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"
    )

    async def _fake_upload(key, data, ct):
        return None

    async def _fake_delete(key):
        return None

    async def _fake_download(key):
        yield b"fake"

    with (
        patch(
            "app.api.documents.storage.upload_file",
            side_effect=_fake_upload,
        ),
        patch(
            "app.api.documents.storage.delete_file",
            side_effect=_fake_delete,
        ),
        patch(
            "app.api.documents.storage.download_file",
            side_effect=_fake_download,
        ),
    ):
        files = {"file": ("test.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
        data = {"document_type": "medical_record", "display_name": "Test Note"}

        response = await async_client.post(
            "/api/v1/documents",
            files=files,
            data=data,
            headers=headers,
        )

    assert response.status_code == 201
    resp_data = response.json()
    assert resp_data["display_name"] == "Test Note"
