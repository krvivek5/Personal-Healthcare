from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.provenance import VerificationState


class EvidenceStatus(str, Enum):
    """Status indicating if backend holds sufficient evidence to satisfy the inquiry."""

    SUFFICIENT = "SUFFICIENT"
    PARTIALLY_SUFFICIENT = "PARTIALLY_SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"


class InquiryTarget(BaseModel):
    """The normalized representation of a user's health question
    for backend evaluation.
    """

    target_domain: Optional[str] = None
    target_entity: Optional[str] = None
    requested_attributes: list[str] = Field(default_factory=list)
    temporal_scope: str = "all"
    question_intent: str = "QUERY"


class InquiryCitation(BaseModel):
    """A verified citation pointing to a structured record in the user's data.

    M3 fields (citation_id, entity_type, record_id, label, verification_state)
    are always present.

    M4 S6 fields (chunk_id, page_number, passage_text) are present only when
    the citation originates from a passage-level retrieval.  They are Optional
    with None defaults to preserve full backward compatibility.
    """

    citation_id: int
    entity_type: str
    record_id: UUID
    label: str
    verification_state: VerificationState
    # M4 S6: passage-level provenance — absent for structured-domain citations.
    chunk_id: Optional[UUID] = None
    page_number: Optional[int] = None
    passage_text: Optional[str] = None


class SafetyGuardrailState(BaseModel):
    """Safety state to trigger non-diagnostic advisories on acute symptoms."""

    triggered: bool
    advisory_message: Optional[str] = None


class HealthInquiryRequest(BaseModel):
    """Client request to submit a personal health question."""

    query: str = Field(
        ...,
        min_length=2,
        max_length=1000,
        description="The user's natural language health question.",
    )

    @field_validator("query")
    @classmethod
    def query_must_not_be_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Query cannot be empty or whitespace only")
        return v


class HealthInquiryResponse(BaseModel):
    """The structured response containing grounded answer and verified provenance."""

    query: str
    answer: str
    evidence_status: EvidenceStatus
    citations: list[InquiryCitation]
    safety: SafetyGuardrailState
    generated_at: datetime
