import uuid
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.core.llm import MockLLMProvider
from app.db.models import Patient
from app.health.evidence_evaluator import (
    evaluate_passage_evidence,
)
from app.health.inquiry_context import (
    PassageEvidenceContext,
    StructuredHealthContext,
)
from app.health.query_understanding import parse_natural_language_query
from app.health.retrieval import RetrievalResult, RetrievedPassage
from app.schemas.inquiry import (
    EvidenceStatus,
    InquiryTarget,
    RoutingMode,
    SafetyGuardrailState,
    TemporalScope,
)
from tests.test_health_inquiry_api import create_user_and_token

PATIENT_A_ID = uuid.uuid4()
PATIENT_B_ID = uuid.uuid4()
DOC_ID = uuid.uuid4()
CHUNK_ID = uuid.uuid4()


def _make_passage(
    chunk_text: str,
    patient_id: uuid.UUID = PATIENT_A_ID,
    document_id: uuid.UUID = DOC_ID,
    chunk_id: uuid.UUID = CHUNK_ID,
    page_number: int = 1,
    document_date: date = date(2024, 6, 15),
    document_type: str = "prescription",
    display_name: str = "Prescription - Lisinopril.pdf",
) -> RetrievedPassage:
    return RetrievedPassage(
        chunk_id=chunk_id,
        document_id=document_id,
        patient_id=patient_id,
        chunk_index=0,
        page_number=page_number,
        chunk_text=chunk_text,
        document_display_name=display_name,
        document_type=document_type,
        document_date=document_date,
        cosine_distance=0.08,
        similarity=0.92,
    )


def _to_context_passage(p: RetrievedPassage) -> PassageEvidenceContext:
    return PassageEvidenceContext(
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


# ---------------------------------------------------------------------------
# 1. Lisinopril physician + dosage retrieval and explicit synthesis
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_lisinopril_physician_and_dosage_retrieval_and_synthesis():
    query = "Who prescribed my Lisinopril and at what dose?"
    target = parse_natural_language_query(query)

    assert target.routing_mode in (RoutingMode.DOCUMENT_ONLY, RoutingMode.CROSS_DOMAIN)
    assert "prescriptions" in target.candidate_document_domains
    assert target.target_entity.lower() == "lisinopril"
    assert "physician_name" in target.requested_attributes
    assert "dosage" in target.requested_attributes

    passage = _make_passage(
        "Prescription for Lisinopril. Dosage: 10 mg daily. "
        "Prescribing Physician: Dr. Jordan Casey, MD. Clinic: Westside Clinic."
    )
    retrieval_res = RetrievalResult(
        patient_id=PATIENT_A_ID,
        target_domains=("prescriptions",),
        query_text=query,
        top_k=5,
        passages=(passage,),
    )

    ev_result = evaluate_passage_evidence(
        target, retrieval_res, requesting_patient_id=PATIENT_A_ID
    )
    assert ev_result.status == EvidenceStatus.SUFFICIENT
    assert "dosage" in ev_result.matched_fields
    assert "physician_name" in ev_result.matched_fields

    provider = MockLLMProvider()
    context = StructuredHealthContext(passages=[_to_context_passage(passage)])
    synthesis = await provider.synthesize_response(
        query=query,
        target=target,
        context=context,
        evidence=ev_result,
        safety_state=SafetyGuardrailState(triggered=False),
    )

    assert "10 mg" in synthesis.answer_text
    assert "Dr. Jordan Casey, MD" in synthesis.answer_text
    assert "dosage: 10 mg" in synthesis.answer_text
    assert "physician_name: Dr. Jordan Casey, MD" in synthesis.answer_text


# ---------------------------------------------------------------------------
# 2. Lisinopril dosage-only retrieval and explicit synthesis
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_lisinopril_dosage_only_retrieval():
    query = "What is my dosage of Lisinopril?"
    target = parse_natural_language_query(query)

    assert target.target_entity.lower() == "lisinopril"
    assert "dosage" in target.requested_attributes

    passage = _make_passage(
        "Rx: Lisinopril. Strength: 20 mg oral tablet. Take once daily."
    )
    retrieval_res = RetrievalResult(
        patient_id=PATIENT_A_ID,
        target_domains=("prescriptions",),
        query_text=query,
        top_k=5,
        passages=(passage,),
    )

    ev_result = evaluate_passage_evidence(
        target, retrieval_res, requesting_patient_id=PATIENT_A_ID
    )
    assert ev_result.status == EvidenceStatus.SUFFICIENT
    assert "dosage" in ev_result.matched_fields

    provider = MockLLMProvider()
    context = StructuredHealthContext(passages=[_to_context_passage(passage)])
    synthesis = await provider.synthesize_response(
        query=query,
        target=target,
        context=context,
        evidence=ev_result,
        safety_state=SafetyGuardrailState(triggered=False),
    )

    assert "20 mg" in synthesis.answer_text
    assert "dosage: 20 mg" in synthesis.answer_text


# ---------------------------------------------------------------------------
# 3. "vitals" / "vital signs" routing vocabulary
# ---------------------------------------------------------------------------
def test_vitals_routing_vocabulary():
    queries = [
        "What were my vitals on June 15, 2024?",
        "Show me my vital signs from last week",
        "Check vital sign records",
    ]
    for q in queries:
        target = parse_natural_language_query(q)
        assert target.routing_mode == RoutingMode.DOCUMENT_ONLY
        assert "clinical_documents" in target.candidate_document_domains
        assert "reports" in target.candidate_document_domains
        assert not target.clarification_required


# ---------------------------------------------------------------------------
# 4. Same-day temporal filtering for June 15, 2024
# ---------------------------------------------------------------------------
def test_vitals_same_day_temporal_parsing():
    query = "What were my vitals on June 15, 2024?"
    target = parse_natural_language_query(query)

    assert target.temporal_constraint.scope == TemporalScope.INTERVAL
    assert target.temporal_constraint.start_date == date(2024, 6, 15)
    assert target.temporal_constraint.end_date == date(2024, 6, 15)
    assert target.temporal_constraint.anchor_year == 2024


# ---------------------------------------------------------------------------
# 5. Insufficient evidence behavior when no matching vitals evidence exists
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_vitals_insufficient_evidence_when_no_records():
    query = "What were my vitals on June 15, 2024?"
    target = parse_natural_language_query(query)

    retrieval_res = RetrievalResult(
        patient_id=PATIENT_A_ID,
        target_domains=("clinical_documents", "reports"),
        query_text=query,
        top_k=5,
        passages=(),
    )

    ev_result = evaluate_passage_evidence(
        target, retrieval_res, requesting_patient_id=PATIENT_A_ID
    )
    assert ev_result.status == EvidenceStatus.INSUFFICIENT
    assert len(ev_result.qualified_passages) == 0

    provider = MockLLMProvider()
    context = StructuredHealthContext(passages=[])
    synthesis = await provider.synthesize_response(
        query=query,
        target=target,
        context=context,
        evidence=ev_result,
        safety_state=SafetyGuardrailState(triggered=False),
    )

    # Must preserve fail-closed safe absence directive, no hallucinations, 0 citations
    assert (
        "do not contain a record of: vitals" in synthesis.answer_text
        or "No matching records found" in synthesis.answer_text
        or "No document records are available" in synthesis.answer_text
    )
    assert len(synthesis.cited_record_ids) == 0


# ---------------------------------------------------------------------------
# 6. Citation integrity
# ---------------------------------------------------------------------------
def test_citation_integrity_metadata_and_provenance():
    passage = _make_passage(
        "Prescription: Lisinopril 10 mg. Physician: Dr. Jordan Casey, MD.",
        page_number=2,
        display_name="Prescription_June2024.pdf",
    )
    target = InquiryTarget(
        candidate_document_domains=["prescriptions"],
        target_entity="Lisinopril",
        requested_attributes=["dosage", "physician_name"],
        routing_mode=RoutingMode.DOCUMENT_ONLY,
    )
    retrieval_res = RetrievalResult(
        patient_id=PATIENT_A_ID,
        target_domains=("prescriptions",),
        query_text="Who prescribed Lisinopril?",
        top_k=5,
        passages=(passage,),
    )

    ev_result = evaluate_passage_evidence(
        target, retrieval_res, requesting_patient_id=PATIENT_A_ID
    )
    assert len(ev_result.qualified_passages) == 1
    qualified = ev_result.qualified_passages[0]
    assert qualified.chunk_id == CHUNK_ID
    assert qualified.document_id == DOC_ID
    assert qualified.page_number == 2
    assert qualified.document_display_name == "Prescription_June2024.pdf"


# ---------------------------------------------------------------------------
# 7. Tenant isolation (Patient B's record rejected for Patient A)
# ---------------------------------------------------------------------------
def test_tenant_isolation_foreign_record_rejected():
    passage_foreign = _make_passage(
        "Prescription: Lisinopril 10 mg. Prescribing Physician: Dr. Jordan Casey, MD.",
        patient_id=PATIENT_B_ID,
    )
    target = InquiryTarget(
        candidate_document_domains=["prescriptions"],
        target_entity="Lisinopril",
        requested_attributes=["dosage", "physician_name"],
        routing_mode=RoutingMode.DOCUMENT_ONLY,
    )
    retrieval_res = RetrievalResult(
        patient_id=PATIENT_B_ID,
        target_domains=("prescriptions",),
        query_text="Who prescribed Lisinopril?",
        top_k=5,
        passages=(passage_foreign,),
    )

    ev_result = evaluate_passage_evidence(
        target, retrieval_res, requesting_patient_id=PATIENT_A_ID
    )
    assert ev_result.status == EvidenceStatus.INSUFFICIENT
    assert len(ev_result.qualified_passages) == 0


# ---------------------------------------------------------------------------
# 8. Anti-misattribution behavior (Reject Amoxicillin when querying Lisinopril)
# ---------------------------------------------------------------------------
def test_anti_misattribution_unrelated_medication_rejected():
    amoxicillin_passage = _make_passage(
        "Prescription for Amoxicillin 500 mg capsules PO tid. "
        "Physician: Dr. Robert Vance, MD."
    )
    target = InquiryTarget(
        candidate_document_domains=["prescriptions"],
        target_entity="Lisinopril",
        requested_attributes=["dosage", "physician_name"],
        routing_mode=RoutingMode.DOCUMENT_ONLY,
    )
    retrieval_res = RetrievalResult(
        patient_id=PATIENT_A_ID,
        target_domains=("prescriptions",),
        query_text="Who prescribed my Lisinopril and at what dose?",
        top_k=5,
        passages=(amoxicillin_passage,),
    )

    ev_result = evaluate_passage_evidence(
        target, retrieval_res, requesting_patient_id=PATIENT_A_ID
    )
    assert ev_result.status == EvidenceStatus.INSUFFICIENT
    assert len(ev_result.qualified_passages) == 0
    assert "dosage" not in ev_result.matched_fields
    assert "physician_name" not in ev_result.matched_fields


# ---------------------------------------------------------------------------
# 9. Integration Regression: Proving actual configured API path expresses
#    qualified dosage and physician values with citation provenance.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_integration_actual_configured_api_path_lisinopril_physician_and_dosage(
    async_client: AsyncClient,
):
    """
    Validates end-to-end through the actual configured LLM gateway / provider:
    The query 'Who prescribed my Lisinopril and at what dose?' must return
    both the qualified dosage ('10 mg') and prescribing physician
    ('Dr. Jordan Casey, MD') along with valid citation provenance pointing
    to the source document.
    Does NOT override or mock get_llm_provider/llm; exercises actual configured path.
    """
    _, token = await create_user_and_token()
    mock_patient_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    passage = _make_passage(
        "Prescription for Lisinopril. Dosage: 10 mg daily. "
        "Prescribing Doctor: Dr. Jordan Casey, MD. Clinic: Westside Clinic.",
        patient_id=mock_patient_id,
        chunk_id=chunk_id,
        document_id=doc_id,
    )

    with (
        patch(
            "app.api.health_inquiry.get_or_create_patient", new_callable=AsyncMock
        ) as m_pat,
        patch(
            "app.api.health_inquiry.build_inquiry_context", new_callable=AsyncMock
        ) as m_ctx,
        patch(
            "app.api.health_inquiry.retrieve_document_passages", new_callable=AsyncMock
        ) as m_ret,
    ):
        m_pat.return_value = Patient(id=mock_patient_id)
        m_ctx.return_value = StructuredHealthContext()
        m_ret.return_value = RetrievalResult(
            patient_id=mock_patient_id,
            target_domains=("prescriptions", "clinical_documents"),
            query_text="Who prescribed my Lisinopril and at what dose?",
            top_k=5,
            passages=(passage,),
        )

        # Call actual configured endpoint without mocking the LLM provider dependency
        response = await async_client.post(
            "/api/v1/health-inquiry",
            json={"query": "Who prescribed my Lisinopril and at what dose?"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()

        # 1. Qualified attribute values explicitly stated in answer
        assert "10 mg" in data["answer"]
        assert "Dr. Jordan Casey, MD" in data["answer"]

        # 2. Citation provenance verified
        assert len(data["citations"]) == 1
        citation = data["citations"][0]
        assert citation["record_id"] == str(doc_id)
        assert citation["chunk_id"] == str(chunk_id)
        assert citation["entity_type"] == "DOCUMENT"
        assert citation["verification_state"] == "SOURCE_RECORDED"
        assert citation["citation_id"] == 1


# ---------------------------------------------------------------------------
# 5. Query Understanding Lexicon Updates for Physician Names
# ---------------------------------------------------------------------------
def test_lisinopril_physician_attribute_extraction():
    q1 = "Who prescribed my Lisinopril and at what dose?"
    t1 = parse_natural_language_query(q1)
    assert "physician_name" in t1.requested_attributes
    assert "dosage" in t1.requested_attributes

    q2 = "Do you know who put me on Lisinopril, and how much was I taking?"
    t2 = parse_natural_language_query(q2)
    assert "physician_name" in t2.requested_attributes
    assert "dosage" in t2.requested_attributes

    q3 = "Who started me on Lisinopril?"
    t3 = parse_natural_language_query(q3)
    assert "physician_name" in t3.requested_attributes

    q4 = "How much Lisinopril was I taking?"
    t4 = parse_natural_language_query(q4)
    assert "dosage" in t4.requested_attributes
    assert "physician_name" not in t4.requested_attributes
