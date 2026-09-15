import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.llm import LLMProvider
from app.core.llm_gateway import get_llm_gateway
from app.db.session import get_db
from app.health.evidence_evaluator import evaluate_evidence
from app.health.inquiry_context import StructuredHealthContext, build_inquiry_context
from app.health.patient import get_or_create_patient
from app.health.query_understanding import parse_natural_language_query
from app.health.safety_guardrails import evaluate_safety
from app.schemas.inquiry import (
    HealthInquiryRequest,
    HealthInquiryResponse,
    InquiryCitation,
)
from app.schemas.provenance import VerificationState

router = APIRouter(prefix="/health-inquiry", tags=["health-inquiry"])


def get_llm_provider() -> LLMProvider:
    """Provides the configured LLM implementation via LLMGateway."""
    return get_llm_gateway()


def _build_record_map(
    context: StructuredHealthContext,
) -> dict[uuid.UUID, tuple[str, str, VerificationState]]:
    """Maps valid context record UUIDs to their entity details."""
    record_map = {}

    if context.profile and context.profile.id:
        record_map[context.profile.id] = (
            "PROFILE",
            "Health Profile",
            VerificationState.SOURCE_RECORDED,
        )

    for c in context.conditions:
        record_map[c.id] = (
            "CONDITION",
            c.name,
            getattr(c, "verification_state", VerificationState.UNCERTAIN),
        )

    for m in context.medications:
        record_map[m.id] = (
            "MEDICATION",
            m.name,
            getattr(m, "verification_state", VerificationState.UNCERTAIN),
        )

    for a in context.allergies:
        record_map[a.id] = (
            "ALLERGY",
            getattr(a, "allergen", "Unknown"),
            getattr(a, "verification_state", VerificationState.UNCERTAIN),
        )

    for s in context.symptoms:
        record_map[s.id] = (
            "SYMPTOM",
            s.name,
            getattr(s, "verification_state", VerificationState.UNCERTAIN),
        )

    for g in context.goals:
        record_map[g.id] = (
            "GOAL",
            g.title,
            getattr(g, "verification_state", VerificationState.UNCERTAIN),
        )

    return record_map


@router.post("", response_model=HealthInquiryResponse)
async def submit_health_inquiry(
    request: HealthInquiryRequest,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    llm: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> HealthInquiryResponse:
    """
    Submits a natural language query for processing against the patient's
    health records.
    """
    # 1 & 2. Authenticate and Scope Patient
    patient = await get_or_create_patient(db, current_user.id)

    # 3. Deterministic Safety Evaluation
    safety_state = evaluate_safety(request.query)

    # 4. Assembly of Structured Context
    context = await build_inquiry_context(db, patient.id)

    # 5. Query Understanding
    target = parse_natural_language_query(request.query)

    # 6. Server-Owned Evidence Evaluation
    evidence = evaluate_evidence(target, context)

    # 7. LLM Response Synthesis
    try:
        synthesis_result = await llm.synthesize_response(
            query=request.query,
            target=target,
            context=context,
            evidence=evidence,
            safety_state=safety_state,
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to synthesize response.",
        )

    # 8. Server-Side Citation Validation
    record_map = _build_record_map(context)
    verified_citations = []
    citation_id_counter = 1

    # Preserve only verified patient-owned citations. Reject foreign IDs.
    for rid in synthesis_result.cited_record_ids:
        if rid in record_map:
            entity_type, label, verif_state = record_map[rid]
            verified_citations.append(
                InquiryCitation(
                    citation_id=citation_id_counter,
                    entity_type=entity_type,
                    record_id=rid,
                    label=label,
                    verification_state=verif_state,
                )
            )
            citation_id_counter += 1

    # 9. Return Grounded Response
    return HealthInquiryResponse(
        query=request.query,
        answer=synthesis_result.answer_text,
        evidence_status=evidence.status,
        citations=verified_citations,
        safety=safety_state,
        generated_at=datetime.now(timezone.utc),
    )
