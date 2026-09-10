"""
Pydantic schemas for medical documents.

Security constraint: DocumentResponse explicitly excludes storage_key and
any other internal S3 identifiers. Clients must never receive the S3 key.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

# ── Document type enum ─────────────────────────────────────────────────────────

DocumentType = Literal[
    "lab_report",
    "prescription",
    "diagnostic_report",
    "discharge_summary",
    "medical_record",
    "other",
]

# ── Response schema ────────────────────────────────────────────────────────────


class DocumentResponse(BaseModel):
    """
    Public representation of a medical document.

    storage_key is intentionally absent — it is an internal S3 identifier
    that must never be exposed to API clients.
    """

    id: uuid.UUID
    patient_id: uuid.UUID
    file_name: str
    display_name: str
    document_type: str
    content_type: str
    file_size_bytes: int
    document_date: Optional[date]
    notes: Optional[str]
    source_type: str
    uploaded_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── Update schema ──────────────────────────────────────────────────────────────


class DocumentUpdate(BaseModel):
    """Mutable metadata fields that a client may update."""

    display_name: Optional[str] = None
    document_type: Optional[DocumentType] = None
    document_date: Optional[date] = None
    notes: Optional[str] = None
