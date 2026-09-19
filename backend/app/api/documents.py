"""
Document API routes.

Endpoints:
  POST   /documents            — upload (multipart)
  GET    /documents            — list
  GET    /documents/{id}       — get metadata
  GET    /documents/{id}/download — stream file from S3
  PATCH  /documents/{id}       — update mutable metadata
  DELETE /documents/{id}       — hard delete (S3 + DB)

Storage / Database consistency (best-effort, no distributed atomicity):

  Upload:
    1. Validate file.
    2. Upload to S3.
    3. Insert DB row.
    4. If DB insert fails → compensating S3 delete → return 500.

  Delete:
    1. Delete S3 object.
    2. If S3 delete fails → abort, return 500 (DB row preserved).
    3. Delete DB row.
    4. If DB delete fails → return 500 (DB row remains, S3 gone; accepted for MVP).
    5. Return 204 only on full success.

Content-Disposition safety:
  The raw filename from the DB is untrusted.  It is sanitised before being
  placed into the Content-Disposition header to prevent CR/LF injection.
"""

from __future__ import annotations

import logging
import re
import uuid

from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.auth import AuthenticatedUser, get_current_user
from app.core.file_validation import validate_upload
from app.db.session import get_db
from app.health.chunking import chunk_and_persist_document
from app.health.documents import (
    create_document,
    delete_document,
    get_document_by_id,
    get_documents,
    persist_extraction,
    update_document,
)
from app.health.extraction import DispatchingExtractor
from app.health.patient import get_or_create_patient
from app.schemas.document import DocumentResponse, DocumentType, DocumentUpdate

logger = logging.getLogger(__name__)

# M3 Slice 3: module-level extractor instance (pluggable via constructor).
_extractor = DispatchingExtractor()

router = APIRouter(prefix="/documents", tags=["documents"])

# ── Helpers ────────────────────────────────────────────────────────────────────

# Characters that must not appear in a Content-Disposition header value.
_UNSAFE_HEADER_CHARS = re.compile(r'[\r\n\x00-\x1f\x7f"\\]')


def _safe_content_disposition(filename: str) -> str:
    """
    Build a safe Content-Disposition header value.

    Strips CR, LF, NUL, control characters, double-quotes and backslashes
    from *filename* to prevent header injection.  Falls back to 'document'
    if the sanitised result is empty.

    The quoted filename= parameter uses the stripped name directly (safe for
    ASCII filenames).  The filename*= parameter uses RFC 5987 percent-encoding
    for non-ASCII characters.
    """
    safe = _UNSAFE_HEADER_CHARS.sub("", filename)
    if not safe:
        safe = "document"
    # RFC 5987 / RFC 6266 encoding for extended filename parameter.
    from urllib.parse import quote

    encoded = quote(safe, safe="!#$&+-.^_`|~")
    return f"attachment; filename=\"{safe}\"; filename*=UTF-8''{encoded}"


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    file: UploadFile,
    document_type: DocumentType = Form(...),
    display_name: str = Form(""),
    document_date: str = Form(None),
    notes: str = Form(None),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    """
    Upload a medical document.

    Multipart form fields:
      file           — the file (required)
      document_type  — one of the allowed DocumentType values (required)
      display_name   — user-readable name (optional; defaults to filename)
      document_date  — date on the document (optional, YYYY-MM-DD)
      notes          — free-text notes (optional)
    """
    # 1. Validate file (bounded reads).
    content_type, file_size = await validate_upload(file)

    # 2. Rewind after validation before reading again for upload.
    await file.seek(0)

    patient = await get_or_create_patient(db, current_user.id)

    # 3. Build storage key.
    doc_uuid = uuid.uuid4()
    storage_key = f"documents/{patient.id}/{doc_uuid}"

    # 4. Upload to S3.
    file_bytes = await file.read()
    try:
        await storage.upload_file(storage_key, file_bytes, content_type)
    except Exception as exc:
        logger.error("S3 upload failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload file to storage.",
        ) from exc

    # 5. Insert DB row; compensate on failure.
    from datetime import date as _date

    doc_date = None
    if document_date:
        try:
            doc_date = _date.fromisoformat(document_date)
        except ValueError:
            # Invalid date; ignore gracefully (DB stores null)
            doc_date = None

    original_filename = file.filename or "document"
    resolved_display = display_name.strip() or original_filename

    metadata = {
        "file_name": original_filename,
        "display_name": resolved_display,
        "document_type": document_type,
        "content_type": content_type,
        "file_size_bytes": file_size,
        "document_date": doc_date,
        "notes": notes or None,
    }

    try:
        doc = await create_document(db, patient.id, metadata, storage_key)
    except Exception as db_exc:
        logger.error("DB insert failed after S3 upload; compensating: %s", db_exc)
        # Compensating delete — best-effort.
        try:
            await storage.delete_file(storage_key)
        except Exception as s3_exc:
            logger.error("Compensating S3 delete also failed: %s", s3_exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save document metadata.",
        ) from db_exc

    # 6. Extract text — best-effort: upload success is independent of extraction.
    #    The canonical MedicalDocument is already committed.  A failure here
    #    persists a FAILED/UNSUPPORTED extraction row; it does NOT roll back
    #    the document or return a non-2xx to the client.
    extraction_persisted = False
    doc_id = doc.id

    try:
        extraction_result = await _extractor.extract_text(file_bytes, content_type)
        extraction = await persist_extraction(db, doc, extraction_result)
        extraction_persisted = True

        # 7. Chunk document — derived data pipeline (non-fatal to upload)
        if extraction.extraction_status == "COMPLETED":
            try:
                await chunk_and_persist_document(db, doc, extraction)
                await db.commit()

                # 8. Embed chunks — provider-neutral pipeline (non-fatal to upload)
                try:
                    from app.health.embedding_pipeline import embed_document_chunks

                    await embed_document_chunks(db, doc)
                    await db.commit()
                except Exception as emb_exc:
                    logger.warning(
                        "Embedding deferred for document %s: %s",
                        doc_id,
                        emb_exc,
                    )
                    # Session hygiene: rollback aborted transaction state
                    # so session remains healthy for subsequent refresh/queries.
                    await db.rollback()
            except Exception as chunk_exc:
                logger.error(
                    "Chunking failure for document %s: %s",
                    doc_id,
                    chunk_exc,
                )
                await db.rollback()

    except Exception as ext_exc:  # pragma: no cover — defensive belt-and-braces
        logger.error(
            "Extraction/persistence error for document %s: %s",
            doc_id,
            ext_exc,
        )
        # Do NOT re-raise — the document upload already succeeded.

    # Refresh to load the document_extraction relationship for response serialisation.
    if extraction_persisted:
        await db.refresh(doc, ["document_extraction"])

    return DocumentResponse.model_validate(doc)


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentResponse]:
    """List all documents belonging to the authenticated patient."""
    patient = await get_or_create_patient(db, current_user.id)
    docs = await get_documents(db, patient.id)
    await db.commit()
    return [DocumentResponse.model_validate(d) for d in docs]


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    """Get a single document's metadata by ID."""
    patient = await get_or_create_patient(db, current_user.id)
    doc = await get_document_by_id(db, document_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    if doc.patient_id != patient.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this resource",
        )
    await db.commit()
    return DocumentResponse.model_validate(doc)


@router.get("/{document_id}/download")
async def download_document(
    document_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Stream the original file from S3.

    Content-Disposition is constructed safely to prevent header injection.
    """
    patient = await get_or_create_patient(db, current_user.id)
    doc = await get_document_by_id(db, document_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    if doc.patient_id != patient.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this resource",
        )
    await db.commit()

    content_disposition = _safe_content_disposition(doc.file_name)

    async def _stream():
        async for chunk in storage.download_file(doc.storage_key):
            yield chunk

    return StreamingResponse(
        _stream(),
        media_type=doc.content_type,
        headers={"Content-Disposition": content_disposition},
    )


@router.patch("/{document_id}", response_model=DocumentResponse)
async def patch_document(
    document_id: uuid.UUID,
    doc_in: DocumentUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    """Update mutable metadata (display_name, document_type, document_date, notes)."""
    patient = await get_or_create_patient(db, current_user.id)
    doc = await get_document_by_id(db, document_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    if doc.patient_id != patient.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this resource",
        )
    data = doc_in.model_dump(exclude_unset=True)
    updated = await update_document(db, doc, data)
    return DocumentResponse.model_validate(updated)


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def remove_document(
    document_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Hard delete: S3 object + DB row.

    Returns 204 only on full success. No silent partial success.

    Failure modes:
    - S3 delete fails → abort, return 500. DB row preserved. System consistent.
    - S3 succeeds, DB delete fails → return 500.
      DB row remains pointing to deleted S3 object (accepted MVP behaviour).
    """
    patient = await get_or_create_patient(db, current_user.id)
    doc = await get_document_by_id(db, document_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    if doc.patient_id != patient.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this resource",
        )

    storage_key = doc.storage_key

    # Step 1: Delete from S3.
    try:
        await storage.delete_file(storage_key)
    except ClientError as exc:
        logger.error("S3 delete failed for key %s: %s", storage_key, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete file from storage.",
        ) from exc

    # Step 2: Delete DB row.
    try:
        await delete_document(db, doc)
    except Exception as exc:
        logger.error(
            "DB delete failed after S3 delete for key %s: %s", storage_key, exc
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="File deleted from storage but metadata deletion failed.",
        ) from exc

    return None
