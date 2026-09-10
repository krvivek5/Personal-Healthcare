"""
Document service layer for medical documents.

Functions follow the pattern established in conditions.py.
S3 interactions are passed in as callables so the service layer
stays infrastructure-independent and testable.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MedicalDocument


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
