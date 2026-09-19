from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import (
    EmbeddingInputError,
    EmbeddingProvider,
    EmbeddingProviderError,
    get_embedding_provider,
)
from app.db.models import DocumentChunk, MedicalDocument

logger = logging.getLogger(__name__)


def format_passage_for_embedding(chunk_text: str) -> str:
    """Format a document chunk text passage for vector embedding.

    Establishes the canonical document-side embedding representation.
    Normalizes whitespace and strips boundary artifacts without mutating
    clinical terminology or laboratory values.
    """
    cleaned = " ".join(chunk_text.split()).strip()
    if not cleaned:
        raise EmbeddingInputError("Cannot format empty or whitespace-only passage")
    return cleaned


@dataclass(frozen=True)
class ChunkSnapshot:
    """In-memory snapshot of a chunk captured during Phase A."""

    id: uuid.UUID
    patient_id: uuid.UUID
    chunk_index: int
    chunk_text: str


async def embed_document_chunks(
    db: AsyncSession,
    document: MedicalDocument,
    provider: Optional[EmbeddingProvider] = None,
    force_reembed: bool = False,
) -> int:
    """Generate and persist vector embeddings for chunks of *document*.

    Adheres strictly to the Three-Phase Decoupled Lifecycle:
      - Phase A: Capture scalar IDs, read chunk snapshots, and rollback read state.
      - Phase B: Execute provider.embed_batch() outside any DB transaction.
      - Phase C: Persist inside begin_nested() using captured scalars with
                 stale-chunk protection.

    Returns:
      Number of chunk embeddings successfully updated.
    """
    if provider is None:
        provider = get_embedding_provider()

    # -------------------------------------------------------------------------
    # PHASE A — READ & SCALAR CAPTURE
    # -------------------------------------------------------------------------
    # 1. Capture immutable scalar identifiers BEFORE rollback
    insp = inspect(document)
    if insp is not None and insp.expired:
        await db.refresh(document, ["id", "patient_id"])
    doc_id: uuid.UUID = document.id
    p_id: uuid.UUID = document.patient_id

    stmt = (
        select(
            DocumentChunk.id,
            DocumentChunk.patient_id,
            DocumentChunk.chunk_index,
            DocumentChunk.chunk_text,
        )
        .where(
            DocumentChunk.document_id == doc_id,
            DocumentChunk.patient_id == p_id,
        )
        .order_by(DocumentChunk.chunk_index.asc())
    )
    if not force_reembed:
        stmt = stmt.where(DocumentChunk.embedding.is_(None))

    result = await db.execute(stmt)
    rows = result.all()

    if not rows:
        return 0

    snapshots = [
        ChunkSnapshot(
            id=r.id,
            patient_id=r.patient_id,
            chunk_index=r.chunk_index,
            chunk_text=r.chunk_text,
        )
        for r in rows
    ]

    # Explicitly reset the read transaction state before entering network I/O.
    # INVARIANT: Do NOT access document.* after this point.
    await db.rollback()

    # -------------------------------------------------------------------------
    # PHASE B — EXTERNAL EMBEDDING (ZERO DB LOCKS HELD)
    # -------------------------------------------------------------------------
    texts = [format_passage_for_embedding(s.chunk_text) for s in snapshots]
    vectors = await provider.embed_batch(texts)

    if len(vectors) != len(snapshots):
        raise EmbeddingProviderError(
            f"Provider returned {len(vectors)} vectors for {len(snapshots)} chunks"
        )

    # -------------------------------------------------------------------------
    # PHASE C — PERSIST WITH STALE-CHUNK PROTECTION (USING SCALARS)
    # -------------------------------------------------------------------------
    target_ids = [s.id for s in snapshots]
    async with db.begin_nested():
        refetch_stmt = select(DocumentChunk).where(
            DocumentChunk.document_id == doc_id,
            DocumentChunk.patient_id == p_id,
            DocumentChunk.id.in_(target_ids),
        )
        refetch_res = await db.execute(refetch_stmt)
        existing_chunks_by_id = {c.id: c for c in refetch_res.scalars().all()}

        updated_count = 0
        for snapshot, vector in zip(snapshots, vectors):
            chunk = existing_chunks_by_id.get(snapshot.id)
            if chunk is None:
                logger.warning(
                    "Stale chunk %s for document %s was replaced/deleted during "
                    "embedding; skipping.",
                    snapshot.id,
                    doc_id,
                )
                continue

            if chunk.chunk_text != snapshot.chunk_text:
                logger.warning(
                    "Chunk text modified for chunk %s; skipping stale embedding.",
                    snapshot.id,
                )
                continue

            chunk.embedding = vector
            updated_count += 1

        await db.flush()

    return updated_count


@dataclass(frozen=True)
class BackfillResult:
    documents_processed: int
    chunks_embedded: int
    failures: int


async def backfill_embeddings(
    db: AsyncSession,
    provider: Optional[EmbeddingProvider] = None,
    patient_id: Optional[uuid.UUID] = None,
) -> BackfillResult:
    """Idempotently backfill embeddings for any DocumentChunk rows missing embeddings.

    Guarantees:
      - Resumable: Queries chunks WHERE embedding IS NULL.
      - Tenant-Safe: Operates document-by-document. When patient_id is provided,
        limits backfill strictly to that patient.
      - Read-Only on Canonical Tables: Never mutates MedicalDocument or
        DocumentExtraction.
      - Checkpointed: Commits per document so progress is immediately durable.
    """
    if provider is None:
        provider = get_embedding_provider()

    query = (
        select(DocumentChunk.document_id, DocumentChunk.patient_id)
        .where(DocumentChunk.embedding.is_(None))
        .distinct()
    )
    if patient_id is not None:
        query = query.where(DocumentChunk.patient_id == patient_id)

    result = await db.execute(query)
    pending_docs = list(result.all())

    docs_processed = 0
    chunks_embedded = 0
    failures = 0

    for doc_id, p_id in pending_docs:
        doc_stmt = select(MedicalDocument).where(
            MedicalDocument.id == doc_id,
            MedicalDocument.patient_id == p_id,
        )
        doc_res = await db.execute(doc_stmt)
        doc = doc_res.scalar_one_or_none()
        if doc is None:
            continue

        try:
            count = await embed_document_chunks(
                db, doc, provider=provider, force_reembed=False
            )
            await db.commit()
            docs_processed += 1
            chunks_embedded += count
        except Exception as exc:
            logger.error("Backfill failed for document %s: %s", doc_id, exc)
            await db.rollback()
            failures += 1

    return BackfillResult(
        documents_processed=docs_processed,
        chunks_embedded=chunks_embedded,
        failures=failures,
    )
