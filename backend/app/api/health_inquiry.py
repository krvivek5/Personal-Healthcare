import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.llm import LLMProvider
from app.core.llm_gateway import get_llm_gateway
from app.db.models import MedicalDocument
from app.db.session import get_db
from app.health.document_selection import select_document_evidence
from app.health.evidence_evaluator import (
    DocumentExtractionEvidence,
    EvidenceResult,
    evaluate_document_evidence,
    evaluate_evidence,
)
from app.health.inquiry_context import (
    DocumentEvidenceContext,
    StructuredHealthContext,
    build_inquiry_context,
)
from app.health.patient import get_or_create_patient
from app.health.query_understanding import parse_natural_language_query
from app.health.safety_guardrails import evaluate_safety
from app.schemas.inquiry import (
    EvidenceStatus,
    HealthInquiryRequest,
    HealthInquiryResponse,
    InquiryCitation,
)
from app.schemas.provenance import VerificationState

router = APIRouter(prefix="/health-inquiry", tags=["health-inquiry"])

DOCUMENT_DOMAINS = {"labs", "reports", "clinical_documents", "prescriptions"}


def get_llm_provider() -> LLMProvider:
    """Provides the configured LLM implementation via LLMGateway."""
    return get_llm_gateway()


def _to_extraction_evidence(doc: MedicalDocument) -> DocumentExtractionEvidence:
    extraction = doc.document_extraction
    return DocumentExtractionEvidence(
        document_id=doc.id,
        patient_id=doc.patient_id,
        extraction_status=extraction.extraction_status if extraction else "FAILED",
        extracted_text=extraction.extracted_text if extraction else None,
        document_date=doc.document_date,
    )


def _to_document_evidence_context(doc: MedicalDocument) -> DocumentEvidenceContext:
    extraction = doc.document_extraction
    excerpt = (
        extraction.extracted_text if extraction and extraction.extracted_text else ""
    )
    return DocumentEvidenceContext(
        document_id=doc.id,
        display_name=doc.display_name,
        document_type=doc.document_type,
        document_date=doc.document_date,
        extracted_excerpt=excerpt,
    )


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

    for doc in context.documents:
        label = (
            f"{doc.display_name} ({doc.document_date.isoformat()})"
            if doc.document_date
            else doc.display_name
        )
        record_map[doc.document_id] = (
            "DOCUMENT",
            label,
            VerificationState.SOURCE_RECORDED,
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
    target_domain = (
        target.target_domain.lower() if target and target.target_domain else ""
    )
    if not safety_state.triggered and target_domain in DOCUMENT_DOMAINS:
        selected_docs = await select_document_evidence(db, patient.id, target)
        if not selected_docs:
            evidence = EvidenceResult(
                status=EvidenceStatus.INSUFFICIENT,
                evidence_directive=(
                    "No completed matching document evidence was available "
                    "to answer this inquiry."
                ),
            )
            context.documents = []
        elif len(selected_docs) == 1:
            winning_doc = selected_docs[0]
            evidence = evaluate_document_evidence(
                target, _to_extraction_evidence(winning_doc), patient.id
            )
            context.documents = [_to_document_evidence_context(winning_doc)]
        else:
            # Top-K=2 candidate evaluation and deterministic tie-breaking
            ev0 = evaluate_document_evidence(
                target, _to_extraction_evidence(selected_docs[0]), patient.id
            )
            if ev0.status == EvidenceStatus.SUFFICIENT:
                # both SUFFICIENT (prefers newest) OR only ev0 SUFFICIENT
                evidence = ev0
                winning_doc = selected_docs[0]
            else:
                ev1 = evaluate_document_evidence(
                    target, _to_extraction_evidence(selected_docs[1]), patient.id
                )
                if ev1.status == EvidenceStatus.SUFFICIENT:
                    # only ev1 SUFFICIENT
                    evidence = ev1
                    winning_doc = selected_docs[1]
                elif ev0.status == EvidenceStatus.PARTIALLY_SUFFICIENT:
                    # both PARTIALLY_SUFFICIENT (prefers newest) OR only ev0 PARTIAL
                    evidence = ev0
                    winning_doc = selected_docs[0]
                elif ev1.status == EvidenceStatus.PARTIALLY_SUFFICIENT:
                    # only ev1 PARTIAL
                    evidence = ev1
                    winning_doc = selected_docs[1]
                else:
                    # both INSUFFICIENT (prefers newest)
                    evidence = ev0
                    winning_doc = selected_docs[0]

            context.documents = [_to_document_evidence_context(winning_doc)]
    else:
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
