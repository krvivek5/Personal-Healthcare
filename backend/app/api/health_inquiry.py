import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.llm import LLMProvider
from app.core.llm_gateway import get_llm_gateway
from app.db.session import get_db
from app.health.evidence_evaluator import (
    evaluate_evidence,
    evaluate_passage_evidence,
)
from app.health.inquiry_context import (
    PassageEvidenceContext,
    StructuredHealthContext,
    build_inquiry_context,
)
from app.health.patient import get_or_create_patient
from app.health.query_understanding import parse_natural_language_query
from app.health.retrieval import (
    RetrievalDatabaseError,
    RetrievalProviderError,
    retrieve_document_passages,
)
from app.health.safety_guardrails import evaluate_safety
from app.health.sanitized_context import build_sanitized_context
from app.schemas.inquiry import (
    EvidenceStatus,
    HealthInquiryRequest,
    HealthInquiryResponse,
    InquiryCitation,
)
from app.schemas.provenance import VerificationState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health-inquiry", tags=["health-inquiry"])

DOCUMENT_DOMAINS = {"labs", "reports", "clinical_documents", "prescriptions"}


def get_llm_provider() -> LLMProvider:
    """Provides the configured LLM implementation via LLMGateway."""
    return get_llm_gateway()


def _build_record_map(
    context: StructuredHealthContext,
) -> dict[uuid.UUID, tuple[str, str, VerificationState]]:
    """Maps valid context record UUIDs to their entity details.

    M4 S6 extension: also covers context.passages, mapping each passage's
    canonical MedicalDocument.id to a DOCUMENT label for citation assembly.
    Passage entries use SOURCE_RECORDED verification state matching M3 docs.
    """
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

    # M3: whole-document evidence contexts
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

    # M4 S6: passage evidence contexts — keyed by document_id (canonical).
    # Multiple passages from the same document share one record_map entry;
    # passage-level detail is resolved later via passage_map.
    for pec in context.passages:
        if pec.document_id not in record_map:
            label = (
                f"{pec.display_name} ({pec.document_date.isoformat()})"
                if pec.document_date
                else pec.display_name
            )
            record_map[pec.document_id] = (
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

    M5 S2 routing:
      1. evaluate_safety
      2. parse_natural_language_query (Ambiguous/Unroutable short-circuits)
      3. get_or_create_patient
      4. route by target.routing_mode (DOCUMENT_ONLY vs STRUCTURED_ONLY / CROSS_DOMAIN)
    """
    # 1. Deterministic Safety Evaluation — short-circuit before any DB work.
    safety_state = evaluate_safety(request.query)
    if safety_state.triggered:
        return HealthInquiryResponse(
            query=request.query,
            answer=safety_state.advisory_message or "SAFETY_ADVISORY",
            evidence_status=EvidenceStatus.INSUFFICIENT,
            citations=[],
            safety=safety_state,
            generated_at=datetime.now(timezone.utc),
            clarification_required=False,
        )

    # 2. Query Understanding & Ambiguity/Unroutable Short-Circuits
    from app.schemas.inquiry import RoutingMode

    target = parse_natural_language_query(request.query)

    if target.routing_mode == RoutingMode.AMBIGUOUS_CLARIFY:
        return HealthInquiryResponse(
            query=request.query,
            answer=target.clarification_prompt or "Please clarify your request.",
            evidence_status=EvidenceStatus.INSUFFICIENT,
            citations=[],
            safety=safety_state,
            generated_at=datetime.now(timezone.utc),
            clarification_required=True,
        )

    if target.routing_mode == RoutingMode.UNROUTABLE:
        return HealthInquiryResponse(
            query=request.query,
            answer="Your query could not be matched to medical records.",
            evidence_status=EvidenceStatus.INSUFFICIENT,
            citations=[],
            safety=safety_state,
            generated_at=datetime.now(timezone.utc),
            clarification_required=False,
        )

    # 3. Authenticate and Scope Patient
    patient = await get_or_create_patient(db, current_user.id)

    sanitized_context = None

    # 4 & 5 & 6. Route using target.routing_mode
    if target.routing_mode == RoutingMode.DOCUMENT_ONLY:
        # ---------------------------------------------------------------
        # DOCUMENT_ONLY path
        # ---------------------------------------------------------------
        # Instantiate empty context
        context = StructuredHealthContext()
        # Close read transaction before vector engine begins
        await db.commit()

        try:
            retrieval_result = await retrieve_document_passages(
                db=db,
                patient_id=patient.id,
                query_text=request.query,
                target_domains=target.candidate_document_domains,
            )
        except (RetrievalProviderError, RetrievalDatabaseError) as exc:
            logger.error("Retrieval failure for patient %s: %s", patient.id, exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve document evidence.",
            )

        evidence = evaluate_passage_evidence(target, retrieval_result, patient.id)

        if evidence.qualified_passages:
            context.passages = [
                PassageEvidenceContext(
                    chunk_id=p.chunk_id,
                    document_id=p.document_id,
                    chunk_index=p.chunk_index,
                    page_number=p.page_number,
                    chunk_text=p.chunk_text,
                    display_name=p.document_display_name,
                    document_type=p.document_type,
                    document_date=p.document_date,
                    cosine_distance=p.cosine_distance,
                    similarity=p.similarity,
                )
                for p in evidence.qualified_passages
            ]

        sanitized_context = build_sanitized_context(context, target)

    elif target.routing_mode == RoutingMode.CROSS_DOMAIN:
        # ---------------------------------------------------------------
        # CROSS_DOMAIN
        # ---------------------------------------------------------------
        from app.health.evidence_fusion import fuse_cross_domain_evidence

        try:
            context = await build_inquiry_context(
                db,
                patient.id,
                domains=(
                    target.candidate_structured_domains
                    if target.candidate_structured_domains
                    else None
                ),
            )
            await db.commit()
        except Exception as exc:
            logger.error(
                "Structured retrieval failure for patient %s: %s", patient.id, exc
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve structured evidence.",
            )

        try:
            retrieval_result = await retrieve_document_passages(
                db=db,
                patient_id=patient.id,
                query_text=request.query,
                target_domains=target.candidate_document_domains,
            )
        except (RetrievalProviderError, RetrievalDatabaseError) as exc:
            logger.error(
                "Document retrieval failure for patient %s: %s", patient.id, exc
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve document evidence.",
            )

        struct_evidence = evaluate_evidence(target, context)
        doc_evidence = evaluate_passage_evidence(target, retrieval_result, patient.id)

        evidence = fuse_cross_domain_evidence(target, struct_evidence, doc_evidence)

        if (
            evidence.status != EvidenceStatus.INSUFFICIENT
            and evidence.qualified_passages
        ):
            context.passages = [
                PassageEvidenceContext(
                    chunk_id=p.chunk_id,
                    document_id=p.document_id,
                    chunk_index=p.chunk_index,
                    page_number=p.page_number,
                    chunk_text=p.chunk_text,
                    display_name=p.document_display_name,
                    document_type=p.document_type,
                    document_date=p.document_date,
                    cosine_distance=p.cosine_distance,
                    similarity=p.similarity,
                )
                for p in evidence.qualified_passages
            ]

        if evidence.status != EvidenceStatus.INSUFFICIENT:
            sanitized_context = build_sanitized_context(context, target)

    else:
        # ---------------------------------------------------------------
        # STRUCTURED_ONLY
        # ---------------------------------------------------------------
        try:
            context = await build_inquiry_context(
                db,
                patient.id,
                domains=(
                    target.candidate_structured_domains
                    if target.candidate_structured_domains
                    else None
                ),
            )
            await db.commit()
        except Exception as exc:
            logger.error(
                "Structured retrieval failure for patient %s: %s", patient.id, exc
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve structured evidence.",
            )

        evidence = evaluate_evidence(target, context)

    # 7. Short-circuit: insufficient evidence — no LLM call.
    if evidence.status == EvidenceStatus.INSUFFICIENT:
        return HealthInquiryResponse(
            query=request.query,
            answer=evidence.evidence_directive,
            evidence_status=evidence.status,
            citations=[],
            safety=safety_state,
            generated_at=datetime.now(timezone.utc),
            clarification_required=False,
        )

    # 8. LLM Response Synthesis
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

    # 9. Server-Side Citation Validation & Enrichment
    record_map = _build_record_map(context)
    verified_citations: list[InquiryCitation] = []
    citation_id_counter = 1

    if len(synthesis_result.cited_tokens) != len(synthesis_result.cited_record_ids):
        logger.error(
            "cited_tokens / cited_record_ids length mismatch (%d vs %d) — "
            "failing closed, emitting zero citations.",
            len(synthesis_result.cited_tokens),
            len(synthesis_result.cited_record_ids),
        )
        synthesis_result = synthesis_result.model_copy(
            update={"cited_record_ids": [], "cited_tokens": []}
        )

    seen_tokens: set[str] = set()
    seen_structured_ids: set[uuid.UUID] = set()

    for rid, token in zip(
        synthesis_result.cited_record_ids, synthesis_result.cited_tokens
    ):
        if token:
            if token in seen_tokens:
                continue
            seen_tokens.add(token)
        else:
            if rid in seen_structured_ids:
                continue
            seen_structured_ids.add(rid)

        if rid not in record_map:
            continue

        entity_type, label, verif_state = record_map[rid]

        chunk_id: uuid.UUID | None = None
        page_number: int | None = None
        passage_text: str | None = None

        if sanitized_context and token:
            provenance = sanitized_context.passage_map.get(token)
            if provenance is not None:
                chunk_id = provenance.chunk_id
                page_number = provenance.page_number
                passage_text = provenance.passage_text

        verified_citations.append(
            InquiryCitation(
                citation_id=citation_id_counter,
                entity_type=entity_type,
                record_id=rid,
                label=label,
                verification_state=verif_state,
                chunk_id=chunk_id,
                page_number=page_number,
                passage_text=passage_text,
            )
        )
        citation_id_counter += 1

    # 10. Return Grounded Response
    return HealthInquiryResponse(
        query=request.query,
        answer=synthesis_result.answer_text,
        evidence_status=evidence.status,
        citations=verified_citations,
        safety=safety_state,
        generated_at=datetime.now(timezone.utc),
        clarification_required=False,
    )
