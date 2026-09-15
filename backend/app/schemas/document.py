"""
Pydantic schemas for medical documents.

Security constraint: DocumentResponse explicitly excludes storage_key and
any other internal S3 identifiers. Clients must never receive the S3 key.

M6 Provenance Contract for medical_documents:
  - Upload and update payloads MUST NOT include source_type, source_id, or
    verification_state. Any attempt returns HTTP 422 (no silent ignore).
  - DocumentResponse exposes source_type and verification_state only.
    No source_id is exposed (no document-to-document chains).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, model_validator

# ── Document type enum ─────────────────────────────────────────────────────────

DocumentType = Literal[
    "lab_report",
    "prescription",
    "diagnostic_report",
    "discharge_summary",
    "medical_record",
    "other",
]

# ── Provenance rejection helper ────────────────────────────────────────────────

_REJECTED_FIELDS = frozenset({"source_type", "source_id", "verification_state"})


def _reject_provenance_fields(data: dict) -> None:
    """Raise ValueError if the payload contains any provenance field."""
    present = _REJECTED_FIELDS & data.keys()
    if present:
        field_list = ", ".join(sorted(present))
        raise ValueError(
            "Medical document payloads must not include provenance fields: "
            f"{field_list}. These values are locked server-side."
        )


# ── Response schema ────────────────────────────────────────────────────────────


class DocumentResponse(BaseModel):
    """
    Public representation of a medical document.

    storage_key is intentionally absent — it is an internal S3 identifier
    that must never be exposed to API clients.

    source_id is intentionally absent — medical_documents do not chain to
    other documents. source_type and verification_state are always
    'PATIENT_REPORTED' (enforced by DB CHECK constraints).

    M3 Slice 3: extraction_status exposes the current extraction lifecycle
    state.  Null means no extraction has been persisted for this document.
    Internal extraction details (method, version, text) are not exposed here.
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
    verification_state: str
    uploaded_at: datetime
    created_at: datetime
    updated_at: datetime
    extraction_status: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def model_validate(cls, obj, **kwargs):  # type: ignore[override]
        """
        Override to populate extraction_status from the related
        document_extraction relationship if present.

        This avoids changing the ORM model or response logic in the API layer.
        """
        instance = super().model_validate(obj, **kwargs)

        # Avoid triggering async lazy load (MissingGreenlet). Only read if loaded.
        if hasattr(obj, "_sa_instance_state"):
            from sqlalchemy.orm.attributes import instance_state

            state = instance_state(obj)
            if "document_extraction" in state.dict:
                extraction = state.dict["document_extraction"]
                if extraction is not None:
                    instance = instance.model_copy(
                        update={"extraction_status": extraction.extraction_status}
                    )
        return instance


# ── Update schema ──────────────────────────────────────────────────────────────


class DocumentUpdate(BaseModel):
    """Mutable metadata fields that a client may update.

    Explicitly rejects source_type, source_id, and verification_state.
    """

    display_name: Optional[str] = None
    document_type: Optional[DocumentType] = None
    document_date: Optional[date] = None
    notes: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def reject_provenance_fields(cls, data: dict) -> dict:
        _reject_provenance_fields(data)
        return data


# ── Extraction schemas ─────────────────────────────────────────────────────────

ExtractionStatus = Literal["COMPLETED", "FAILED", "UNSUPPORTED"]


class DocumentExtractionResponse(BaseModel):
    """
    Public representation of derived text content extracted from a MedicalDocument.
    """

    id: uuid.UUID
    document_id: uuid.UUID
    patient_id: uuid.UUID
    extracted_text: Optional[str] = None
    extraction_status: ExtractionStatus
    extraction_method: str
    extraction_version: str
    extracted_at: datetime
    error_message: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def validate_extraction_lifecycle(self) -> DocumentExtractionResponse:
        if self.extraction_status == "COMPLETED":
            if self.extracted_text is None or not self.extracted_text.strip():
                raise ValueError(
                    "COMPLETED extraction status requires non-empty extracted_text"
                )
        elif self.extraction_status in ("FAILED", "UNSUPPORTED"):
            if self.extracted_text is not None and self.extracted_text.strip():
                raise ValueError(
                    f"{self.extraction_status} extraction status permits "
                    "only null or empty extracted_text"
                )
        return self
