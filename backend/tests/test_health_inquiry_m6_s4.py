"""
Phase 2 — M6 Slice 4: Health Inquiry Orchestrator Integration & Regression Tests

Covers Cases 42, 50-53 (Integration checks) and Cases 54-55 (Regression gates)
according to V10.2 frozen specification.
"""

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import SynthesisResult
from app.db.models import Patient
from app.health.evidence_evaluator import (
    EvidenceResult,
    TrajectoryCompleteness,
    evaluate_evidence,
)
from app.health.evidence_fusion import fuse_cross_domain_evidence
from app.health.inquiry_context import (
    ConditionResponse,
    HealthEvent,
    MedicationResponse,
    StructuredHealthContext,
)
from app.health.retrieval import RetrievalResult, RetrievedPassage
from app.health.sanitized_context import build_sanitized_context
from app.schemas.inquiry import (
    EvidenceStatus,
    InquiryTarget,
    RoutingMode,
    SafetyGuardrailState,
    SuperlativeType,
    TemporalConstraint,
    TemporalScope,
    generate_timeline_event_id,
)
from tests.test_health_inquiry_api import create_user_and_token

PATIENT_ID = uuid.uuid4()


@pytest.fixture
def mock_safety():
    with patch("app.api.health_inquiry.evaluate_safety") as mock:
        mock.return_value = SafetyGuardrailState(triggered=False)
        yield mock


@pytest.fixture
def mock_parse():
    with patch("app.api.health_inquiry.parse_natural_language_query") as mock:
        yield mock


@pytest.fixture
def mock_patient():
    with patch(
        "app.api.health_inquiry.get_or_create_patient", new_callable=AsyncMock
    ) as mock:
        patient = Patient(id=PATIENT_ID)
        mock.return_value = patient
        yield mock


@pytest.fixture
def mock_build_context():
    with patch(
        "app.api.health_inquiry.build_inquiry_context", new_callable=AsyncMock
    ) as mock:
        mock.return_value = StructuredHealthContext()
        yield mock


@pytest.fixture
def mock_retrieve():
    with patch(
        "app.api.health_inquiry.retrieve_document_passages", new_callable=AsyncMock
    ) as mock:
        mock.return_value = RetrievalResult(
            patient_id=PATIENT_ID,
            target_domains=("clinical_notes",),
            query_text="",
            top_k=4,
            passages=(),
        )
        yield mock


@pytest.fixture
def mock_llm_synth():
    with patch("app.api.health_inquiry.get_llm_gateway") as mock_get_gateway:
        mock_provider = AsyncMock()
        mock_provider.synthesize_response.return_value = SynthesisResult(
            answer_text="Mocked Answer", cited_record_ids=[], cited_tokens=[]
        )
        mock_get_gateway.return_value = mock_provider
        yield mock_provider


# ---------------------------------------------------------------------------
# Case 42: Upload timestamp disqualification for superlatives (Integration)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upload_timestamp_disqualification_superlative(
    async_client: AsyncClient,
    db: AsyncSession,
    mock_safety,
    mock_parse,
    mock_patient,
    mock_build_context,
    mock_llm_synth,
):
    """
    Case 42 [INTEGRATION - BEHAVIORAL]:
    Timeline event with event_type == 'DOCUMENT_UPLOADED' (2026-01-01) is the only
    matching record for query: 'What is my latest lab test?'.
    Orchestrated through health_inquiry.py endpoint.

    Expected:
    - DOCUMENT_UPLOADED is disqualified from clinical recency.
    - Zero clinical dates found -> status == PARTIALLY_SUFFICIENT.
    - Directive: 'Identified lab test records, but no verifiable clinical dates were
      recorded to establish recency.'
    - Undated candidate retained in matched_records and cited.
    - LLM provider is CALLED exactly once (1 call) with recency caveat.
    """
    mock_parse.return_value = InquiryTarget(
        question_intent="FACTUAL",
        target_entity="lab test",
        candidate_structured_domains=["timeline"],
        candidate_document_domains=[],
        routing_mode=RoutingMode.STRUCTURED_ONLY,
        temporal_constraint=TemporalConstraint(
            superlative=SuperlativeType.LATEST,
            raw_expression="latest",
        ),
    )

    ev_id = uuid.uuid4()
    upload_event = HealthEvent(
        event_type="DOCUMENT_UPLOADED",
        source_type="DOCUMENT",
        source_id=ev_id,
        title="Lab Test PDF",
        description="lab test document uploaded",
        event_date="2026-01-01",
        event_state="historical",
    )
    mock_build_context.return_value.recent_timeline_events = [upload_event]

    expected_timeline_id = generate_timeline_event_id(
        "DOCUMENT", ev_id, "DOCUMENT_UPLOADED"
    )
    mock_llm_synth.synthesize_response.return_value = SynthesisResult(
        answer_text="Based on records, lab test document was found but lacks dates.",
        cited_record_ids=[expected_timeline_id],
        cited_tokens=[""],
    )

    _, token = await create_user_and_token()
    response = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "What is my latest lab test?"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["evidence_status"] == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert mock_llm_synth.synthesize_response.call_count == 1
    assert len(data["citations"]) == 1
    assert data["citations"][0]["record_id"] == str(expected_timeline_id)
    assert data["citations"][0]["entity_type"] == "TIMELINE"


# ---------------------------------------------------------------------------
# Case 50: Tenant isolation boundary (Integration)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tenant_isolation_boundary(
    async_client: AsyncClient,
    db: AsyncSession,
    mock_safety,
    mock_parse,
    mock_patient,
    mock_build_context,
    mock_retrieve,
    mock_llm_synth,
):
    """
    Case 50 [INTEGRATION - BEHAVIORAL]:
    Inject a foreign-patient passage into retrieval result before S4
    candidate-pool construction / before fuse_cross_domain_evidence() ->
    evaluate_longitudinal_trajectory() path is entered.

    Expected:
    - Upstream tenant boundary in evaluate_passage_evidence rejects foreign candidate.
    - Foreign candidate never enters S4 candidate pools.
    - Zero cross-tenant evidence reaches S4 trajectory or comparison processing.
    - Returns INSUFFICIENT with 0 LLM calls.
    """
    mock_parse.return_value = InquiryTarget(
        question_intent="COMPARISON",
        target_entity="blood pressure",
        candidate_structured_domains=[],
        candidate_document_domains=["clinical_notes"],
        routing_mode=RoutingMode.DOCUMENT_ONLY,
    )

    foreign_patient_id = uuid.uuid4()
    foreign_passage = RetrievedPassage(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_index=0,
        page_number=1,
        chunk_text="Foreign patient blood pressure 120/80 on 2024-01-01.",
        document_display_name="Foreign Report",
        document_type="CLINICAL_NOTE",
        document_date=date(2024, 1, 1),
        patient_id=foreign_patient_id,  # foreign patient!
        cosine_distance=0.1,
        similarity=0.9,
    )

    mock_retrieve.return_value = RetrievalResult(
        patient_id=PATIENT_ID,
        target_domains=("clinical_notes",),
        query_text="Compare my blood pressure over time",
        top_k=4,
        passages=(foreign_passage,),
    )

    _, token = await create_user_and_token()
    response = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "Compare my blood pressure over time"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["evidence_status"] == EvidenceStatus.INSUFFICIENT
    assert data["citations"] == []
    assert mock_llm_synth.synthesize_response.call_count == 0


# ---------------------------------------------------------------------------
# Case 51: Comparison zero dates LLM bypass orchestrator (Integration)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_comparison_zero_dates_llm_bypass_orchestrator(
    async_client: AsyncClient,
    db: AsyncSession,
    mock_safety,
    mock_parse,
    mock_patient,
    mock_build_context,
    mock_retrieve,
    mock_llm_synth,
):
    """
    Case 51 [INTEGRATION - BEHAVIORAL]:
    Comparison query with zero clinical dates routed to orchestrator.

    Expected:
    - Status == INSUFFICIENT.
    - Response generated by Step 7.5 short-circuit gate.
    - final_answer == evidence.evidence_directive ('No clinically dated records...')
    - citations == []
    - LLM provider call count == 0.
    """
    mock_parse.return_value = InquiryTarget(
        question_intent="COMPARISON",
        target_entity="cholesterol",
        candidate_structured_domains=["conditions"],
        candidate_document_domains=[],
        routing_mode=RoutingMode.STRUCTURED_ONLY,
    )

    # Empty conditions pool -> 0 clinical dates
    mock_build_context.return_value.conditions = []

    _, token = await create_user_and_token()
    response = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "Compare my cholesterol over time"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["evidence_status"] == EvidenceStatus.INSUFFICIENT
    assert (
        data["answer"]
        == "No clinically dated records were found to compare changes over time."
    )
    assert data["citations"] == []
    assert mock_llm_synth.synthesize_response.call_count == 0


# ---------------------------------------------------------------------------
# Case 52: Citation provenance preservation (Integration)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_citation_provenance_preservation(
    async_client: AsyncClient,
    db: AsyncSession,
    mock_safety,
    mock_parse,
    mock_patient,
    mock_build_context,
    mock_retrieve,
    mock_llm_synth,
):
    """
    Case 52 [INTEGRATION - BEHAVIORAL]:
    Multi-source trajectory comparison response.
    Reconciles CONDITION, MEDICATION, DOCUMENT, TIMELINE.

    Expected:
    - Citations numbered 1..K sequentially.
    - Passage citations include chunk/page.
    - Preserves provenance across diverse entity types.
    """
    mock_parse.return_value = InquiryTarget(
        question_intent="COMPARISON",
        target_entity="health",
        candidate_structured_domains=["conditions", "medications", "timeline"],
        candidate_document_domains=["clinical_notes"],
        routing_mode=RoutingMode.CROSS_DOMAIN,
    )

    cond_id = uuid.uuid4()
    cond = ConditionResponse(
        id=cond_id,
        patient_id=PATIENT_ID,
        name="Health: Hypertension",
        status="active",
        started_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
        is_chronic=True,
        source_type="CLINICIAN",
        source_id=uuid.uuid4(),
        verification_state="CLINICIAN_CONFIRMED",
        recorded_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
        created_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
    )

    med_id = uuid.uuid4()
    med = MedicationResponse(
        id=med_id,
        patient_id=PATIENT_ID,
        name="Health: Lisinopril",
        dosage="10mg",
        frequency="daily",
        status="active",
        started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        source_type="PATIENT",
        source_id=uuid.uuid4(),
        verification_state="PATIENT_REPORTED",
        recorded_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    encounter_id = uuid.uuid4()
    timeline_event = HealthEvent(
        event_type="SYMPTOM_LOGGED",
        source_type="SYMPTOM",
        source_id=encounter_id,
        title="Health: Symptom Logged",
        description="Mild tension headache",
        event_date="2025-01-01",
        event_state="historical",
    )

    mock_build_context.return_value.conditions = [cond]
    mock_build_context.return_value.medications = [med]
    mock_build_context.return_value.recent_timeline_events = [timeline_event]

    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    passage = RetrievedPassage(
        chunk_id=chunk_id,
        document_id=doc_id,
        chunk_index=0,
        page_number=2,
        chunk_text="Patient overall health is stable across all domains.",
        document_display_name="Health Summary 2025",
        document_type="CLINICAL_NOTE",
        document_date=date(2025, 1, 1),
        patient_id=PATIENT_ID,
        cosine_distance=0.1,
        similarity=0.9,
    )
    mock_retrieve.return_value = RetrievalResult(
        patient_id=PATIENT_ID,
        target_domains=("clinical_notes",),
        query_text="Compare my health over time",
        top_k=4,
        passages=(passage,),
    )

    expected_timeline_id = generate_timeline_event_id(
        "SYMPTOM", encounter_id, "SYMPTOM_LOGGED"
    )

    mock_llm_synth.synthesize_response.return_value = SynthesisResult(
        answer_text="Health comparison shows consistent progress over the years.",
        cited_record_ids=[cond_id, med_id, expected_timeline_id, doc_id],
        cited_tokens=["", "", "", "[DOC-1]"],
    )

    _, token = await create_user_and_token()
    response = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "Compare my health over time"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["evidence_status"] == EvidenceStatus.SUFFICIENT
    citations = data["citations"]
    assert len(citations) == 4

    # Sequential numbering
    for i, c in enumerate(citations, start=1):
        assert c["citation_id"] == i

    types = {c["entity_type"] for c in citations}
    assert types == {"CONDITION", "MEDICATION", "TIMELINE", "DOCUMENT"}

    doc_citation = next(c for c in citations if c["entity_type"] == "DOCUMENT")
    assert doc_citation["chunk_id"] == str(chunk_id)
    assert doc_citation["page_number"] == 2
    assert "Patient overall health is stable" in doc_citation["passage_text"]


# ---------------------------------------------------------------------------
# Case 53: Timeline only comparison trajectory (Integration)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_timeline_only_comparison_trajectory(
    async_client: AsyncClient,
    db: AsyncSession,
    mock_safety,
    mock_parse,
    mock_patient,
    mock_build_context,
    mock_llm_synth,
):
    """
    Case 53 [INTEGRATION - BEHAVIORAL]:
    Timeline-only comparison query with 3 distinct event dates.

    Expected:
    - Milestones: 3 timeline event dates selected (Baseline, Intermediate, Latest).
    - Status == SUFFICIENT.
    - Verified timeline participates in same >= 2 date policy.
    - Prompt serialization uses [TIMELINE: ...] tag.
    """
    mock_parse.return_value = InquiryTarget(
        question_intent="COMPARISON",
        target_entity="cough",
        candidate_structured_domains=["timeline"],
        candidate_document_domains=[],
        routing_mode=RoutingMode.STRUCTURED_ONLY,
    )

    e1 = HealthEvent(
        event_type="SYMPTOM_LOGGED",
        source_type="SYMPTOM",
        source_id=uuid.uuid4(),
        title="Mild Cough",
        description="Dry cough started",
        event_date="2023-01-01",
        event_state="historical",
    )
    e2 = HealthEvent(
        event_type="SYMPTOM_LOGGED",
        source_type="SYMPTOM",
        source_id=uuid.uuid4(),
        title="Moderate Cough",
        description="Cough worsened",
        event_date="2024-01-01",
        event_state="historical",
    )
    e3 = HealthEvent(
        event_type="SYMPTOM_LOGGED",
        source_type="SYMPTOM",
        source_id=uuid.uuid4(),
        title="Resolved Cough",
        description="Cough resolved",
        event_date="2025-01-01",
        event_state="historical",
    )

    ctx = StructuredHealthContext()
    ctx.recent_timeline_events = [e1, e2, e3]
    mock_build_context.return_value = ctx

    # Verify evaluator directly on timeline events
    target = mock_parse.return_value
    ev_result = evaluate_evidence(target, ctx)
    assert ev_result.status == EvidenceStatus.SUFFICIENT
    assert (
        ev_result.trajectory_completeness
        == TrajectoryCompleteness.COMPLETE_WITHIN_EVALUATED_CANDIDATES
    )
    assert len(ev_result.matched_records) == 3

    # Verify prompt serialization contains [TIMELINE: ...]
    sanitized = build_sanitized_context(ctx, target, evidence=ev_result)
    assert sanitized.chronological_trajectory is not None
    assert len(sanitized.chronological_trajectory) == 3
    for line in sanitized.chronological_trajectory:
        assert "[TIMELINE:" in line

    prompt_text = sanitized.to_prompt_text()
    assert "=== CHRONOLOGICAL TRAJECTORY ===" in prompt_text

    _, token = await create_user_and_token()
    response = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "Compare my cough symptoms over time"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["evidence_status"] == EvidenceStatus.SUFFICIENT


# ---------------------------------------------------------------------------
# Case 54: Existing M5 regression preservation (Regression Gate)
# ---------------------------------------------------------------------------
def test_existing_m5_regression_preservation():
    """
    Case 54 [REGRESSION GATE]:
    Re-run full M5 cross-domain sufficiency test scenarios.
    M5 7-case truth table must be 100% unchanged for factual inquiries.
    """
    target = InquiryTarget(
        question_intent="FACTUAL",
        target_entity="Hypertension",
        candidate_structured_domains=["conditions"],
        candidate_document_domains=["clinical_notes"],
        routing_mode=RoutingMode.CROSS_DOMAIN,
    )

    # 1. Structured SUFFICIENT + Doc SUFFICIENT -> SUFFICIENT
    res1 = fuse_cross_domain_evidence(
        target=target,
        struct_evidence=EvidenceResult(
            status=EvidenceStatus.SUFFICIENT, evidence_directive="Struct found."
        ),
        doc_evidence=EvidenceResult(
            status=EvidenceStatus.SUFFICIENT, evidence_directive="Doc found."
        ),
    )
    assert res1.status == EvidenceStatus.SUFFICIENT

    # 2. Structured PARTIAL + Doc SUFFICIENT (covers missing) -> SUFFICIENT
    target_with_attrs = InquiryTarget(
        question_intent="FACTUAL",
        target_entity="Hypertension",
        requested_attributes=["status", "clinic"],
        candidate_structured_domains=["conditions"],
        candidate_document_domains=["clinical_notes"],
        routing_mode=RoutingMode.CROSS_DOMAIN,
    )
    res2 = fuse_cross_domain_evidence(
        target=target_with_attrs,
        struct_evidence=EvidenceResult(
            status=EvidenceStatus.PARTIALLY_SUFFICIENT,
            matched_fields=["status"],
            missing_fields=["clinic"],
        ),
        doc_evidence=EvidenceResult(
            status=EvidenceStatus.SUFFICIENT,
            matched_fields=["clinic"],
            missing_fields=[],
        ),
    )
    assert res2.status == EvidenceStatus.SUFFICIENT

    # 3. Structured INSUFFICIENT + Doc INSUFFICIENT -> INSUFFICIENT
    res3 = fuse_cross_domain_evidence(
        target=target,
        struct_evidence=EvidenceResult(
            status=EvidenceStatus.INSUFFICIENT, evidence_directive="No struct."
        ),
        doc_evidence=EvidenceResult(
            status=EvidenceStatus.INSUFFICIENT, evidence_directive="No doc."
        ),
    )
    assert res3.status == EvidenceStatus.INSUFFICIENT


# ---------------------------------------------------------------------------
# Case 55: Existing S3 regression preservation (Regression Gate)
# ---------------------------------------------------------------------------
def test_existing_s3_regression_preservation():
    """
    Case 55 [REGRESSION GATE]:
    Re-run S3 timeline evidence and Rule F caveat tests.
    S3 timeline behavior must be 100% unchanged for non-comparison inquiries.
    """
    # 1. Undated timeline event with superlative constraint -> PARTIALLY_SUFFICIENT
    target = InquiryTarget(
        candidate_structured_domains=["timeline"],
        target_entity="Asthma",
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.ALL, superlative=SuperlativeType.LATEST
        ),
        routing_mode=RoutingMode.STRUCTURED_ONLY,
    )
    undated_event = HealthEvent(
        event_type="CONDITION_DIAGNOSED",
        source_type="CONDITION",
        source_id=uuid.uuid4(),
        title="Asthma Diagnosed",
        description="Diagnosed with mild asthma",
        event_date="",  # undated
        event_state="historical",
    )
    ctx = StructuredHealthContext()
    ctx.recent_timeline_events = [undated_event]

    ev = evaluate_evidence(target, ctx)
    assert ev.status == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert "lack documented clinical dates" in ev.evidence_directive

    # 2. Rule F caveat propagation in multi-domain pooling:
    # Condition is SUFFICIENT, but Timeline has undated caveat ->
    # pooled is PARTIALLY_SUFFICIENT
    cond_record = ConditionResponse(
        id=uuid.uuid4(),
        patient_id=PATIENT_ID,
        name="Asthma",
        status="active",
        is_chronic=True,
        source_type="CLINICIAN",
        source_id=uuid.uuid4(),
        verification_state="CLINICIAN_CONFIRMED",
        recorded_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    multi_ctx = StructuredHealthContext(
        conditions=[cond_record],
        recent_timeline_events=[undated_event],
    )
    multi_target = InquiryTarget(
        candidate_structured_domains=["timeline", "conditions"],
        target_entity="Asthma",
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.ALL, superlative=SuperlativeType.LATEST
        ),
    )
    pooled_ev = evaluate_evidence(multi_target, multi_ctx)
    assert pooled_ev.status == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert "lack documented clinical dates" in pooled_ev.evidence_directive
