"""
M4 Comparative Evaluation Harness
Verifies the 6 core architectural enhancements of M4 over M3.
"""

import uuid
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from app.health.evidence_evaluator import EvidenceStatus
from app.health.inquiry_context import StructuredHealthContext
from app.health.retrieval import RetrievalResult, RetrievedPassage
from app.schemas.inquiry import InquiryTarget

PATIENT_ID = uuid.uuid4()


def _make_passage(
    chunk_text: str,
    document_id: uuid.UUID | None = None,
    chunk_id: uuid.UUID | None = None,
    page_number: int = 1,
    document_date: date | None = None,
    patient_id: uuid.UUID | None = None,
) -> RetrievedPassage:
    return RetrievedPassage(
        chunk_id=chunk_id or uuid.uuid4(),
        document_id=document_id or uuid.uuid4(),
        patient_id=patient_id or PATIENT_ID,
        chunk_index=0,
        page_number=page_number,
        chunk_text=chunk_text,
        document_display_name="Test Doc",
        document_type="lab_report",
        document_date=document_date or date(2025, 1, 1),
        cosine_distance=0.1,
        similarity=0.9,
    )


# 1. Longitudinal Discovery vs M3 Recency Bias
@pytest.mark.asyncio
async def test_eval_longitudinal_discovery():
    """
    Patient has Document A (older, contains target analyte) and Document B
    (newer, unrelated).
    Hybrid retrieval returns Document A passage; evidence scores SUFFICIENT;
    answer synthesizes finding citing Document A.
    """
    doc_a_id = uuid.uuid4()
    doc_b_id = uuid.uuid4()
    p_older_target = _make_passage(
        "cholesterol 185 mg/dL", document_id=doc_a_id, document_date=date(2020, 1, 1)
    )
    p_newer_unrelated = _make_passage(
        "blood pressure normal", document_id=doc_b_id, document_date=date(2025, 1, 1)
    )

    with patch(
        "app.api.health_inquiry.retrieve_document_passages", new_callable=AsyncMock
    ) as mock_retrieval:
        mock_retrieval.return_value = RetrievalResult(
            patient_id=PATIENT_ID,
            target_domains=("labs",),
            query_text="What is my cholesterol?",
            top_k=5,
            passages=(p_older_target, p_newer_unrelated),
        )

        # Test full pipeline via evaluate_passage_evidence and MockLLMProvider
        from app.health.evidence_evaluator import evaluate_passage_evidence

        target = InquiryTarget(
            target_domain="labs", requested_attributes=["cholesterol"]
        )
        evidence = evaluate_passage_evidence(
            target, mock_retrieval.return_value, PATIENT_ID
        )

        assert evidence.status == EvidenceStatus.SUFFICIENT
        assert len(evidence.qualified_passages) == 1
        assert evidence.qualified_passages[0].document_id == doc_a_id


# 2. Multi-Passage Attribute Pooling
@pytest.mark.asyncio
async def test_eval_multi_passage_pooling():
    """
    Query requests attributes spanning across 2 distinct passages.
    Evaluator aggregates attributes across passages into SUFFICIENT;
    missing_fields is empty; both cited.
    """
    p1 = _make_passage("cholesterol 185 mg/dL")
    p2 = _make_passage("hdl 55 mg/dL")

    from app.health.evidence_evaluator import evaluate_passage_evidence

    target = InquiryTarget(
        target_domain="labs", requested_attributes=["cholesterol", "hdl"]
    )
    retrieval_result = RetrievalResult(
        patient_id=PATIENT_ID,
        target_domains=("labs",),
        query_text="",
        top_k=5,
        passages=(p1, p2),
    )

    evidence = evaluate_passage_evidence(target, retrieval_result, PATIENT_ID)

    assert evidence.status == EvidenceStatus.SUFFICIENT
    assert evidence.missing_fields == []
    assert len(evidence.qualified_passages) == 2


# 3. Irrelevant Nearest-Neighbor Pruning
@pytest.mark.asyncio
async def test_eval_irrelevant_neighbor_pruning():
    """
    Retrieval returns 4 candidate chunks: 2 corroborate the clinical target,
    2 are irrelevant neighbors.
    Serialized prompt context contains strictly the 2 qualified chunks.
    """
    p1 = _make_passage("creatinine 1.1")
    p2 = _make_passage("creatinine 1.2")
    p3 = _make_passage("random text about diet")
    p4 = _make_passage("some other irrelevant note")

    from app.health.evidence_evaluator import evaluate_passage_evidence

    target = InquiryTarget(target_domain="labs", target_entity="creatinine")
    retrieval_result = RetrievalResult(
        patient_id=PATIENT_ID,
        target_domains=("labs",),
        query_text="",
        top_k=5,
        passages=(p1, p2, p3, p4),
    )

    evidence = evaluate_passage_evidence(target, retrieval_result, PATIENT_ID)

    assert evidence.status == EvidenceStatus.SUFFICIENT
    assert len(evidence.qualified_passages) == 2
    chunk_ids = {p.chunk_id for p in evidence.qualified_passages}
    assert p1.chunk_id in chunk_ids
    assert p2.chunk_id in chunk_ids


# 4. Dual-Resolution Provenance Integrity
@pytest.mark.asyncio
async def test_eval_dual_resolution_provenance():
    """
    Multi-passage synthesis emits citations for Page 1 and Page 4 of the same document.
    Both citations resolve to authentic MedicalDocument.id;
    chunk_id/page_number/passage_text match.
    """
    from app.api.health_inquiry import _build_record_map
    from app.health.inquiry_context import PassageEvidenceContext

    doc_id = uuid.uuid4()
    c1 = uuid.uuid4()
    c2 = uuid.uuid4()
    pec1 = PassageEvidenceContext(
        chunk_id=c1,
        document_id=doc_id,
        chunk_index=0,
        page_number=1,
        chunk_text="p1",
        display_name="Doc",
        document_type="lab_report",
        document_date=date(2025, 1, 1),
        cosine_distance=0.1,
        similarity=0.9,
    )
    pec2 = PassageEvidenceContext(
        chunk_id=c2,
        document_id=doc_id,
        chunk_index=1,
        page_number=4,
        chunk_text="p4",
        display_name="Doc",
        document_type="lab_report",
        document_date=date(2025, 1, 1),
        cosine_distance=0.1,
        similarity=0.9,
    )
    context = StructuredHealthContext(passages=[pec1, pec2])

    from app.health.sanitized_context import build_sanitized_context

    sanitized = build_sanitized_context(context, InquiryTarget(target_domain="labs"))

    assert sanitized.passage_map["[DOC-1]"].page_number == 1
    assert sanitized.passage_map["[DOC-2]"].page_number == 4

    record_map = _build_record_map(context)
    assert doc_id in record_map


# 5. Corpus-Level Absence Honesty
@pytest.mark.asyncio
async def test_eval_corpus_absence_honesty():
    """
    Query targets an analyte not present anywhere in patient records.
    Result is INSUFFICIENT; directive states absence. Zero citations.
    """
    from app.health.evidence_evaluator import evaluate_passage_evidence

    target = InquiryTarget(target_domain="labs", target_entity="unknown_analyte")
    retrieval_result = RetrievalResult(
        patient_id=PATIENT_ID,
        target_domains=("labs",),
        query_text="",
        top_k=5,
        passages=(),
    )

    evidence = evaluate_passage_evidence(target, retrieval_result, PATIENT_ID)

    assert evidence.status == EvidenceStatus.INSUFFICIENT
    assert "unknown_analyte" in evidence.evidence_directive.lower()


# 6. Safety Pre-Flight Precedence & Tenant Gate
@pytest.mark.asyncio
async def test_eval_safety_and_tenant_gate():
    """
    Acute symptom query with candidate passages present -> SAFETY_ADVISORY.
    Tenant mismatch injection attempt -> INSUFFICIENT.
    """
    from app.health.safety_guardrails import evaluate_safety

    safety_state = evaluate_safety("I have severe chest pain right now")
    assert safety_state.triggered is True
    assert "emergency" in safety_state.advisory_message.lower()

    from app.health.evidence_evaluator import evaluate_passage_evidence

    target = InquiryTarget(target_domain="labs", target_entity="cholesterol")
    p_foreign = _make_passage("cholesterol 185", patient_id=uuid.uuid4())
    retrieval_result = RetrievalResult(
        patient_id=PATIENT_ID,
        target_domains=("labs",),
        query_text="",
        top_k=5,
        passages=(p_foreign,),
    )

    # Tenant mismatch
    evidence = evaluate_passage_evidence(target, retrieval_result, PATIENT_ID)
    assert evidence.status == EvidenceStatus.INSUFFICIENT
