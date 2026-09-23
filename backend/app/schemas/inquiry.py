from datetime import date, datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.provenance import VerificationState


class EvidenceStatus(str, Enum):
    """Status indicating if backend holds sufficient evidence to satisfy the inquiry."""

    SUFFICIENT = "SUFFICIENT"
    PARTIALLY_SUFFICIENT = "PARTIALLY_SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"


# Supported domain constants
STRUCTURED_DOMAINS = {
    "conditions",
    "medications",
    "allergies",
    "symptoms",
    "goals",
    "profile",
}
DOCUMENT_DOMAINS = {"labs", "reports", "prescriptions", "clinical_documents"}


class RoutingMode(str, Enum):
    """Execution strategy determined by query understanding."""

    STRUCTURED_ONLY = "STRUCTURED_ONLY"  # Targets only structured relational tables
    DOCUMENT_ONLY = "DOCUMENT_ONLY"  # Targets only document chunk vector retrieval
    CROSS_DOMAIN = "CROSS_DOMAIN"  # Targets both structured records and document chunks
    AMBIGUOUS_CLARIFY = (
        "AMBIGUOUS_CLARIFY"  # Query lacks semantic anchor; prompt user for clarity
    )
    UNROUTABLE = (
        "UNROUTABLE"  # Non-medical query; cannot be mapped to any health domain
    )


class TemporalScope(str, Enum):
    """Categorical temporal scope."""

    ALL = "all"
    CURRENT = "current"
    HISTORICAL = "historical"
    INTERVAL = "interval"


class TemporalConstraint(BaseModel):
    """Detailed temporal boundaries extracted from the natural language query."""

    scope: TemporalScope = TemporalScope.ALL
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    anchor_year: Optional[int] = None
    raw_expression: Optional[str] = None


class InquiryTarget(BaseModel):
    """Evolutionary normalized representation of a user's health inquiry."""

    candidate_structured_domains: list[str] = Field(default_factory=list)
    candidate_document_domains: list[str] = Field(default_factory=list)
    target_entity: Optional[str] = None
    requested_attributes: list[str] = Field(default_factory=list)
    temporal_constraint: TemporalConstraint = Field(default_factory=TemporalConstraint)
    routing_mode: RoutingMode = RoutingMode.UNROUTABLE
    clarification_required: bool = False
    clarification_prompt: Optional[str] = None
    question_intent: str = "QUERY"

    # -----------------------------------------------------------------------
    # Legacy Constructor Adapter (Backward Compatibility with M1–M4 tests)
    # -----------------------------------------------------------------------
    @model_validator(mode="before")
    @classmethod
    def _handle_legacy_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # If legacy target_domain was passed in kwargs:
            td = data.pop("target_domain", None)
            if td is not None:
                if (
                    "candidate_structured_domains" not in data
                    and "candidate_document_domains" not in data
                ):
                    if td in STRUCTURED_DOMAINS:
                        data["candidate_structured_domains"] = [td]
                        data.setdefault("routing_mode", RoutingMode.STRUCTURED_ONLY)
                    elif td in DOCUMENT_DOMAINS:
                        data["candidate_document_domains"] = [td]
                        data.setdefault("routing_mode", RoutingMode.DOCUMENT_ONLY)
                    else:
                        data["candidate_structured_domains"] = [td]
                        data.setdefault("routing_mode", RoutingMode.STRUCTURED_ONLY)

            # If legacy temporal_scope was passed in kwargs:
            ts = data.pop("temporal_scope", None)
            if ts is not None and "temporal_constraint" not in data:
                try:
                    scope_val = TemporalScope(ts)
                except ValueError:
                    scope_val = TemporalScope.ALL
                data["temporal_constraint"] = {"scope": scope_val}
        return data

    # -----------------------------------------------------------------------
    # Transitional Backward-Compatibility Accessors
    # -----------------------------------------------------------------------
    @property
    def target_domain(self) -> Optional[str]:
        """Transitional backward-compatibility accessor.

        Preserves legacy M1–M4 tests that assert target.target_domain.
        Returns candidate_structured_domains[0] first if present (preserving
        M1/M2 structured precedence), else candidate_document_domains[0], else None.

        CRITICAL: M5 routing logic must NEVER use this accessor for primary
        routing decisions, and must NEVER allow it to collapse multi-domain
        candidate sets.
        """
        if self.candidate_structured_domains:
            return self.candidate_structured_domains[0]
        if self.candidate_document_domains:
            return self.candidate_document_domains[0]
        return None

    @property
    def temporal_scope(self) -> str:
        """Transitional backward-compatibility accessor for temporal scope."""
        return self.temporal_constraint.scope.value


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
    clarification_required: bool = False
