"""
Document service layer for medical documents.

Functions follow the pattern established in conditions.py.
S3 interactions are passed in as callables so the service layer
stays infrastructure-independent and testable.

M3 Slice 3 addition:
  persist_extraction() — create or idempotently update the one-to-one
  DocumentExtraction record linked to a canonical MedicalDocument.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DocumentExtraction, MedicalDocument
from app.health.extraction import ExtractionResult

logger = logging.getLogger(__name__)


async def get_documents(
    db: AsyncSession,
    patient_id: uuid.UUID,
) -> list[MedicalDocument]:
    """Return all documents for *patient_id*, ordered newest first."""
    stmt = (
        select(MedicalDocument)
        .where(MedicalDocument.patient_id == patient_id)
        .order_by(MedicalDocument.uploaded_at.desc(), MedicalDocument.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_document_by_id(
    db: AsyncSession,
    document_id: uuid.UUID,
) -> Optional[MedicalDocument]:
    """Retrieve a specific document by its ID."""
    stmt = select(MedicalDocument).where(MedicalDocument.id == document_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_document(
    db: AsyncSession,
    patient_id: uuid.UUID,
    metadata: dict[str, Any],
    storage_key: str,
) -> MedicalDocument:
    """
    Insert a new MedicalDocument row.

    *metadata* must include: file_name, display_name, document_type,
    content_type, file_size_bytes. Optional: document_date, notes.

    *storage_key* is the S3 object key (internal, never client-facing).

    The caller is responsible for uploading to S3 before calling this function
    and for compensating (deleting the S3 object) if this function raises.
    """
    doc = MedicalDocument(
        patient_id=patient_id,
        storage_key=storage_key,
        source_type="PATIENT_REPORTED",
        **{k: v for k, v in metadata.items() if v is not None},
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


async def update_document(
    db: AsyncSession,
    document: MedicalDocument,
    data: dict[str, Any],
) -> MedicalDocument:
    """
    Patch mutable metadata fields on *document*.

    Only display_name, document_type, document_date, and notes may be updated.
    storage_key and source_type are immutable via this function.
    """
    mutable_fields = {"display_name", "document_type", "document_date", "notes"}
    for key, value in data.items():
        if key in mutable_fields:
            setattr(document, key, value)
    await db.commit()
    await db.refresh(document)
    return document


async def delete_document(
    db: AsyncSession,
    document: MedicalDocument,
) -> None:
    """
    Delete *document* from the database.

    The caller must delete the S3 object *before* calling this function.
    If the S3 delete succeeded but this function raises, the caller should
    surface a 500 to the client (the DB row remains; no silent success).
    """
    await db.delete(document)
    await db.commit()


async def persist_extraction(
    db: AsyncSession,
    document: MedicalDocument,
    result: ExtractionResult,
) -> DocumentExtraction:
    """Persist (or idempotently replace) a DocumentExtraction for *document*.

    Tenant safety:
      - patient_id is always taken from *document.patient_id*.  The caller
        must never supply a client-provided patient_id.
      - The composite FK on (document_id, patient_id) enforces DB-level
        tenant integrity (established in Slice 1).

    Idempotency:
      - If a DocumentExtraction already exists for document.id, its fields
        are updated in place rather than inserting a duplicate row.
      - The one-to-one unique constraint on document_id guarantees that a
        second INSERT would fail; this function prevents that by checking first.

    Lifecycle:
      - COMPLETED  → extracted_text is set; error_message is None.
      - FAILED     → extracted_text is None; error_message is set.
      - UNSUPPORTED→ extracted_text is None; error_message set if available.
    """
    extracted_at = datetime.now(timezone.utc)

    # Look up any existing extraction for this document.
    stmt = select(DocumentExtraction).where(
        DocumentExtraction.document_id == document.id
    )
    row = await db.execute(stmt)
    extraction: Optional[DocumentExtraction] = row.scalar_one_or_none()

    if extraction is None:
        extraction = DocumentExtraction(
            document_id=document.id,
            patient_id=document.patient_id,  # always from canonical document
            extracted_text=result.extracted_text,
            extraction_status=result.status,
            extraction_method=result.extraction_method,
            extraction_version=result.extraction_version,
            extracted_at=extracted_at,
            error_message=result.error_message,
        )
        db.add(extraction)
    else:
        # Update in place — do not create a second row.
        # Use an UPDATE statement to avoid multi-field @validates conflicts
        # when transitioning between COMPLETED and FAILED/UNSUPPORTED.
        from sqlalchemy import update

        upd_stmt = (
            update(DocumentExtraction)
            .where(DocumentExtraction.id == extraction.id)
            .values(
                extracted_text=result.extracted_text,
                extraction_status=result.status,
                extraction_method=result.extraction_method,
                extraction_version=result.extraction_version,
                extracted_at=extracted_at,
                error_message=result.error_message,
            )
        )
        await db.execute(upd_stmt)

    await db.commit()
    await db.refresh(extraction)
    logger.info(
        "DocumentExtraction persisted: document_id=%s status=%s",
        document.id,
        result.status,
    )
    return extraction
