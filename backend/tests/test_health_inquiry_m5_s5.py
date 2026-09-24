import uuid
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.health.evidence_evaluator import (
    evaluate_evidence,
    evaluate_passage_evidence,
)
from app.health.inquiry_context import StructuredHealthContext
from app.health.retrieval import RetrievalResult, RetrievedPassage
from app.schemas.inquiry import (
    EvidenceStatus,
    InquiryTarget,
    RoutingMode,
    TemporalConstraint,
    TemporalScope,
)


@pytest.fixture
def mock_target_interval():
    return InquiryTarget(
        candidate_structured_domains=["conditions"],
        candidate_document_domains=[],
        target_entity="Hypertension",
        requested_attributes=[],
        routing_mode=RoutingMode.STRUCTURED_ONLY,
        temporal_scope=TemporalScope.INTERVAL,
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.INTERVAL,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            anchor_year=2024,
            raw_expression="in 2024",
        ),
    )


class MockCondition:
    def __init__(self, id, name, started_at=None, ended_at=None, status=None):
        self.id = id
        self.name = name
        self.started_at = started_at
        self.ended_at = ended_at
        self.status = status


class MockAllergy:
    def __init__(self, id, allergen, recorded_at=None):
        self.id = id
        self.allergen = allergen
        self.recorded_at = recorded_at


class MockSymptom:
    def __init__(self, id, name, started_at=None, ended_at=None):
        self.id = id
        self.name = name
        self.started_at = started_at
        self.ended_at = ended_at


class MockMedication:
    def __init__(
        self,
        id,
        name,
        dosage="10mg",
        frequency="daily",
        status="active",
        as_needed=False,
        started_at=None,
        ended_at=None,
        notes=None,
    ):
        self.id = id
        self.name = name
        self.dosage = dosage
        self.frequency = frequency
        self.status = status
        self.as_needed = as_needed
        self.started_at = started_at
        self.ended_at = ended_at
        self.notes = notes


def test_scenario_8_missing_started_at():
    # Condition missing started_at. Query "in 2024"
    context = StructuredHealthContext()
    context.conditions = [MockCondition(uuid.uuid4(), "Hypertension", started_at=None)]

    target = InquiryTarget(
        candidate_structured_domains=["conditions"],
        candidate_document_domains=[],
        target_entity="Hypertension",
        requested_attributes=[],
        routing_mode=RoutingMode.STRUCTURED_ONLY,
        temporal_scope=TemporalScope.INTERVAL,
        target_domain="conditions",
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.INTERVAL,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            anchor_year=2024,
            raw_expression="in 2024",
        ),
    )
    result = evaluate_evidence(target, context)

    # Expected: excluded, INSUFFICIENT
    assert result.status == EvidenceStatus.INSUFFICIENT
    assert len(result.matched_records) == 0


def test_scenario_9_missing_ended_at():
    # Med with started_at=2023, ended_at=None, active. Query "in 2024"
    context = StructuredHealthContext()
    context.conditions = [
        MockCondition(
            uuid.uuid4(),
            "Hypertension",
            started_at=datetime(2023, 6, 1),
            ended_at=None,
            status="active",
        )
    ]

    target = InquiryTarget(
        candidate_structured_domains=["conditions"],
        candidate_document_domains=[],
        target_entity="Hypertension",
        requested_attributes=[],
        routing_mode=RoutingMode.STRUCTURED_ONLY,
        temporal_scope=TemporalScope.INTERVAL,
        target_domain="conditions",
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.INTERVAL,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            anchor_year=2024,
            raw_expression="in 2024",
        ),
    )
    result = evaluate_evidence(target, context)

    # Expected: Qualified for 2024
    assert result.status == EvidenceStatus.SUFFICIENT
    assert len(result.matched_records) == 1


def test_scenario_10_ongoing_symptom_overlap():
    # Symptom with started_at=2023, ended_at=None.
    # Query 2024. Expected: Qualified for 2024
    target = InquiryTarget(
        candidate_structured_domains=["symptoms"],
        candidate_document_domains=[],
        target_entity="Cough",
        requested_attributes=[],
        routing_mode=RoutingMode.STRUCTURED_ONLY,
        temporal_scope=TemporalScope.INTERVAL,
        target_domain="symptoms",
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.INTERVAL,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            anchor_year=2024,
            raw_expression="in 2024",
        ),
    )

    context = StructuredHealthContext()
    context.symptoms = [
        MockSymptom(uuid.uuid4(), "Cough", started_at=datetime(2023, 1, 1))
    ]

    result = evaluate_evidence(target, context)
    assert result.status == EvidenceStatus.SUFFICIENT
    assert len(result.matched_records) == 1


def test_scenario_11_scope_all_undated_doc():
    # Query "What is my physician name?". Expected: ALL, undated doc retrieved normally.
    target = InquiryTarget(
        candidate_structured_domains=[],
        candidate_document_domains=["clinical_documents"],
        target_entity=None,
        requested_attributes=["physician_name"],
        routing_mode=RoutingMode.DOCUMENT_ONLY,
        temporal_scope=TemporalScope.ALL,
    )

    patient_id = uuid.uuid4()
    p1 = RetrievedPassage(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        patient_id=patient_id,
        chunk_index=0,
        page_number=1,
        chunk_text="Dr. Smith is the attending physician.",
        document_display_name="Doc 1",
        document_type="clinical_documents",
        document_date=None,  # Undated
        cosine_distance=0.1,
        similarity=0.9,
    )

    retrieval_result = RetrievalResult(
        patient_id=patient_id,
        target_domains={"clinical_documents"},
        query_text="What is my physician name?",
        top_k=5,
        passages=(p1,),
    )

    result = evaluate_passage_evidence(target, retrieval_result, patient_id)
    assert result.status == EvidenceStatus.SUFFICIENT
    assert len(result.qualified_passages) == 1


def test_scenario_12_scope_current_undated_doc():
    # Query "What medicines am I currently taking?".
    # Locked S5 contract:
    # - TemporalScope.CURRENT performs NO chronological document-date filtering.
    # - An undated document (document_date=None) remains eligible under existing
    #   retrieval/evidence behavior.
    # - document_date=None is NOT proof of current clinical time.
    # - S5 must not exclude the document merely because it is undated.
    target = InquiryTarget(
        candidate_structured_domains=[],
        candidate_document_domains=["clinical_documents"],
        target_entity="Lisinopril",
        requested_attributes=[],
        routing_mode=RoutingMode.DOCUMENT_ONLY,
        temporal_scope=TemporalScope.CURRENT,
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.CURRENT,
            raw_expression="currently",
        ),
    )

    patient_id = uuid.uuid4()
    p1 = RetrievedPassage(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        patient_id=patient_id,
        chunk_index=0,
        page_number=1,
        chunk_text="Prescribed Lisinopril 10mg daily.",
        document_display_name="Doc 1",
        document_type="clinical_documents",
        document_date=None,  # Undated document
        cosine_distance=0.1,
        similarity=0.9,
    )

    retrieval_result = RetrievalResult(
        patient_id=patient_id,
        target_domains={"clinical_documents"},
        query_text="What medicines am I currently taking?",
        top_k=5,
        passages=(p1,),
    )

    result = evaluate_passage_evidence(target, retrieval_result, patient_id)
    # Undated doc remains eligible under existing behavior for CURRENT
    assert result.status == EvidenceStatus.SUFFICIENT
    assert len(result.qualified_passages) == 1
    assert result.qualified_passages[0].chunk_id == p1.chunk_id


def test_scenario_13_scope_interval_undated_doc():
    # Query 2024. Expected: INTERVAL, undated doc excluded by SQL and evaluator.
    target = InquiryTarget(
        candidate_structured_domains=[],
        candidate_document_domains=["clinical_documents"],
        target_entity=None,
        requested_attributes=["physician_name"],
        routing_mode=RoutingMode.DOCUMENT_ONLY,
        temporal_scope=TemporalScope.INTERVAL,
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.INTERVAL,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            anchor_year=2024,
            raw_expression="in 2024",
        ),
    )

    patient_id = uuid.uuid4()
    p1 = RetrievedPassage(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        patient_id=patient_id,
        chunk_index=0,
        page_number=1,
        chunk_text="Dr. Smith is the attending physician.",
        document_display_name="Doc 1",
        document_type="clinical_documents",
        document_date=None,  # Undated! Defense in depth exclusion
        cosine_distance=0.1,
        similarity=0.9,
    )

    retrieval_result = RetrievalResult(
        patient_id=patient_id,
        target_domains={"clinical_documents"},
        query_text="physician name in 2024",
        top_k=5,
        passages=(p1,),
    )

    result = evaluate_passage_evidence(target, retrieval_result, patient_id)

    assert result.status == EvidenceStatus.INSUFFICIENT
    assert len(result.qualified_passages) == 0


def test_scenario_15_historical_allergy_interval():
    # "What allergies did I have in 2024?".
    # Expected: INTERVAL, yields INSUFFICIENT for interval
    target = InquiryTarget(
        candidate_structured_domains=["allergies"],
        candidate_document_domains=[],
        target_entity="Peanut",
        requested_attributes=[],
        routing_mode=RoutingMode.STRUCTURED_ONLY,
        temporal_scope=TemporalScope.INTERVAL,
        target_domain="allergies",
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.INTERVAL,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            anchor_year=2024,
            raw_expression="in 2024",
        ),
    )

    context = StructuredHealthContext()
    context.allergies = [
        MockAllergy(uuid.uuid4(), "Peanut", recorded_at=datetime(2023, 1, 1))
    ]

    result = evaluate_evidence(target, context)

    assert result.status == EvidenceStatus.INSUFFICIENT
    assert "presence during in 2024 is unverified" in result.evidence_directive


@patch("app.api.health_inquiry.evaluate_safety")
@patch("app.api.health_inquiry.get_or_create_patient")
@patch("app.api.health_inquiry.retrieve_document_passages")
@patch("app.api.health_inquiry.build_inquiry_context")
@pytest.mark.asyncio
async def test_scenario_16_shared_interval_cross_domain(
    mock_build_ctx, mock_retrieve, mock_get_pat, mock_safety
):
    from app.api.health_inquiry import submit_health_inquiry
    from app.core.auth import AuthenticatedUser
    from app.health.query_understanding import parse_natural_language_query
    from app.schemas.inquiry import HealthInquiryRequest, SafetyGuardrailState

    mock_safety.return_value = SafetyGuardrailState(triggered=False)

    query_str = "What medications was I taking in 2023?"

    # Verify query parsing produces one canonical TemporalConstraint
    target = parse_natural_language_query(query_str)
    assert target.temporal_scope == TemporalScope.INTERVAL
    assert target.temporal_constraint is not None
    assert target.temporal_constraint.start_date == date(2023, 1, 1)
    assert target.temporal_constraint.end_date == date(2023, 12, 31)
    assert target.temporal_constraint.anchor_year == 2023
    assert target.routing_mode == RoutingMode.CROSS_DOMAIN

    patient_id = uuid.uuid4()
    patient = MagicMock()
    patient.id = patient_id
    mock_get_pat.return_value = patient

    # 1. Structured domain context: build_inquiry_context provides all records
    # (domain-scoped, without temporal filtering applied by build_inquiry_context)
    context = StructuredHealthContext()
    # Med 1: active across 2023 (started 2022, ended 2024) -> overlaps interval
    med_qualifying = MockMedication(
        uuid.uuid4(),
        "Lisinopril",
        started_at=datetime(2022, 1, 1),
        ended_at=datetime(2024, 1, 1),
        status="active",
    )
    # Med 2: started 2025 -> outside 2023 window -> excluded by evidence_evaluator
    med_out_of_window = MockMedication(
        uuid.uuid4(),
        "Metformin",
        started_at=datetime(2025, 1, 1),
        ended_at=None,
        status="active",
    )
    context.medications = [med_qualifying, med_out_of_window]
    mock_build_ctx.return_value = context

    # 2. Document domain: retrieve_document_passages receives start_date/end_date
    passage_2023 = RetrievedPassage(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        patient_id=patient_id,
        chunk_index=0,
        page_number=1,
        chunk_text="Prescription for Lisinopril 10mg daily filled in October 2023.",
        document_display_name="Prescription Record 2023",
        document_type="prescriptions",
        document_date=date(2023, 10, 15),
        cosine_distance=0.1,
        similarity=0.9,
    )
    mock_retrieve.return_value = RetrievalResult(
        patient_id=patient_id,
        target_domains=("prescriptions",),
        query_text=query_str,
        top_k=20,
        passages=(passage_2023,),
    )

    mock_llm = MagicMock()
    synthesis = MagicMock()
    synthesis.answer_text = "You were taking Lisinopril in 2023."
    synthesis.cited_record_ids = []
    synthesis.cited_tokens = []
    mock_llm.synthesize_response = AsyncMock(return_value=synthesis)

    request = HealthInquiryRequest(query=query_str)
    user = AuthenticatedUser(
        id=str(patient_id),
        email="patient@test.com",
        role="authenticated",
        full_name="Test Patient",
    )

    res = await submit_health_inquiry(request, user, AsyncMock(), mock_llm)

    # Verify build_inquiry_context called with candidate domains and NO temporal args
    mock_build_ctx.assert_awaited_once_with(
        mock_build_ctx.call_args[0][0],
        patient_id,
        domains=["medications"],
    )

    # Verify retrieve_document_passages received identical canonical interval bounds
    mock_retrieve.assert_awaited_once_with(
        db=mock_retrieve.call_args.kwargs["db"],
        patient_id=patient_id,
        query_text=query_str,
        target_domains=["prescriptions"],
        start_date=date(2023, 1, 1),
        end_date=date(2023, 12, 31),
    )

    # Both channels independently qualified and fused cleanly
    assert res.evidence_status == EvidenceStatus.SUFFICIENT
    assert res.answer == "You were taking Lisinopril in 2023."


def test_scenario_17_out_of_window_exclusion():
    # Query 2024, patient only has 2021 docs.
    # Expected: empty retrieval, INSUFFICIENT with timeframe directive.
    target = InquiryTarget(
        candidate_structured_domains=[],
        candidate_document_domains=["clinical_documents"],
        target_entity=None,
        requested_attributes=["physician_name"],
        routing_mode=RoutingMode.DOCUMENT_ONLY,
        temporal_scope=TemporalScope.INTERVAL,
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.INTERVAL,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            anchor_year=2024,
            raw_expression="in 2024",
        ),
    )

    patient_id = uuid.uuid4()
    p1 = RetrievedPassage(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        patient_id=patient_id,
        chunk_index=0,
        page_number=1,
        chunk_text="Dr. Smith is the attending physician.",
        document_display_name="Doc 1",
        document_type="clinical_documents",
        document_date=date(2021, 5, 5),  # Out of window (2021)
        cosine_distance=0.1,
        similarity=0.9,
    )

    retrieval_result = RetrievalResult(
        patient_id=patient_id,
        target_domains={"clinical_documents"},
        query_text="physician name in 2024",
        top_k=5,
        passages=(p1,),
    )
    result = evaluate_passage_evidence(target, retrieval_result, patient_id)

    assert result.status == EvidenceStatus.INSUFFICIENT
    assert len(result.qualified_passages) == 0
    assert "in 2024" in result.evidence_directive


def test_scenario_18_tenant_isolation():
    # Patient A queries 2024, Patient B has 2024 docs.
    # Expected: zero cross-tenant leakage.
    target = InquiryTarget(
        candidate_structured_domains=[],
        candidate_document_domains=["clinical_documents"],
        target_entity=None,
        requested_attributes=["physician_name"],
        routing_mode=RoutingMode.DOCUMENT_ONLY,
        temporal_scope=TemporalScope.INTERVAL,
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.INTERVAL,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            anchor_year=2024,
            raw_expression="in 2024",
        ),
    )

    patient_a = uuid.uuid4()
    patient_b = uuid.uuid4()

    p1 = RetrievedPassage(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        patient_id=patient_b,  # Document belongs to Patient B
        chunk_index=0,
        page_number=1,
        chunk_text="Dr. Smith is the attending physician.",
        document_display_name="Doc 1",
        document_type="clinical_documents",
        document_date=date(2024, 5, 5),
        cosine_distance=0.1,
        similarity=0.9,
    )

    retrieval_result = RetrievalResult(
        patient_id=patient_a,  # But search executed by Patient A
        target_domains={"clinical_documents"},
        query_text="physician name in 2024",
        top_k=5,
        passages=(p1,),
    )

    result = evaluate_passage_evidence(target, retrieval_result, patient_a)

    assert result.status == EvidenceStatus.INSUFFICIENT
    assert len(result.qualified_passages) == 0


@patch("app.api.health_inquiry.evaluate_safety")
@patch("app.api.health_inquiry.parse_natural_language_query")
@patch("app.api.health_inquiry.get_or_create_patient")
@patch("app.api.health_inquiry.retrieve_document_passages")
@patch("app.api.health_inquiry.build_inquiry_context")
@pytest.mark.asyncio
async def test_scenario_19_deterministic_repeat(
    mock_build_ctx, mock_retrieve, mock_get_pat, mock_parse, mock_safety
):
    from app.api.health_inquiry import submit_health_inquiry
    from app.core.auth import AuthenticatedUser
    from app.schemas.inquiry import HealthInquiryRequest, SafetyGuardrailState

    mock_safety.return_value = SafetyGuardrailState(triggered=False)

    target = InquiryTarget(
        candidate_structured_domains=[],
        candidate_document_domains=["labs"],
        target_entity="Cholesterol",
        requested_attributes=[],
        routing_mode=RoutingMode.DOCUMENT_ONLY,
        temporal_scope=TemporalScope.INTERVAL,
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.INTERVAL,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30),
            anchor_year=2024,
            raw_expression="past 6 months",
        ),
    )
    mock_parse.return_value = target

    patient = MagicMock()
    patient.id = uuid.uuid4()
    mock_get_pat.return_value = patient

    passage = RetrievedPassage(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        patient_id=patient.id,
        chunk_index=0,
        page_number=1,
        chunk_text="Cholesterol is 180",
        document_display_name="Doc 1",
        document_type="labs",
        document_date=date(2024, 3, 1),
        cosine_distance=0.1,
        similarity=0.9,
    )

    mock_retrieve.return_value = RetrievalResult(
        patient_id=patient.id,
        target_domains={"labs"},
        query_text="past 6 months",
        top_k=5,
        passages=(passage,),
    )

    mock_llm = MagicMock()
    synthesis = MagicMock()
    synthesis.answer_text = "Your cholesterol is 180."
    synthesis.cited_record_ids = []
    synthesis.cited_tokens = []
    mock_llm.synthesize_response = AsyncMock(return_value=synthesis)

    request = HealthInquiryRequest(query="past 6 months")
    user = AuthenticatedUser(
        id=str(patient.id),
        email="test@test.com",
        role="authenticated",
        full_name="Test",
    )

    results = []
    for _ in range(100):
        res = await submit_health_inquiry(request, user, AsyncMock(), mock_llm)
        results.append(res)

    for res in results:
        assert res.answer == "Your cholesterol is 180."
        assert res.evidence_status == EvidenceStatus.SUFFICIENT
