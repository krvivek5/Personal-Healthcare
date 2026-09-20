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

    M4 S6 routing:
      - Document domains (labs / reports / prescriptions / clinical_documents):
        S4 retrieval → S5 passage evidence evaluation → LLM synthesis.
      - Structured domains (conditions / medications / allergies / …):
        Existing M3 relational evidence evaluation path (unchanged).
    """
    # 1 & 2. Authenticate and Scope Patient
    patient = await get_or_create_patient(db, current_user.id)

    # 3. Deterministic Safety Evaluation — short-circuit before any DB work.
    safety_state = evaluate_safety(request.query)

    # 4. Assembly of Structured Context
    context = await build_inquiry_context(db, patient.id)

    # S4 retrieval_document_passages strictly requires the session to not be in an open
    # transaction. The prior DB reads implicitly started a transaction, so we commit
    # it here.
    await db.commit()

    # 5. Query Understanding
    target = parse_natural_language_query(request.query)

    # 6. Server-Owned Evidence Evaluation
    target_domain = (
        target.target_domain.lower() if target and target.target_domain else ""
    )

    # Initialise sanitized_context to None; built after passage population.
    sanitized_context = None

    if not safety_state.triggered and target_domain in DOCUMENT_DOMAINS:
        # ---------------------------------------------------------------
        # M4 passage-based path (S4 retrieval → S5 qualification → S6)
        # ---------------------------------------------------------------
        try:
            retrieval_result = await retrieve_document_passages(
                db=db,
                patient_id=patient.id,
                query_text=request.query,
                target_domains=[target_domain],
            )
        except (RetrievalProviderError, RetrievalDatabaseError) as exc:
            logger.error("Retrieval failure for patient %s: %s", patient.id, exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve document evidence.",
            )

        # S5 qualification — S6 must NOT re-run _keyword_present.
        evidence = evaluate_passage_evidence(target, retrieval_result, patient.id)

        # Map S5-qualified passages directly into context without re-filtering.
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

        # Build sanitized context (includes passage_map for citation enrichment).
        sanitized_context = build_sanitized_context(context, target)

    else:
        # ---------------------------------------------------------------
        # M3 structured relational path (unchanged)
        # ---------------------------------------------------------------
        evidence = evaluate_evidence(target, context)

    # 7. Short-circuit: insufficient evidence — no LLM call.
    if evidence.status == EvidenceStatus.INSUFFICIENT and not safety_state.triggered:
        return HealthInquiryResponse(
            query=request.query,
            answer=evidence.evidence_directive,
            evidence_status=evidence.status,
            citations=[],
            safety=safety_state,
            generated_at=datetime.now(timezone.utc),
        )

    # 8. LLM Response Synthesis — safety short-circuit is handled by LLMGateway.
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

    # Validate length invariant before iterating.
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
        # For passage-backed citations, deduplicate by token:
        if token:
            if token in seen_tokens:
                continue
            seen_tokens.add(token)
        else:
            # For structured-domain citations without tokens, deduplicate by record_id:
            if rid in seen_structured_ids:
                continue
            seen_structured_ids.add(rid)

        # Reject foreign / hallucinated UUIDs.
        if rid not in record_map:
            continue

        entity_type, label, verif_state = record_map[rid]

        # M4 passage enrichment: look up chunk-level metadata via passage_map.
        chunk_id: uuid.UUID | None = None
        page_number: int | None = None
        passage_text: str | None = None

        if sanitized_context and token:
            provenance = sanitized_context.passage_map.get(token)
            if provenance is not None:
                chunk_id = provenance.chunk_id
                page_number = provenance.page_number
                passage_text = provenance.passage_text
            # If token is valid but absent from passage_map: no passage enrichment
            # (chunk_id / page_number / passage_text remain None).

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
    )
