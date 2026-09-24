import time
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.db.models import Patient
from app.health.evidence_evaluator import EvidenceResult
from app.health.evidence_fusion import fuse_cross_domain_evidence
from app.health.query_understanding import parse_natural_language_query
from app.health.retrieval import RetrievedPassage
from app.health.safety_guardrails import evaluate_safety
from app.schemas.inquiry import EvidenceStatus, InquiryTarget, RoutingMode
from tests.eval.m5_benchmark_corpus import (
    M5_BENCHMARK_CORPUS,
    get_ambiguous_cases,
    get_invalid_temporal_cases,
    get_non_ambiguous_parser_cases,
    get_normal_routable_cases,
    get_parser_benchmark_cases,
    get_safety_cases,
    get_valid_temporal_cases,
)
from tests.test_health_inquiry_api import create_user_and_token

FIXED_REF_DATETIME = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


def test_layer1_parser_conformance():
    """
    Evaluates Layer 1 parser behavior, enforcing all metric gates.
    """
    start_time = time.time()
    parser_cases = get_parser_benchmark_cases()
    assert len(parser_cases) == 50
    assert len(M5_BENCHMARK_CORPUS) == 54

    routing_conformance_count = 0
    false_unroutable_count = 0
    clarification_recall_count = 0
    clarification_total_triggered = 0
    false_clarification_count = 0
    valid_temporal_count = 0
    invalid_temporal_count = 0

    ambiguous_cases = get_ambiguous_cases()
    normal_routable_cases = get_normal_routable_cases()
    non_ambiguous_cases = get_non_ambiguous_parser_cases()
    valid_temp_cases = get_valid_temporal_cases()
    invalid_temp_cases = get_invalid_temporal_cases()

    with patch("app.health.query_understanding.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_REF_DATETIME

        for case in parser_cases:
            target = parse_natural_language_query(case.query)

            # Check Routing Conformance
            if case.case_id in ("TMP-07", "TMP-08"):
                # Invalid temporal fail-closed contract per S5:
                # unroutable non-clarification
                if (
                    target.routing_mode == RoutingMode.UNROUTABLE
                    and not target.clarification_required
                ):
                    routing_conformance_count += 1
            else:
                # 48 standard non-safety cases: exact field-by-field equality
                if (
                    target.routing_mode == case.expected_routing_mode
                    and sorted(target.candidate_structured_domains)
                    == sorted(case.expected_structured_domains)
                    and sorted(target.candidate_document_domains)
                    == sorted(case.expected_document_domains)
                    and target.target_entity == case.expected_target_entity
                    and sorted(target.requested_attributes)
                    == sorted(case.expected_attributes)
                    and target.temporal_constraint.scope == case.expected_temporal_scope
                    and target.temporal_constraint.anchor_year
                    == case.expected_anchor_year
                    and target.temporal_constraint.start_date
                    == case.expected_start_date
                    and target.temporal_constraint.end_date == case.expected_end_date
                    and target.clarification_required
                    == case.expected_clarification_required
                ):
                    routing_conformance_count += 1

            if target.clarification_required:
                clarification_total_triggered += 1

            # Check False Unroutable
            if (
                case in normal_routable_cases
                and target.routing_mode == RoutingMode.UNROUTABLE
            ):
                false_unroutable_count += 1

            # Check Clarification Recall
            if case in ambiguous_cases and target.clarification_required:
                clarification_recall_count += 1

            # Check False Clarification
            if case in non_ambiguous_cases and target.clarification_required:
                false_clarification_count += 1

            # Check Valid Temporal Normalization
            if case in valid_temp_cases:
                if (
                    target.temporal_constraint.scope == case.expected_temporal_scope
                    and target.temporal_constraint.anchor_year
                    == case.expected_anchor_year
                    and target.temporal_constraint.start_date
                    == case.expected_start_date
                    and target.temporal_constraint.end_date == case.expected_end_date
                ):
                    valid_temporal_count += 1

            # Check Invalid Temporal Fail-Closed
            if case in invalid_temp_cases:
                if (
                    target.routing_mode == RoutingMode.UNROUTABLE
                    and not target.clarification_required
                ):
                    invalid_temporal_count += 1

    end_time = time.time()

    # Asserting Gates
    assert routing_conformance_count == 50, (
        f"Routing Conformance failed: {routing_conformance_count}/50"
    )
    assert false_unroutable_count == 0, (
        f"False Unroutable failed: "
        f"{false_unroutable_count}/{len(normal_routable_cases)}"
    )
    assert clarification_recall_count == 4, (
        f"Clarification Recall failed: {clarification_recall_count}/4"
    )
    assert clarification_total_triggered == 4, (
        f"Clarification Precision failed: 4/{clarification_total_triggered}"
    )
    assert false_clarification_count == 0, (
        f"False Clarification failed: "
        f"{false_clarification_count}/{len(non_ambiguous_cases)}"
    )
    assert valid_temporal_count == 6, (
        f"Valid Temporal Normalization failed: {valid_temporal_count}/6"
    )
    assert invalid_temporal_count == 2, (
        f"Invalid Temporal Fail-Closed failed: {invalid_temporal_count}/2"
    )

    elapsed_ms = (end_time - start_time) * 1000
    print(f"Layer 1 diagnostics: Parser benchmark took {elapsed_ms:.2f} ms")


def test_eval_deterministic_repeatability():
    """
    Runs parser and safety evaluations 3 times to ensure 100% deterministic outputs.
    """
    parser_cases = get_parser_benchmark_cases()
    safety_cases = get_safety_cases()

    with patch("app.health.query_understanding.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_REF_DATETIME

        for case in parser_cases:
            res1 = parse_natural_language_query(case.query)
            res2 = parse_natural_language_query(case.query)
            res3 = parse_natural_language_query(case.query)
            assert res1 == res2 == res3

        for case in safety_cases:
            res1 = evaluate_safety(case.query)
            res2 = evaluate_safety(case.query)
            res3 = evaluate_safety(case.query)
            assert res1.triggered == res2.triggered == res3.triggered
            assert (
                res1.advisory_message == res2.advisory_message == res3.advisory_message
            )


def _make_target(has_attrs: bool = False) -> InquiryTarget:
    return InquiryTarget(
        candidate_structured_domains=["conditions"],
        candidate_document_domains=["clinical_notes"],
        target_entity="Diabetes",
        requested_attributes=["status", "notes"] if has_attrs else [],
        routing_mode=RoutingMode.CROSS_DOMAIN,
    )


def _make_struct(
    status: EvidenceStatus, records=None, matched_fields=None
) -> EvidenceResult:
    return EvidenceResult(
        status=status,
        matched_records=records or [],
        matched_fields=matched_fields or [],
        evidence_directive=f"Structured: {status.value}",
    )


def _make_doc(
    status: EvidenceStatus, passages=None, matched_fields=None
) -> EvidenceResult:
    return EvidenceResult(
        status=status,
        matched_records=[],
        matched_fields=matched_fields or [],
        evidence_directive=f"Document: {status.value}",
        qualified_passages=passages or [],
    )


class DummyRecord:
    def __init__(self):
        self.id = uuid.uuid4()


def _make_passage() -> RetrievedPassage:
    return RetrievedPassage(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        patient_id=uuid.uuid4(),
        page_number=1,
        document_date=date.today(),
        chunk_index=0,
        chunk_text="Patient has diabetes.",
        document_display_name="Note",
        document_type="clinical_notes",
        cosine_distance=0.1,
        similarity=0.9,
    )


def test_layer2_pure_fusion_truth_table():
    """
    Asserts the exact S4 seven-case fusion truth table, contradiction coexistence.
    """
    # 1. Complementary Sufficiency
    t1 = _make_target(has_attrs=True)
    f1 = fuse_cross_domain_evidence(
        t1,
        _make_struct(EvidenceStatus.PARTIALLY_SUFFICIENT, [DummyRecord()], ["status"]),
        _make_doc(EvidenceStatus.PARTIALLY_SUFFICIENT, [_make_passage()], ["notes"]),
    )
    assert f1.status == EvidenceStatus.SUFFICIENT
    assert f1.evidence_directive == "All requested information is recorded."

    # 2. Structured Dominant
    t2 = _make_target(has_attrs=False)
    f2 = fuse_cross_domain_evidence(
        t2,
        _make_struct(EvidenceStatus.SUFFICIENT, [DummyRecord()]),
        _make_doc(EvidenceStatus.INSUFFICIENT),
    )
    assert f2.status == EvidenceStatus.SUFFICIENT
    assert f2.evidence_directive == "Relevant records found."

    # 3. Document Dominant
    t3 = _make_target(has_attrs=False)
    f3 = fuse_cross_domain_evidence(
        t3,
        _make_struct(EvidenceStatus.INSUFFICIENT),
        _make_doc(EvidenceStatus.SUFFICIENT, [_make_passage()]),
    )
    assert f3.status == EvidenceStatus.SUFFICIENT
    assert f3.evidence_directive == "Relevant records found."

    # 4. Partial in Both
    t4 = _make_target(has_attrs=True)
    f4 = fuse_cross_domain_evidence(
        t4,
        _make_struct(EvidenceStatus.PARTIALLY_SUFFICIENT, [DummyRecord()], ["status"]),
        _make_doc(EvidenceStatus.PARTIALLY_SUFFICIENT, [_make_passage()], ["status"]),
    )
    assert f4.status == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert (
        "Diabetes is recorded, but not found in records: notes" in f4.evidence_directive
    )

    # 5. Entity Present, All Attributes Missing
    t5 = _make_target(has_attrs=True)
    f5 = fuse_cross_domain_evidence(
        t5,
        _make_struct(EvidenceStatus.PARTIALLY_SUFFICIENT, [DummyRecord()], []),
        _make_doc(EvidenceStatus.PARTIALLY_SUFFICIENT, [_make_passage()], []),
    )
    assert f5.status == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert (
        "Diabetes is recorded, but not found in records: status, notes"
        in f5.evidence_directive
    )

    # 6. Entity Absent Everywhere
    t6 = _make_target(has_attrs=False)
    f6 = fuse_cross_domain_evidence(
        t6,
        _make_struct(EvidenceStatus.INSUFFICIENT),
        _make_doc(EvidenceStatus.INSUFFICIENT),
    )
    assert f6.status == EvidenceStatus.INSUFFICIENT
    assert (
        f6.evidence_directive
        == "Your records and documents do not contain a record of: Diabetes."
    )

    # 7. Attribute-Only Absent Everywhere
    t7 = InquiryTarget(
        candidate_structured_domains=["conditions"],
        candidate_document_domains=["clinical_notes"],
        target_entity=None,
        requested_attributes=["status"],
        routing_mode=RoutingMode.CROSS_DOMAIN,
    )
    f7 = fuse_cross_domain_evidence(
        t7,
        _make_struct(EvidenceStatus.INSUFFICIENT),
        _make_doc(EvidenceStatus.INSUFFICIENT),
    )
    assert f7.status == EvidenceStatus.INSUFFICIENT
    assert (
        "Your uploaded records were searched, but do not contain a record of: status"
        in f7.evidence_directive
    )

    # Contradiction Coexistence Invariant
    # Just verify that both sources of evidence are retained when combined.
    # The tests above implicitly do this: len(matched_records) + len(qualified_passages)
    assert len(f1.matched_records) == 1
    assert len(f1.qualified_passages) == 1


def test_layer2_anti_misattribution_defense():
    """
    Verifies that document attributes are not borrowed if the document
    does not confirm the entity.
    """
    t = _make_target(has_attrs=True)
    struct_evidence = _make_struct(
        EvidenceStatus.PARTIALLY_SUFFICIENT, [DummyRecord()], ["status"]
    )
    doc_evidence = _make_doc(EvidenceStatus.INSUFFICIENT, [_make_passage()], ["notes"])
    fused = fuse_cross_domain_evidence(t, struct_evidence, doc_evidence)
    assert fused.status == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert "notes" not in fused.matched_fields
    assert len(fused.qualified_passages) == 0


def test_layer2_temporal_window_qualification_defense():
    """
    Verifies S5 temporal-window qualification defense.
    Evaluated by directly simulating evaluate_passage_evidence.
    """
    from app.health.evidence_evaluator import evaluate_passage_evidence
    from app.schemas.inquiry import TemporalConstraint, TemporalScope

    target = InquiryTarget(
        candidate_structured_domains=[],
        candidate_document_domains=["clinical_notes"],
        target_entity=None,
        requested_attributes=[],
        routing_mode=RoutingMode.DOCUMENT_ONLY,
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.INTERVAL,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        ),
    )
    # create a passage outside the window
    passage = RetrievedPassage(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        patient_id=uuid.uuid4(),
        page_number=1,
        document_date=date(2021, 5, 10),
        chunk_index=0,
        chunk_text="Patient has diabetes.",
        document_display_name="Note",
        document_type="clinical_notes",
        cosine_distance=0.1,
        similarity=0.9,
    )

    from app.health.retrieval import RetrievalResult

    retrieval_res = RetrievalResult(
        patient_id=passage.patient_id,
        target_domains=("clinical_notes",),
        query_text="test",
        top_k=5,
        passages=(passage,),
    )

    res = evaluate_passage_evidence(
        target, retrieval_res, requesting_patient_id=passage.patient_id
    )
    assert res.status == EvidenceStatus.INSUFFICIENT
    assert len(res.qualified_passages) == 0


@pytest.fixture
def mock_dependencies():
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
        patch("app.api.health_inquiry.get_llm_gateway") as m_llm,
    ):
        m_pat.return_value = Patient(id=uuid.uuid4())

        from app.health.inquiry_context import StructuredHealthContext

        m_ctx.return_value = StructuredHealthContext()

        from app.health.retrieval import RetrievalResult

        m_ret.return_value = RetrievalResult(
            patient_id=uuid.uuid4(),
            target_domains=("clinical_notes",),
            query_text="test",
            top_k=5,
            passages=(),
        )

        mock_provider = AsyncMock()
        from app.core.llm import SynthesisResult

        mock_provider.synthesize_response.return_value = SynthesisResult(
            answer_text="Mocked Answer", cited_record_ids=[], cited_tokens=[]
        )
        m_llm.return_value = mock_provider

        yield m_pat, m_ctx, m_ret, mock_provider


@pytest.mark.asyncio
async def test_layer3_safety_precedence_zero_downstream_access(
    async_client: AsyncClient, mock_dependencies
):
    m_pat, m_ctx, m_ret, m_llm = mock_dependencies
    _, token = await create_user_and_token()

    for case in get_safety_cases():
        m_pat.reset_mock()
        m_ctx.reset_mock()
        m_ret.reset_mock()
        m_llm.synthesize_response.reset_mock()

        response = await async_client.post(
            "/api/v1/health-inquiry",
            json={"query": case.query},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "medical evaluation" in data["answer"].lower()
        assert data["citations"] == []

        assert m_pat.call_count == 0
        assert m_ctx.call_count == 0
        assert m_ret.call_count == 0
        assert m_llm.synthesize_response.call_count == 0


@pytest.mark.asyncio
async def test_layer3_ambiguity_unroutable_zero_database_access(
    async_client: AsyncClient, mock_dependencies
):
    m_pat, m_ctx, m_ret, m_llm = mock_dependencies
    _, token = await create_user_and_token()

    test_cases = list(get_ambiguous_cases()) + [
        case for case in M5_BENCHMARK_CORPUS if case.category == "Unroutable"
    ]

    for case in test_cases:
        m_ctx.reset_mock()
        m_ret.reset_mock()
        m_llm.synthesize_response.reset_mock()

        response = await async_client.post(
            "/api/v1/health-inquiry",
            json={"query": case.query},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["evidence_status"] == EvidenceStatus.INSUFFICIENT.value

        assert m_ctx.call_count == 0
        assert m_ret.call_count == 0
        assert m_llm.synthesize_response.call_count == 0


@pytest.mark.asyncio
async def test_layer3_document_only_context_skipping(
    async_client: AsyncClient, mock_dependencies
):
    m_pat, m_ctx, m_ret, m_llm = mock_dependencies
    _, token = await create_user_and_token()

    response = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "What is my physician name?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert m_ctx.call_count == 0
    assert m_ret.call_count == 1


@pytest.mark.asyncio
async def test_layer3_tenant_isolation_boundary(
    async_client: AsyncClient, mock_dependencies
):
    from app.health.evidence_evaluator import evaluate_passage_evidence

    target = InquiryTarget(
        candidate_structured_domains=[],
        candidate_document_domains=["clinical_notes"],
        target_entity=None,
        requested_attributes=[],
        routing_mode=RoutingMode.DOCUMENT_ONLY,
    )
    my_patient_id = uuid.uuid4()
    foreign_patient_id = uuid.uuid4()

    passage_foreign = RetrievedPassage(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        patient_id=foreign_patient_id,
        page_number=1,
        document_date=date.today(),
        chunk_index=0,
        chunk_text="Patient has diabetes.",
        document_display_name="Note",
        document_type="clinical_notes",
        cosine_distance=0.1,
        similarity=0.9,
    )

    from app.health.retrieval import RetrievalResult

    retrieval_res = RetrievalResult(
        patient_id=foreign_patient_id,
        target_domains=("clinical_notes",),
        query_text="test",
        top_k=5,
        passages=(passage_foreign,),
    )

    res = evaluate_passage_evidence(
        target, retrieval_res, requesting_patient_id=my_patient_id
    )
    assert len(res.qualified_passages) == 0


@pytest.mark.asyncio
async def test_layer3_citation_reconciliation(
    async_client: AsyncClient, mock_dependencies
):
    m_pat, m_ctx, m_ret, m_llm = mock_dependencies
    _, token = await create_user_and_token()

    rec_id_1 = uuid.uuid4()
    rec_id_2 = uuid.uuid4()

    class DummyCondition:
        def __init__(self, id_val):
            self.id = id_val
            self.name = "Diabetes Type 2"
            self.status = "ACTIVE"
            self.is_chronic = False
            self.started_at = None
            self.ended_at = None
            self.notes = ""
            self.verification_state = "PATIENT_REPORTED"

    m_ctx.return_value.conditions = [
        DummyCondition(rec_id_1),
        DummyCondition(rec_id_2),
    ]

    from app.core.llm import SynthesisResult

    m_llm.synthesize_response.return_value = SynthesisResult(
        answer_text="Mocked Answer",
        cited_record_ids=[rec_id_1, rec_id_2, rec_id_1],
        cited_tokens=["[REC-1]", "[DOC-1]", "[REC-1]"],
    )

    # We do a CROSS_DOMAIN query
    response = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "Do I have diabetes based on notes and records?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    citations = data.get("citations", [])
    assert len(citations) == 2
    assert citations[0]["citation_id"] == 1
    assert citations[1]["citation_id"] == 2


@pytest.mark.asyncio
async def test_layer3_fail_closed_subsystem_errors(
    async_client: AsyncClient, mock_dependencies
):
    m_pat, m_ctx, m_ret, m_llm = mock_dependencies
    _, token = await create_user_and_token()

    m_ctx.side_effect = Exception("DB crash")

    response = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "What are my diagnosed conditions?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 500
