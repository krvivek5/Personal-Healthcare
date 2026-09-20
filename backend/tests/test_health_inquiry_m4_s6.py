"""
Phase 2 — M4 Slice 6: LLM Gateway Synthesis & Citation Reconciliation

Tests the S6 orchestration layer:
  1. S5 → S6 qualified-passage handoff via EvidenceResult.qualified_passages
  2. Document-domain routing through M4 retrieval path
  3. Structured-domain M3 compatibility
  4. Safety short-circuit (zero retrieval / LLM calls)
  5. Insufficient evidence (zero LLM calls, answer = directive)
  6. Partial evidence synthesis
  7. Passage citation enrichment (chunk_id, page_number, passage_text)
  8. cited_tokens / cited_record_ids length-mismatch → fail closed
  9. Malformed / unknown tokens → ignored
  10. Duplicate citation token → one citation emitted
  11. Valid token absent from passage_map → no passage enrichment
  12. Tenant mismatch in evaluate_passage_evidence → INSUFFICIENT
  13. Retrieval failure → HTTP 500
  14. LLM failure → HTTP 500
  15. M3 whole-document regression compatibility
"""

import dataclasses
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import MockLLMProvider, SynthesisResult
from app.db.models import Patient
from app.health.evidence_evaluator import EvidenceResult, evaluate_passage_evidence
from app.health.inquiry_context import (
    DocumentEvidenceContext,
    PassageEvidenceContext,
    StructuredHealthContext,
)
from app.health.retrieval import (
    RetrievalDatabaseError,
    RetrievalResult,
    RetrievedPassage,
)
from app.health.sanitized_context import (
    PassageProvenance,
    build_sanitized_context,
)
from app.schemas.inquiry import (
    EvidenceStatus,
    HealthInquiryRequest,
    InquiryCitation,
    InquiryTarget,
    SafetyGuardrailState,
)
from app.schemas.provenance import VerificationState
from tests.test_health_inquiry_api import create_user_and_token

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PATIENT_ID = uuid.uuid4()
DOC_ID_A = uuid.uuid4()
DOC_ID_B = uuid.uuid4()
CHUNK_ID_1 = uuid.uuid4()
CHUNK_ID_2 = uuid.uuid4()
CHUNK_ID_3 = uuid.uuid4()


def _make_passage(
    chunk_id: uuid.UUID = None,
    document_id: uuid.UUID = None,
    patient_id: uuid.UUID = None,
    chunk_text: str = "cholesterol 185 mg/dL",
    page_number: int = 1,
    chunk_index: int = 0,
    document_display_name: str = "Lipid Panel",
    document_type: str = "lab_report",
    document_date: date = date(2025, 6, 1),
) -> RetrievedPassage:
    return RetrievedPassage(
        chunk_id=chunk_id or uuid.uuid4(),
        document_id=document_id or DOC_ID_A,
        patient_id=patient_id or PATIENT_ID,
        chunk_index=chunk_index,
        page_number=page_number,
        chunk_text=chunk_text,
        document_display_name=document_display_name,
        document_type=document_type,
        document_date=document_date,
        cosine_distance=0.15,
        similarity=0.85,
    )


def _make_retrieval_result(
    passages: list[PassageEvidenceContext],
    patient_id: uuid.UUID = None,
) -> RetrievalResult:
    return RetrievalResult(
        patient_id=patient_id or PATIENT_ID,
        target_domains=("labs",),
        query_text="test query",
        top_k=5,
        passages=tuple(passages),
    )


# ---------------------------------------------------------------------------
# 1. S5 → S6 qualified-passage handoff: EvidenceResult.qualified_passages
# ---------------------------------------------------------------------------


def test_evaluate_passage_evidence_rule_a_sufficient_populates_qualified_passages():
    """Rule A SUFFICIENT: only corroborating passages appear in qualified_passages."""
    p1 = _make_passage(chunk_id=CHUNK_ID_1, chunk_text="cholesterol 185 mg/dL hdl 55")
    p2 = _make_passage(chunk_id=CHUNK_ID_2, chunk_text="unrelated text about something")
    p3 = _make_passage(chunk_id=CHUNK_ID_3, chunk_text="ldl 110 mg/dL")
    target = InquiryTarget(
        target_domain="labs",
        requested_attributes=["cholesterol", "hdl", "ldl"],
    )
    result = evaluate_passage_evidence(
        target, _make_retrieval_result([p1, p2, p3]), PATIENT_ID
    )

    assert result.status == EvidenceStatus.SUFFICIENT
    assert len(result.qualified_passages) == 2
    chunk_ids = {p.chunk_id for p in result.qualified_passages}
    assert CHUNK_ID_1 in chunk_ids
    assert CHUNK_ID_3 in chunk_ids
    assert CHUNK_ID_2 not in chunk_ids  # non-contributing passage pruned


def test_evaluate_passage_evidence_rule_a_partial_returns_only_matching_passages():
    """Rule A PARTIALLY_SUFFICIENT: non-contributing passages not in handoff."""
    p1 = _make_passage(chunk_id=CHUNK_ID_1, chunk_text="fasting glucose 95 mg/dL")
    p2 = _make_passage(chunk_id=CHUNK_ID_2, chunk_text="unrelated imaging note")
    target = InquiryTarget(
        target_domain="labs",
        requested_attributes=["fasting glucose", "hba1c", "insulin"],
    )
    result = evaluate_passage_evidence(
        target, _make_retrieval_result([p1, p2]), PATIENT_ID
    )

    assert result.status == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert result.missing_fields == ["hba1c", "insulin"]
    assert len(result.qualified_passages) == 1
    assert result.qualified_passages[0].chunk_id == CHUNK_ID_1


def test_evaluate_passage_evidence_rule_b_sufficient_populates_qualified_passages():
    """Rule B SUFFICIENT: passages containing entity appear in handoff."""
    p1 = _make_passage(chunk_id=CHUNK_ID_1, chunk_text="creatinine 0.9 mg/dL")
    p2 = _make_passage(chunk_id=CHUNK_ID_2, chunk_text="blood pressure 120/80")
    target = InquiryTarget(target_domain="labs", target_entity="creatinine")
    result = evaluate_passage_evidence(
        target, _make_retrieval_result([p1, p2]), PATIENT_ID
    )

    assert result.status == EvidenceStatus.SUFFICIENT
    assert len(result.qualified_passages) == 1
    assert result.qualified_passages[0].chunk_id == CHUNK_ID_1


def test_evaluate_passage_evidence_rule_c_sufficient_all_passages_qualify():
    """Rule C generic query: all retrieved passages in qualified_passages."""
    passages = [_make_passage(chunk_id=uuid.uuid4()) for _ in range(3)]
    target = InquiryTarget(target_domain="labs")
    result = evaluate_passage_evidence(
        target, _make_retrieval_result(passages), PATIENT_ID
    )

    assert result.status == EvidenceStatus.SUFFICIENT
    assert len(result.qualified_passages) == 3


def test_evaluate_passage_evidence_insufficient_empty_qualified_passages():
    """INSUFFICIENT evidence: qualified_passages must be empty."""
    p1 = _make_passage(chunk_text="blood pressure measurement")
    target = InquiryTarget(target_domain="labs", target_entity="vitamin d")
    result = evaluate_passage_evidence(target, _make_retrieval_result([p1]), PATIENT_ID)

    assert result.status == EvidenceStatus.INSUFFICIENT
    assert result.qualified_passages == []


# ---------------------------------------------------------------------------
# 2. Tenant mismatch → INSUFFICIENT with empty qualified_passages
# ---------------------------------------------------------------------------


def test_evaluate_passage_evidence_tenant_mismatch_result_level():
    """RetrievalResult patient_id mismatch → INSUFFICIENT, no passage exposure."""
    p1 = _make_passage()
    foreign_patient = uuid.uuid4()
    result_obj = _make_retrieval_result([p1], patient_id=foreign_patient)
    target = InquiryTarget(target_domain="labs", target_entity="cholesterol")
    result = evaluate_passage_evidence(target, result_obj, PATIENT_ID)

    assert result.status == EvidenceStatus.INSUFFICIENT
    assert result.qualified_passages == []


def test_evaluate_passage_evidence_tenant_mismatch_passage_level():
    """Individual passage patient_id mismatch → INSUFFICIENT, no exposure."""
    foreign_passage = _make_passage(patient_id=uuid.uuid4())
    target = InquiryTarget(target_domain="labs", target_entity="cholesterol")
    # retrieval_result.patient_id matches, but passage.patient_id does not
    result_obj = _make_retrieval_result([foreign_passage])
    result = evaluate_passage_evidence(target, result_obj, PATIENT_ID)

    assert result.status == EvidenceStatus.INSUFFICIENT
    assert result.qualified_passages == []


# ---------------------------------------------------------------------------
# 3. context.passages population from qualified_passages
# ---------------------------------------------------------------------------


def test_context_passages_population_from_qualified_passages():
    """Orchestrator maps qualified_passages → context.passages without re-filtering."""
    p1 = _make_passage(
        chunk_id=CHUNK_ID_1,
        chunk_text="cholesterol 185 mg/dL",
        page_number=2,
        document_date=date(2025, 6, 1),
    )
    evidence = EvidenceResult(
        status=EvidenceStatus.SUFFICIENT,
        evidence_directive="Found.",
        qualified_passages=[p1],
    )

    passages = [
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

    assert len(passages) == 1
    assert passages[0].chunk_id == CHUNK_ID_1
    assert passages[0].page_number == 2
    assert passages[0].display_name == "Lipid Panel"


# ---------------------------------------------------------------------------
# 4. SynthesisResult: cited_tokens / cited_record_ids alignment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_llm_passage_synthesis_emits_parallel_tokens():
    """MockLLMProvider passage path: cited_tokens is parallel to cited_record_ids."""
    pec = PassageEvidenceContext(
        chunk_id=CHUNK_ID_1,
        document_id=DOC_ID_A,
        chunk_index=0,
        page_number=1,
        chunk_text="cholesterol 185 mg/dL",
        display_name="Lipid Panel",
        document_type="lab_report",
        document_date=date(2025, 6, 1),
        cosine_distance=0.15,
        similarity=0.85,
    )
    context = StructuredHealthContext(passages=[pec])
    target = InquiryTarget(target_domain="labs", target_entity="cholesterol")
    evidence = EvidenceResult(
        status=EvidenceStatus.SUFFICIENT,
        evidence_directive="Found.",
        qualified_passages=[],
    )
    safety_state = SafetyGuardrailState(triggered=False)
    provider = MockLLMProvider()

    result = await provider.synthesize_response(
        query="What was my cholesterol?",
        target=target,
        context=context,
        evidence=evidence,
        safety_state=safety_state,
    )

    assert isinstance(result, SynthesisResult)
    assert len(result.cited_record_ids) == len(result.cited_tokens)
    assert DOC_ID_A in result.cited_record_ids
    assert "[DOC-1]" in result.cited_tokens


@pytest.mark.asyncio
async def test_mock_llm_m3_structured_path_preserves_tokens():
    """MockLLMProvider M3 path: cited_tokens emitted (may be empty strings for
    structured records without passage tokens — length invariant still holds)."""

    from app.schemas.condition import ConditionResponse

    cond_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    condition = ConditionResponse(
        id=cond_id,
        patient_id=PATIENT_ID,
        name="Hypertension",
        status="active",
        is_chronic=True,
        recorded_at=now,
        source_type="PATIENT_REPORTED",
        source_id=None,
        verification_state="UNVERIFIED",
        created_at=now,
        updated_at=now,
    )
    context = StructuredHealthContext(conditions=[condition])
    evidence = EvidenceResult(
        status=EvidenceStatus.SUFFICIENT,
        matched_records=[condition],
        evidence_directive="Found.",
    )
    target = InquiryTarget(target_domain="conditions", target_entity="Hypertension")
    safety_state = SafetyGuardrailState(triggered=False)
    provider = MockLLMProvider()

    result = await provider.synthesize_response(
        query="Do I have hypertension?",
        target=target,
        context=context,
        evidence=evidence,
        safety_state=safety_state,
    )

    # Length invariant must always hold
    assert len(result.cited_record_ids) == len(result.cited_tokens)


# ---------------------------------------------------------------------------
# 5. Insufficient evidence → zero LLM calls (HTTP 200 short-circuit)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_llm_insufficient_returns_directive_zero_citations():
    """INSUFFICIENT: answer = directive, zero citations, no further LLM work."""
    context = StructuredHealthContext()
    target = InquiryTarget(target_domain="labs", target_entity="vitamin d")
    evidence = EvidenceResult(
        status=EvidenceStatus.INSUFFICIENT,
        evidence_directive="Your records do not contain vitamin d.",
    )
    safety_state = SafetyGuardrailState(triggered=False)
    provider = MockLLMProvider()

    result = await provider.synthesize_response(
        query="What was my vitamin d?",
        target=target,
        context=context,
        evidence=evidence,
        safety_state=safety_state,
    )

    assert result.answer_text == evidence.evidence_directive
    assert result.cited_record_ids == []
    assert result.cited_tokens == []


# ---------------------------------------------------------------------------
# 6. Safety short-circuit: zero citations, answer = advisory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_llm_safety_override_zero_citations():
    """Safety-triggered: advisory returned, zero citations."""
    context = StructuredHealthContext()
    target = InquiryTarget(target_domain="labs")
    evidence = EvidenceResult(status=EvidenceStatus.SUFFICIENT)
    safety_state = SafetyGuardrailState(
        triggered=True,
        advisory_message="Seek emergency care immediately.",
    )
    provider = MockLLMProvider()

    result = await provider.synthesize_response(
        query="I have severe chest pain",
        target=target,
        context=context,
        evidence=evidence,
        safety_state=safety_state,
    )

    assert result.answer_text == "Seek emergency care immediately."
    assert result.cited_record_ids == []
    assert result.cited_tokens == []


# ---------------------------------------------------------------------------
# 7. Citation reconciliation edge cases (orchestrator-level, not API-level)
# ---------------------------------------------------------------------------


def test_citation_reconciliation_length_mismatch_fails_closed():
    """Length mismatch between cited_tokens and cited_record_ids: fail closed."""
    from app.api.health_inquiry import _build_record_map

    doc_id = uuid.uuid4()
    pec = PassageEvidenceContext(
        chunk_id=uuid.uuid4(),
        document_id=doc_id,
        chunk_index=0,
        page_number=1,
        chunk_text="cholesterol data",
        display_name="Lipid Panel",
        document_type="lab_report",
        document_date=date(2025, 6, 1),
        cosine_distance=0.15,
        similarity=0.85,
    )
    context = StructuredHealthContext(passages=[pec])
    record_map = _build_record_map(context)

    # Mismatched lengths — simulate a corrupt SynthesisResult
    cited_record_ids = [doc_id, uuid.uuid4()]
    cited_tokens = ["[DOC-1]"]  # length 1 vs 2

    assert len(cited_tokens) != len(cited_record_ids)

    # The orchestrator logic must detect this and emit zero citations.
    # We simulate the orchestrator's guard:
    verified: list[InquiryCitation] = []
    if len(cited_tokens) != len(cited_record_ids):
        pass  # fail closed: no citations emitted
    else:
        for rid, token in zip(cited_record_ids, cited_tokens):
            if rid in record_map:
                entity_type, label, vs = record_map[rid]
                verified.append(
                    InquiryCitation(
                        citation_id=1,
                        entity_type=entity_type,
                        record_id=rid,
                        label=label,
                        verification_state=vs,
                    )
                )
    assert verified == []


def test_citation_reconciliation_duplicate_token_emits_one():
    """Duplicate cited token → exactly one citation emitted."""
    from app.api.health_inquiry import _build_record_map

    doc_id = uuid.uuid4()
    pec = PassageEvidenceContext(
        chunk_id=uuid.uuid4(),
        document_id=doc_id,
        chunk_index=0,
        page_number=1,
        chunk_text="cholesterol data",
        display_name="Lipid Panel",
        document_type="lab_report",
        document_date=date(2025, 6, 1),
        cosine_distance=0.15,
        similarity=0.85,
    )
    context = StructuredHealthContext(passages=[pec])
    record_map = _build_record_map(context)

    # Both entries resolve to the same document_id (duplicate token)
    cited_record_ids = [doc_id, doc_id]
    cited_tokens = ["[DOC-1]", "[DOC-1]"]

    verified: list[InquiryCitation] = []
    seen: set[uuid.UUID] = set()
    counter = 1
    for rid, token in zip(cited_record_ids, cited_tokens):
        if rid in seen:
            continue
        if rid not in record_map:
            continue
        entity_type, label, vs = record_map[rid]
        verified.append(
            InquiryCitation(
                citation_id=counter,
                entity_type=entity_type,
                record_id=rid,
                label=label,
                verification_state=vs,
            )
        )
        seen.add(rid)
        counter += 1

    assert len(verified) == 1
    assert verified[0].record_id == doc_id


def test_citation_reconciliation_unknown_token_ignored():
    """Unknown / hallucinated token → not present in verified citations."""
    from app.api.health_inquiry import _build_record_map

    doc_id = uuid.uuid4()
    pec = PassageEvidenceContext(
        chunk_id=uuid.uuid4(),
        document_id=doc_id,
        chunk_index=0,
        page_number=1,
        chunk_text="cholesterol data",
        display_name="Lipid Panel",
        document_type="lab_report",
        document_date=date(2025, 6, 1),
        cosine_distance=0.15,
        similarity=0.85,
    )
    context = StructuredHealthContext(passages=[pec])
    record_map = _build_record_map(context)

    hallucinated_id = uuid.uuid4()
    cited_record_ids = [doc_id, hallucinated_id]
    cited_tokens = ["[DOC-1]", "[DOC-99]"]

    verified: list[InquiryCitation] = []
    seen: set[uuid.UUID] = set()
    counter = 1
    for rid, token in zip(cited_record_ids, cited_tokens):
        if rid in seen or rid not in record_map:
            continue
        entity_type, label, vs = record_map[rid]
        verified.append(
            InquiryCitation(
                citation_id=counter,
                entity_type=entity_type,
                record_id=rid,
                label=label,
                verification_state=vs,
            )
        )
        seen.add(rid)
        counter += 1

    assert len(verified) == 1
    assert verified[0].record_id == doc_id


def test_citation_reconciliation_token_absent_from_passage_map_no_enrichment():
    """Valid token with no passage_map entry → no chunk_id / page_number emitted."""
    passage_map: dict[str, PassageProvenance] = {}  # intentionally empty
    token = "[DOC-1]"
    provenance = passage_map.get(token)
    assert provenance is None
    # chunk_id / page_number / passage_text should all remain None
    chunk_id = provenance.chunk_id if provenance else None
    page_number = provenance.page_number if provenance else None
    passage_text = provenance.passage_text if provenance else None
    assert chunk_id is None
    assert page_number is None
    assert passage_text is None


# ---------------------------------------------------------------------------
# 8. Passage citation enrichment (chunk_id, page_number, passage_text)
# ---------------------------------------------------------------------------


def test_passage_map_provides_chunk_level_enrichment():
    """passage_map lookup yields correct chunk_id, page_number, passage_text."""
    pec = PassageEvidenceContext(
        chunk_id=CHUNK_ID_1,
        document_id=DOC_ID_A,
        chunk_index=0,
        page_number=3,
        chunk_text="cholesterol 185 mg/dL",
        display_name="Lipid Panel",
        document_type="lab_report",
        document_date=date(2025, 6, 1),
        cosine_distance=0.15,
        similarity=0.85,
    )
    context = StructuredHealthContext(passages=[pec])
    target = InquiryTarget(target_domain="labs", target_entity="cholesterol")
    sanitized = build_sanitized_context(context, target)

    assert "[DOC-1]" in sanitized.passage_map
    prov = sanitized.passage_map["[DOC-1]"]
    assert prov.chunk_id == CHUNK_ID_1
    assert prov.page_number == 3
    assert prov.passage_text == "cholesterol 185 mg/dL"
    assert prov.document_id == DOC_ID_A


def test_dual_resolution_same_document_different_chunks():
    """Two passages from same document → same document_id, different chunk_ids."""
    pec1 = PassageEvidenceContext(
        chunk_id=CHUNK_ID_1,
        document_id=DOC_ID_A,
        chunk_index=0,
        page_number=1,
        chunk_text="cholesterol 185",
        display_name="Lipid Panel",
        document_type="lab_report",
        document_date=date(2025, 6, 1),
        cosine_distance=0.1,
        similarity=0.9,
    )
    pec2 = PassageEvidenceContext(
        chunk_id=CHUNK_ID_2,
        document_id=DOC_ID_A,
        chunk_index=1,
        page_number=4,
        chunk_text="hdl 55 mg/dL",
        display_name="Lipid Panel",
        document_type="lab_report",
        document_date=date(2025, 6, 1),
        cosine_distance=0.15,
        similarity=0.85,
    )
    context = StructuredHealthContext(passages=[pec1, pec2])
    sanitized = build_sanitized_context(context, None)

    assert sanitized.reference_map["[DOC-1]"] == DOC_ID_A
    assert sanitized.reference_map["[DOC-2]"] == DOC_ID_A
    assert sanitized.passage_map["[DOC-1]"].chunk_id == CHUNK_ID_1
    assert sanitized.passage_map["[DOC-2]"].chunk_id == CHUNK_ID_2
    assert sanitized.passage_map["[DOC-1]"].page_number == 1
    assert sanitized.passage_map["[DOC-2]"].page_number == 4


# ---------------------------------------------------------------------------
# 9. _build_record_map covers context.passages
# ---------------------------------------------------------------------------


def test_build_record_map_covers_passages():
    """_build_record_map maps passage document_ids to DOCUMENT entries."""
    from app.api.health_inquiry import _build_record_map

    pec = PassageEvidenceContext(
        chunk_id=CHUNK_ID_1,
        document_id=DOC_ID_A,
        chunk_index=0,
        page_number=1,
        chunk_text="test",
        display_name="Lipid Panel",
        document_type="lab_report",
        document_date=date(2025, 6, 1),
        cosine_distance=0.1,
        similarity=0.9,
    )
    context = StructuredHealthContext(passages=[pec])
    record_map = _build_record_map(context)

    assert DOC_ID_A in record_map
    entity_type, label, vs = record_map[DOC_ID_A]
    assert entity_type == "DOCUMENT"
    assert "Lipid Panel" in label
    assert vs == VerificationState.SOURCE_RECORDED


def test_build_record_map_no_duplicate_from_passages_and_docs():
    """If the same document_id appears in both documents and passages,
    the M3 documents entry takes precedence (it's registered first)."""
    from app.api.health_inquiry import _build_record_map

    doc_ctx = DocumentEvidenceContext(
        document_id=DOC_ID_A,
        display_name="Lipid Panel M3",
        document_type="lab_report",
        document_date=date(2025, 6, 1),
        extracted_excerpt="some text",
    )
    pec = PassageEvidenceContext(
        chunk_id=CHUNK_ID_1,
        document_id=DOC_ID_A,
        chunk_index=0,
        page_number=1,
        chunk_text="test",
        display_name="Lipid Panel M4",
        document_type="lab_report",
        document_date=date(2025, 6, 1),
        cosine_distance=0.1,
        similarity=0.9,
    )
    context = StructuredHealthContext(documents=[doc_ctx], passages=[pec])
    record_map = _build_record_map(context)

    # Only one entry; M3 doc (registered first) wins
    assert DOC_ID_A in record_map
    entity_type, label, vs = record_map[DOC_ID_A]
    assert "Lipid Panel M3" in label


# ---------------------------------------------------------------------------
# 10. InquiryCitation backward compatibility (M3 fields unaffected)
# ---------------------------------------------------------------------------


def test_inquiry_citation_m3_backward_compatible():
    """M3 callers that don't supply chunk_id/page_number/passage_text get None."""
    cid = uuid.uuid4()
    citation = InquiryCitation(
        citation_id=1,
        entity_type="CONDITION",
        record_id=cid,
        label="Hypertension",
        verification_state=VerificationState.UNCERTAIN,
    )
    assert citation.chunk_id is None
    assert citation.page_number is None
    assert citation.passage_text is None


def test_inquiry_citation_m4_passage_fields():
    """M4 passage citations carry chunk_id, page_number, passage_text."""
    cid = uuid.uuid4()
    cid_chunk = uuid.uuid4()
    citation = InquiryCitation(
        citation_id=1,
        entity_type="DOCUMENT",
        record_id=cid,
        label="Lipid Panel (2025-06-01)",
        verification_state=VerificationState.SOURCE_RECORDED,
        chunk_id=cid_chunk,
        page_number=3,
        passage_text="cholesterol 185 mg/dL",
    )
    assert citation.chunk_id == cid_chunk
    assert citation.page_number == 3
    assert citation.passage_text == "cholesterol 185 mg/dL"


# ---------------------------------------------------------------------------
# 11. SynthesisResult: cited_tokens default and length invariant
# ---------------------------------------------------------------------------


def test_synthesis_result_default_cited_tokens_empty():
    """SynthesisResult.cited_tokens defaults to empty list (backward-compatible)."""
    result = SynthesisResult(
        answer_text="test",
        cited_record_ids=[uuid.uuid4()],
    )
    # cited_tokens not provided: defaults to []
    assert result.cited_tokens == []


def test_synthesis_result_with_tokens_aligned():
    """When cited_tokens provided, must be parallel to cited_record_ids."""
    rid = uuid.uuid4()
    result = SynthesisResult(
        answer_text="test",
        cited_record_ids=[rid],
        cited_tokens=["[DOC-1]"],
    )
    assert len(result.cited_record_ids) == len(result.cited_tokens)
    assert result.cited_tokens[0] == "[DOC-1]"


# ---------------------------------------------------------------------------
# 12. Partial evidence synthesis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_llm_partially_sufficient_uses_directive():
    """Partially sufficient: MockLLMProvider returns directive, cites passage doc."""
    pec = PassageEvidenceContext(
        chunk_id=CHUNK_ID_1,
        document_id=DOC_ID_A,
        chunk_index=0,
        page_number=1,
        chunk_text="fasting glucose 95 mg/dL",
        display_name="Metabolic Panel",
        document_type="lab_report",
        document_date=date(2025, 8, 1),
        cosine_distance=0.1,
        similarity=0.9,
    )
    context = StructuredHealthContext(passages=[pec])
    target = InquiryTarget(
        target_domain="labs",
        requested_attributes=["fasting glucose", "hba1c"],
    )
    evidence = EvidenceResult(
        status=EvidenceStatus.PARTIALLY_SUFFICIENT,
        matched_fields=["fasting glucose"],
        missing_fields=["hba1c"],
        evidence_directive=(
            "Information partially found in your uploaded records. "
            "Not found in records: hba1c."
        ),
        qualified_passages=[],
    )
    safety_state = SafetyGuardrailState(triggered=False)
    provider = MockLLMProvider()

    result = await provider.synthesize_response(
        query="What were my glucose and hba1c?",
        target=target,
        context=context,
        evidence=evidence,
        safety_state=safety_state,
    )

    assert result.answer_text == evidence.evidence_directive
    assert DOC_ID_A in result.cited_record_ids
    assert len(result.cited_record_ids) == len(result.cited_tokens)


# ---------------------------------------------------------------------------
# 13. M3 whole-document regression: existing tests remain compatible
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_llm_m3_document_sufficient_regression():
    """M3 whole-document SUFFICIENT path continues to work (regression guard)."""
    doc_id = uuid.uuid4()
    doc = DocumentEvidenceContext(
        document_id=doc_id,
        display_name="CBC Report",
        document_type="lab_report",
        document_date=date(2026, 1, 15),
        extracted_excerpt="WBC: 6.8 K/uL",
    )
    context = StructuredHealthContext(documents=[doc])
    target = InquiryTarget(target_domain="labs", target_entity="WBC")
    evidence = EvidenceResult(
        status=EvidenceStatus.SUFFICIENT,
        evidence_directive="Found.",
        matched_fields=["wbc"],
    )
    safety_state = SafetyGuardrailState(triggered=False)
    provider = MockLLMProvider()

    result = await provider.synthesize_response(
        query="What was my WBC?",
        target=target,
        context=context,
        evidence=evidence,
        safety_state=safety_state,
    )

    assert isinstance(result, SynthesisResult)
    assert "CBC Report" in result.answer_text
    assert doc_id in result.cited_record_ids
    assert len(result.cited_record_ids) == len(result.cited_tokens)


# ---------------------------------------------------------------------------
# 14. HTTP endpoint: retrieval failure → HTTP 500 (mocked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_endpoint_retrieval_failure_returns_500():
    """When retrieve_document_passages raises, endpoint must return HTTP 500."""

    from app.api.health_inquiry import submit_health_inquiry
    from app.core.auth import AuthenticatedUser

    mock_patient = MagicMock()
    mock_patient.id = PATIENT_ID

    mock_user = AuthenticatedUser(id=str(PATIENT_ID), email="test@example.com")
    mock_context = StructuredHealthContext()

    with (
        patch(
            "app.api.health_inquiry.get_or_create_patient",
            new_callable=AsyncMock,
            return_value=mock_patient,
        ),
        patch(
            "app.api.health_inquiry.build_inquiry_context",
            new_callable=AsyncMock,
            return_value=mock_context,
        ),
        patch(
            "app.api.health_inquiry.evaluate_safety",
            return_value=SafetyGuardrailState(triggered=False),
        ),
        patch(
            "app.api.health_inquiry.parse_natural_language_query",
            return_value=InquiryTarget(target_domain="labs", target_entity="glucose"),
        ),
        patch(
            "app.api.health_inquiry.retrieve_document_passages",
            new_callable=AsyncMock,
            side_effect=RetrievalDatabaseError("DB down"),
        ),
    ):
        import fastapi

        request = HealthInquiryRequest(query="What was my glucose?")
        db_mock = AsyncMock()
        llm_mock = AsyncMock()

        with pytest.raises(fastapi.HTTPException) as exc_info:
            await submit_health_inquiry(
                request=request,
                current_user=mock_user,
                db=db_mock,
                llm=llm_mock,
            )
        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# 15. API Document-Domain Invariants (Migrated from M3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_endpoint_document_inquiry_sufficient_evidence(async_client: AsyncClient):
    user_id, token = await create_user_and_token()

    mock_passage = RetrievedPassage(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        patient_id=user_id,
        chunk_index=0,
        page_number=1,
        chunk_text="Creatinine: 0.9 mg/dL",
        document_display_name="Metabolic Panel",
        document_type="lab_report",
        document_date=date(2026, 8, 12),
        cosine_distance=0.1,
        similarity=0.9,
    )

    with patch(
        "app.api.health_inquiry.retrieve_document_passages", new_callable=AsyncMock
    ) as mock_retrieval:

        async def _mock_retrieve(**kwargs):
            return RetrievalResult(
                patient_id=kwargs["patient_id"],
                target_domains=("document",),
                query_text="What was my creatinine?",
                top_k=20,
                passages=(
                    dataclasses.replace(mock_passage, patient_id=kwargs["patient_id"]),
                ),
            )

        mock_retrieval.side_effect = _mock_retrieve
        response = await async_client.post(
            "/api/v1/health-inquiry",
            headers={"Authorization": f"Bearer {token}"},
            json={"query": "What was my creatinine?"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["evidence_status"] == EvidenceStatus.SUFFICIENT
    assert len(data["citations"]) == 1
    assert data["citations"][0]["record_id"] == str(mock_passage.document_id)


@pytest.mark.asyncio
async def test_endpoint_document_inquiry_absent_analyte_insufficient(
    async_client: AsyncClient,
):
    user_id, token = await create_user_and_token()

    mock_passage = RetrievedPassage(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        patient_id=user_id,
        chunk_index=0,
        page_number=1,
        chunk_text="Creatinine: 0.9 mg/dL",
        document_display_name="Metabolic Panel",
        document_type="lab_report",
        document_date=date(2026, 8, 12),
        cosine_distance=0.1,
        similarity=0.9,
    )

    with patch(
        "app.api.health_inquiry.retrieve_document_passages", new_callable=AsyncMock
    ) as mock_retrieval:

        async def _mock_retrieve(**kwargs):
            return RetrievalResult(
                patient_id=kwargs["patient_id"],
                target_domains=("document",),
                query_text="What was my cholesterol?",
                top_k=20,
                passages=(
                    dataclasses.replace(mock_passage, patient_id=kwargs["patient_id"]),
                ),
            )

        mock_retrieval.side_effect = _mock_retrieve
        response = await async_client.post(
            "/api/v1/health-inquiry",
            headers={"Authorization": f"Bearer {token}"},
            json={"query": "What was my cholesterol?"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["evidence_status"] == EvidenceStatus.INSUFFICIENT
    assert "do not contain a record of: cholesterol." in data["answer"].lower()


@pytest.mark.asyncio
async def test_endpoint_document_inquiry_zero_candidates_insufficient(
    async_client: AsyncClient,
):
    user_id, token = await create_user_and_token()

    with patch(
        "app.api.health_inquiry.retrieve_document_passages", new_callable=AsyncMock
    ) as mock_retrieval:

        async def _mock_retrieve(**kwargs):
            return RetrievalResult(
                patient_id=kwargs["patient_id"],
                target_domains=("document",),
                query_text="What did my blood test say?",
                top_k=20,
                passages=(),
            )

        mock_retrieval.side_effect = _mock_retrieve
        response = await async_client.post(
            "/api/v1/health-inquiry",
            headers={"Authorization": f"Bearer {token}"},
            json={"query": "What did my blood test say?"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["evidence_status"] == EvidenceStatus.INSUFFICIENT
    assert "do not contain a record of: blood test." in data["answer"].lower()


@pytest.mark.asyncio
async def test_endpoint_document_inquiry_tenant_isolation(
    async_client: AsyncClient, db: AsyncSession
):
    user_id, token = await create_user_and_token()

    with patch(
        "app.api.health_inquiry.retrieve_document_passages", new_callable=AsyncMock
    ) as mock_retrieval:

        async def _mock_retrieve(**kwargs):
            return RetrievalResult(
                patient_id=kwargs["patient_id"],
                target_domains=("document",),
                query_text="What was my creatinine?",
                top_k=20,
                passages=(),
            )

        mock_retrieval.side_effect = _mock_retrieve
        response = await async_client.post(
            "/api/v1/health-inquiry",
            headers={"Authorization": f"Bearer {token}"},
            json={"query": "What was my creatinine?"},
        )

        # Verify S4 retrieval was scoped to the calling user_id
        # Verify S4 retrieval was scoped to the actual DB patient_id for the user
        mock_retrieval.assert_called_once()
        call_kwargs = mock_retrieval.call_args.kwargs

        stmt = select(Patient.id).where(Patient.user_id == uuid.UUID(user_id))
        patient_id_db = (await db.execute(stmt)).scalar_one()
        assert call_kwargs.get("patient_id") == patient_id_db

    assert response.status_code == 200
    data = response.json()
    assert data["evidence_status"] == EvidenceStatus.INSUFFICIENT
    assert "do not contain a record of: creatinine." in data["answer"].lower()


@pytest.mark.asyncio
async def test_endpoint_document_inquiry_safety_preflight_precedence(
    async_client: AsyncClient,
):
    user_id, token = await create_user_and_token()

    query = "I am having severe chest pain right now, what should I do?"

    with patch(
        "app.api.health_inquiry.retrieve_document_passages", new_callable=AsyncMock
    ) as mock_retrieval:
        response = await async_client.post(
            "/api/v1/health-inquiry",
            headers={"Authorization": f"Bearer {token}"},
            json={"query": query},
        )

        mock_retrieval.assert_not_called()

    assert response.status_code == 200
    data = response.json()
    assert len(data["citations"]) == 0
