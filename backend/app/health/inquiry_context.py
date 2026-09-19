import uuid
from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.health.allergies import get_allergies
from app.health.conditions import get_conditions
from app.health.goals import get_goals
from app.health.medications import get_medications
from app.health.profile import get_health_profile
from app.health.symptoms import get_symptoms
from app.health.timeline import get_timeline
from app.schemas.allergy import AllergyResponse
from app.schemas.condition import ConditionResponse
from app.schemas.goal import GoalResponse
from app.schemas.health_profile import HealthProfileResponse
from app.schemas.medication import MedicationResponse
from app.schemas.symptom import SymptomResponse
from app.schemas.timeline import HealthEvent


class DocumentEvidenceContext(BaseModel):
    """
    Lightweight, non-ORM representation of selected document evidence.
    Used for safe serialization into the inquiry context.
    """

    document_id: uuid.UUID
    display_name: str
    document_type: str
    document_date: Optional[date] = None
    extracted_excerpt: str


class PassageEvidenceContext(BaseModel):
    """Lightweight, non-ORM representation of a qualified retrieved passage.

    Mirrors the fields from ``RetrievedPassage`` (M4 S4) that are safe for
    LLM-layer propagation.  ``patient_id`` is intentionally excluded — it
    must not be serialized into any LLM payload or prompt block.

    Callers are responsible for populating this from a ``RetrievedPassage``
    after tenant isolation has been verified by ``evaluate_passage_evidence``.
    Only qualified passages (those corroborating at least one requested
    attribute or topical entity) should be placed here.
    """

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    page_number: Optional[int] = None
    chunk_text: str
    display_name: str
    document_type: str
    document_date: Optional[date] = None
    cosine_distance: float
    similarity: float

    model_config = ConfigDict(from_attributes=True)


class StructuredHealthContext(BaseModel):
    """
    Canonical in-memory context representation required by M1.
    Contains only the authenticated patient's records with fields required by M1 design,
    including record IDs and data-faithful temporal representations.
    It contains no LLM-generated information or MedicalDocument file contents.
    (M3 extension: optionally contains deterministically selected document excerpts)
    """

    profile: Optional[HealthProfileResponse] = None
    conditions: list[ConditionResponse] = Field(default_factory=list)
    medications: list[MedicationResponse] = Field(default_factory=list)
    allergies: list[AllergyResponse] = Field(default_factory=list)
    symptoms: list[SymptomResponse] = Field(default_factory=list)
    goals: list[GoalResponse] = Field(default_factory=list)
    recent_timeline_events: list[HealthEvent] = Field(default_factory=list)
    documents: list[DocumentEvidenceContext] = Field(default_factory=list)
    # M4 S5: qualified retrieved passages from HybridRetrievalEngine.
    # Only pre-qualified passages (corroborating at least one attribute or
    # entity) are placed here after evaluate_passage_evidence runs.
    # Empty by default; populated by the S6 orchestrator when domain is
    # document-based (labs / reports / prescriptions / clinical_documents).
    passages: list[PassageEvidenceContext] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


async def build_inquiry_context(
    db: AsyncSession, patient_id: uuid.UUID
) -> StructuredHealthContext:
    """
    Creates a backend service that takes an authenticated patient_id,
    reads the existing Phase 1 structured health data,
    and produces the canonical in-memory context representation.
    """
    # 1. Fetch Profile
    profile_db = await get_health_profile(db, patient_id)
    profile = HealthProfileResponse.model_validate(profile_db) if profile_db else None

    # 2. Fetch Conditions
    conditions_db = await get_conditions(db, patient_id)
    conditions = [ConditionResponse.model_validate(c) for c in conditions_db]

    # 3. Fetch Medications
    medications_db = await get_medications(db, patient_id)
    medications = [MedicationResponse.model_validate(m) for m in medications_db]

    # 4. Fetch Allergies
    allergies_db = await get_allergies(db, patient_id)
    allergies = [AllergyResponse.model_validate(a) for a in allergies_db]

    # 5. Fetch Symptoms
    symptoms_db = await get_symptoms(db, patient_id)
    symptoms = [SymptomResponse.model_validate(s) for s in symptoms_db]

    # 6. Fetch Goals
    goals_db = await get_goals(db, patient_id)
    goals = [GoalResponse.model_validate(g) for g in goals_db]

    # 7. Fetch Timeline
    timeline_events = await get_timeline(db, patient_id)

    return StructuredHealthContext(
        profile=profile,
        conditions=conditions,
        medications=medications,
        allergies=allergies,
        symptoms=symptoms,
        goals=goals,
        recent_timeline_events=timeline_events,
    )
