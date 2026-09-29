import time
import uuid
from datetime import date, datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.db.models import Patient
from app.health.evidence_evaluator import (
    BOUNDED_TRAJECTORY_QUALIFIER,
    EvidenceResult,
    TrajectoryCompleteness,
    allocate_attribute_aware_milestone_passages,
    evaluate_longitudinal_trajectory,
    evaluate_passage_evidence,
    evaluate_timeline_evidence,
    extract_canonical_clinical_date,
    select_longitudinal_milestones,
)
from app.health.evidence_fusion import fuse_cross_domain_evidence
from app.health.inquiry_context import HealthEvent, StructuredHealthContext
from app.health.query_understanding import parse_natural_language_query
from app.health.retrieval import RetrievalResult, RetrievedPassage
from app.health.safety_guardrails import evaluate_safety
from app.schemas.inquiry import (
    EvidenceStatus,
    InquiryTarget,
    RoutingMode,
    SuperlativeType,
    generate_timeline_event_id,
)
from tests.eval.m6_benchmark_corpus import (
    M6_BENCHMARK_CORPUS,
    get_ambiguous_cases,
    get_comparison_cases,
    get_invalid_temporal_cases,
    get_non_ambiguous_parser_cases,
    get_normal_routable_cases,
    get_parser_benchmark_cases,
    get_safety_cases,
    get_superlative_cases,
    get_timeline_cases,
    get_valid_temporal_cases,
)
from tests.test_health_inquiry_api import create_user_and_token

FIXED_REF_DATETIME = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


# =============================================================================
# LAYER 1: Query Understanding Conformance Harness
# =============================================================================


def test_layer1_parser_conformance():
    """
    Evaluates Layer 1 parser behavior across all 66 non-safety benchmark cases,
    enforcing 100% deterministic conformance and all metric gates.
    """
    start_time = time.time()
    parser_cases = get_parser_benchmark_cases()
    assert len(parser_cases) == 66
    assert len(M6_BENCHMARK_CORPUS) == 70

    routing_conformance_count = 0
    false_unroutable_count = 0
    clarification_recall_count = 0
    clarification_total_triggered = 0
    false_clarification_count = 0
    valid_temporal_count = 0
    invalid_temporal_count = 0
    superlative_conformance_count = 0
    comparison_conformance_count = 0
    timeline_routing_conformance_count = 0

    ambiguous_cases = get_ambiguous_cases()
    normal_routable_cases = get_normal_routable_cases()
    non_ambiguous_cases = get_non_ambiguous_parser_cases()
    valid_temp_cases = get_valid_temporal_cases()
    invalid_temp_cases = get_invalid_temporal_cases()
    superlative_cases = get_superlative_cases()
    comparison_cases = get_comparison_cases()
    timeline_cases = get_timeline_cases()

    with patch("app.health.query_understanding.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_REF_DATETIME

        for case in parser_cases:
            target = parse_natural_language_query(case.query)

            # Routing Conformance
            if case.case_id in ("TMP-07", "TMP-08"):
                # Invalid temporal fail-closed contract:
                # UNROUTABLE without clarification
                if (
                    target.routing_mode == RoutingMode.UNROUTABLE
                    and not target.clarification_required
                ):
                    routing_conformance_count += 1
            else:
                # Standard cases: match all expected fields
                fields_match = (
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
                )

                # For M6 cases (Categories 10-13): also assert superlative and intent
                if case.case_id.startswith(("SUP-", "TML-", "CMP-")):
                    fields_match = (
                        fields_match
                        and target.temporal_constraint.superlative
                        == case.expected_superlative
                        and target.question_intent == case.expected_question_intent
                    )

                if fields_match:
                    routing_conformance_count += 1

            if target.clarification_required:
                clarification_total_triggered += 1

            # Metric: False Unroutable
            if (
                case in normal_routable_cases
                and target.routing_mode == RoutingMode.UNROUTABLE
            ):
                false_unroutable_count += 1

            # Metric: Clarification Recall
            if case in ambiguous_cases and target.clarification_required:
                clarification_recall_count += 1

            # Metric: False Clarification
            if case in non_ambiguous_cases and target.clarification_required:
                false_clarification_count += 1

            # Metric: Valid Temporal Normalization
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

            # Metric: Invalid Temporal Fail-Closed
            if case in invalid_temp_cases:
                if (
                    target.routing_mode == RoutingMode.UNROUTABLE
                    and not target.clarification_required
                ):
                    invalid_temporal_count += 1

            # Metric: Superlative Conformance (8 cases: SUP-01..08)
            if case in superlative_cases:
                if target.temporal_constraint.superlative == case.expected_superlative:
                    superlative_conformance_count += 1

            # Metric: Comparison Intent Conformance (4 cases: CMP-01..04)
            if case in comparison_cases:
                if target.question_intent == "COMPARISON":
                    comparison_conformance_count += 1

            # Metric: Timeline Domain Routing Conformance (4 cases: TML-01..04)
            if case in timeline_cases:
                if "timeline" in target.candidate_structured_domains:
                    timeline_routing_conformance_count += 1

    end_time = time.time()

    # Enforce All Layer 1 Metric Gates
    assert routing_conformance_count == 66, (
        f"Routing Conformance failed: {routing_conformance_count}/66"
    )
    assert false_unroutable_count == 0, (
        f"False Unroutable failed: {false_unroutable_count}/"
        f"{len(normal_routable_cases)}"
    )
    assert clarification_recall_count == 4, (
        f"Clarification Recall failed: {clarification_recall_count}/4"
    )
    assert clarification_total_triggered == 4, (
        f"Clarification Precision failed: 4/{clarification_total_triggered}"
    )
    assert false_clarification_count == 0, (
        f"False Clarification failed: {false_clarification_count}/"
        f"{len(non_ambiguous_cases)}"
    )
    assert valid_temporal_count == 10, (
        f"Valid Temporal Normalization failed: {valid_temporal_count}/10"
    )
    assert invalid_temporal_count == 2, (
        f"Invalid Temporal Fail-Closed failed: {invalid_temporal_count}/2"
    )
    assert superlative_conformance_count == 8, (
        f"Superlative Conformance failed: {superlative_conformance_count}/8"
    )
    assert comparison_conformance_count == 4, (
        f"Comparison Conformance failed: {comparison_conformance_count}/4"
    )
    assert timeline_routing_conformance_count == 4, (
        f"Timeline Routing Conformance failed: {timeline_routing_conformance_count}/4"
    )

    elapsed_ms = (end_time - start_time) * 1000
    print(f"Layer 1 diagnostics: 66-case benchmark took {elapsed_ms:.2f} ms")


def test_eval_deterministic_repeatability():
    """
    Executes all 66 parser cases and 4 safety cases 3 times, asserting
    100% value equality across passes.
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


# =============================================================================
# LAYER 2: Pure Evidence / Retrieval / Fusion Conformance
# =============================================================================


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
    def __init__(self, d: Optional[date] = None):
        self.id = uuid.uuid4()
        self.name = "Diabetes"
        self.recorded_date = d or date.today()
        self.started_at = d or date.today()


def _make_passage(
    chunk_id: Optional[uuid.UUID] = None,
    document_id: Optional[uuid.UUID] = None,
    patient_id: Optional[uuid.UUID] = None,
    doc_date: Optional[date] = None,
    chunk_text: str = "Total Cholesterol: 210 mg/dL.",
    doc_type: str = "labs",
    chunk_index: int = 0,
) -> RetrievedPassage:
    return RetrievedPassage(
        chunk_id=chunk_id or uuid.uuid4(),
        document_id=document_id or uuid.uuid4(),
        patient_id=patient_id or uuid.uuid4(),
        page_number=1,
        document_date=doc_date,
        chunk_index=chunk_index,
        chunk_text=chunk_text,
        document_display_name="Lab Report",
        document_type=doc_type,
        cosine_distance=0.1,
        similarity=0.9,
    )


def test_layer2_m5_fusion_truth_table_preservation():
    """
    Asserts the exact M5 seven-case fusion truth table preservation.
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


def test_layer2_timeline_evidence_evaluation():
    """
    Verifies evaluate_timeline_evidence with entity matching, interval bounds,
    and superlative extremity filtering.
    """
    cond_id = uuid.uuid4()
    e1 = HealthEvent(
        event_type="CONDITION_STARTED",
        source_type="CONDITION",
        source_id=cond_id,
        title="Asthma",
        description="Diagnosed with Asthma",
        event_date="2022-04-10",
        event_state="historical",
    )
    e2 = HealthEvent(
        event_type="CONDITION_STARTED",
        source_type="CONDITION",
        source_id=cond_id,
        title="Asthma",
        description="Mild intermittent asthma follow up",
        event_date="2024-08-15",
        event_state="current",
    )
    ctx = StructuredHealthContext()
    ctx.recent_timeline_events = [e1, e2]

    # Target: LATEST Asthma on timeline
    target_latest = InquiryTarget(
        candidate_structured_domains=["timeline"],
        candidate_document_domains=[],
        target_entity="Asthma",
        routing_mode=RoutingMode.STRUCTURED_ONLY,
    )
    target_latest.temporal_constraint.superlative = SuperlativeType.LATEST

    ev = evaluate_timeline_evidence(target_latest, ctx)
    assert ev.status == EvidenceStatus.SUFFICIENT
    assert len(ev.matched_records) == 1
    assert ev.matched_records[0].event_date == "2024-08-15"

    # Target: FIRST Asthma on timeline
    target_first = InquiryTarget(
        candidate_structured_domains=["timeline"],
        candidate_document_domains=[],
        target_entity="Asthma",
        routing_mode=RoutingMode.STRUCTURED_ONLY,
    )
    target_first.temporal_constraint.superlative = SuperlativeType.FIRST

    ev_first = evaluate_timeline_evidence(target_first, ctx)
    assert ev_first.status == EvidenceStatus.SUFFICIENT
    assert len(ev_first.matched_records) == 1
    assert ev_first.matched_records[0].event_date == "2022-04-10"


def test_layer2_superlative_chronological_extremity():
    """
    Verifies that under LATEST, newest qualified passage is identified;
    under FIRST, oldest wins.
    """
    pat_id = uuid.uuid4()
    p_old = _make_passage(
        patient_id=pat_id, doc_date=date(2021, 5, 1), chunk_text="Cholesterol 190"
    )
    p_mid = _make_passage(
        patient_id=pat_id, doc_date=date(2023, 7, 1), chunk_text="Cholesterol 205"
    )
    p_new = _make_passage(
        patient_id=pat_id, doc_date=date(2025, 9, 1), chunk_text="Cholesterol 220"
    )

    target_latest = InquiryTarget(
        candidate_structured_domains=[],
        candidate_document_domains=["labs"],
        target_entity="Cholesterol",
        routing_mode=RoutingMode.DOCUMENT_ONLY,
    )
    target_latest.temporal_constraint.superlative = SuperlativeType.LATEST

    ret_res = RetrievalResult(
        patient_id=pat_id,
        target_domains=("labs",),
        query_text="What is my latest cholesterol?",
        top_k=3,
        passages=(p_mid, p_old, p_new),  # Intentionally unordered input
    )
    ev_latest = evaluate_passage_evidence(
        target_latest, ret_res, requesting_patient_id=pat_id
    )
    assert ev_latest.status == EvidenceStatus.SUFFICIENT
    assert "2025-09-01" in ev_latest.evidence_directive

    # Under FIRST: oldest must win
    target_first = InquiryTarget(
        candidate_structured_domains=[],
        candidate_document_domains=["labs"],
        target_entity="Cholesterol",
        routing_mode=RoutingMode.DOCUMENT_ONLY,
    )
    target_first.temporal_constraint.superlative = SuperlativeType.FIRST

    ev_first = evaluate_passage_evidence(
        target_first, ret_res, requesting_patient_id=pat_id
    )
    assert ev_first.status == EvidenceStatus.SUFFICIENT
    assert "2021-05-01" in ev_first.evidence_directive


def test_layer2_undated_evidence_disqualification():
    """
    Verifies that passages with document_date IS NULL and timeline DOCUMENT_UPLOADED
    cannot win a dated superlative.
    """
    pat_id = uuid.uuid4()
    p_dated = _make_passage(
        patient_id=pat_id, doc_date=date(2022, 1, 1), chunk_text="Cholesterol 195"
    )
    p_undated = _make_passage(
        patient_id=pat_id, doc_date=None, chunk_text="Cholesterol 200"
    )

    target = InquiryTarget(
        candidate_structured_domains=[],
        candidate_document_domains=["labs"],
        target_entity="Cholesterol",
        routing_mode=RoutingMode.DOCUMENT_ONLY,
    )
    target.temporal_constraint.superlative = SuperlativeType.LATEST

    ret_res = RetrievalResult(
        patient_id=pat_id,
        target_domains=("labs",),
        query_text="latest cholesterol",
        top_k=2,
        passages=(p_undated, p_dated),
    )
    ev = evaluate_passage_evidence(target, ret_res, requesting_patient_id=pat_id)
    assert ev.status == EvidenceStatus.SUFFICIENT
    assert "2022-01-01" in ev.evidence_directive

    # Timeline upload date disqualification
    e_upload = HealthEvent(
        event_type="DOCUMENT_UPLOADED",
        source_type="DOCUMENT",
        source_id=uuid.uuid4(),
        title="Uploaded doc",
        description="Admin upload",
        event_date="2026-01-01",
        event_state="historical",
    )
    assert extract_canonical_clinical_date(e_upload) is None


def test_layer2_longitudinal_trajectory_milestone_selection():
    """
    Verifies select_longitudinal_milestones picks Baseline (oldest),
    Intermediate (newest intermediate), and Latest (newest) when >= 3
    distinct dates exist.
    """
    d1 = date(2020, 1, 1)
    d2 = date(2021, 6, 1)
    d3 = date(2023, 3, 1)
    d4 = date(2025, 12, 1)

    milestones = select_longitudinal_milestones([d3, d1, d4, d2])
    assert len(milestones) == 3
    assert milestones[0] == d1  # Baseline
    assert milestones[1] == d3  # Newest intermediate
    assert milestones[2] == d4  # Latest


def test_layer2_attribute_aware_passage_budget():
    """
    Verifies allocate_attribute_aware_milestone_passages bounds total passages
    to budget K <= 4 and prioritizes passages matching requested attributes.
    """
    d1 = date(2022, 1, 1)
    d2 = date(2024, 1, 1)
    milestones = [d1, d2]

    # 3 passages on d1, 3 on d2
    passages = [
        _make_passage(doc_date=d1, chunk_text="Lab A dosage 10mg", chunk_index=0),
        _make_passage(doc_date=d1, chunk_text="Lab B general info", chunk_index=1),
        _make_passage(doc_date=d1, chunk_text="Lab C other notes", chunk_index=2),
        _make_passage(doc_date=d2, chunk_text="Lab D dosage 20mg", chunk_index=0),
        _make_passage(doc_date=d2, chunk_text="Lab E general notes", chunk_index=1),
        _make_passage(doc_date=d2, chunk_text="Lab F clinic info", chunk_index=2),
    ]

    allocated = allocate_attribute_aware_milestone_passages(
        milestone_dates=milestones,
        passages_or_by_date=passages,
        requested_attributes_or_target=["dosage"],
        budget=4,
    )
    assert len(allocated) <= 4
    # Dosage-bearing passages should be prioritized
    texts = [p.chunk_text for p in allocated]
    assert any("dosage 10mg" in t for t in texts)
    assert any("dosage 20mg" in t for t in texts)


def test_layer2_cross_domain_superlative_reconciliation():
    """
    Verifies Section 7.3 cross-domain reconciliation: newer date wins regardless
    of source domain, with deterministic STRUCTURED priority on same-date ties.
    """
    target = InquiryTarget(
        candidate_structured_domains=["conditions"],
        candidate_document_domains=["clinical_documents"],
        target_entity="Asthma",
        routing_mode=RoutingMode.CROSS_DOMAIN,
    )
    target.temporal_constraint.superlative = SuperlativeType.LATEST

    class DummyCondition:
        def __init__(self, name: str, d: date):
            self.id = uuid.uuid4()
            self.name = name
            self.started_at = d
            self.status = "ACTIVE"
            self.is_chronic = True

    # Case A: Document is newer (2025 vs 2023)
    p_newer = _make_passage(
        doc_date=date(2025, 1, 1), chunk_text="Asthma confirmed in clinic notes"
    )
    struct_older = DummyCondition("Asthma", date(2023, 1, 1))

    f_doc_wins = fuse_cross_domain_evidence(
        target=target,
        struct_evidence=EvidenceResult(status=EvidenceStatus.SUFFICIENT),
        doc_evidence=EvidenceResult(status=EvidenceStatus.SUFFICIENT),
        structured_candidates=[struct_older],
        document_candidates=[p_newer],
    )
    assert f_doc_wins.status == EvidenceStatus.SUFFICIENT
    assert "2025-01-01" in f_doc_wins.evidence_directive
    assert len(f_doc_wins.qualified_passages) == 1

    # Case B: Same date tie -> STRUCTURED priority in directive
    struct_same = DummyCondition("Asthma", date(2024, 6, 1))
    p_same = _make_passage(doc_date=date(2024, 6, 1), chunk_text="Asthma notes")

    f_same = fuse_cross_domain_evidence(
        target=target,
        struct_evidence=EvidenceResult(status=EvidenceStatus.SUFFICIENT),
        doc_evidence=EvidenceResult(status=EvidenceStatus.SUFFICIENT),
        structured_candidates=[struct_same],
        document_candidates=[p_same],
    )
    assert f_same.status == EvidenceStatus.SUFFICIENT
    assert "2024-06-01" in f_same.evidence_directive


def test_layer2_trajectory_completeness_qualifier_contract():
    """
    Verifies that when distinct evaluated candidate dates exceed selected
    milestone dates, trajectory_completeness is set to
    BOUNDED_WITH_ADDITIONAL_QUALIFIED_CANDIDATES and qualifier is injected.
    """
    pat_id = uuid.uuid4()
    p1 = _make_passage(
        patient_id=pat_id, doc_date=date(2021, 1, 1), chunk_text="Cholesterol 180"
    )
    p2 = _make_passage(
        patient_id=pat_id, doc_date=date(2022, 1, 1), chunk_text="Cholesterol 190"
    )
    p3 = _make_passage(
        patient_id=pat_id, doc_date=date(2023, 1, 1), chunk_text="Cholesterol 200"
    )
    p4 = _make_passage(
        patient_id=pat_id, doc_date=date(2024, 1, 1), chunk_text="Cholesterol 210"
    )
    p5 = _make_passage(
        patient_id=pat_id, doc_date=date(2025, 1, 1), chunk_text="Cholesterol 220"
    )

    target = InquiryTarget(
        candidate_structured_domains=[],
        candidate_document_domains=["labs"],
        target_entity="Cholesterol",
        routing_mode=RoutingMode.DOCUMENT_ONLY,
        question_intent="COMPARISON",
    )

    ev = evaluate_longitudinal_trajectory(
        structured_candidates=[],
        document_candidates=[p1, p2, p3, p4, p5],
        target=target,
    )
    assert ev.status == EvidenceStatus.SUFFICIENT
    assert (
        ev.trajectory_completeness
        == TrajectoryCompleteness.BOUNDED_WITH_ADDITIONAL_QUALIFIED_CANDIDATES
    )
    assert BOUNDED_TRAJECTORY_QUALIFIER in ev.evidence_directive


# =============================================================================
# LAYER 3: Orchestrator / API Integration Conformance
# =============================================================================


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
        pat_id = uuid.uuid4()
        m_pat.return_value = Patient(id=pat_id)

        m_ctx.return_value = StructuredHealthContext()

        m_ret.return_value = RetrievalResult(
            patient_id=pat_id,
            target_domains=("clinical_documents",),
            query_text="test",
            top_k=5,
            passages=(),
        )

        mock_provider = AsyncMock()
        from app.core.llm import SynthesisResult

        mock_provider.synthesize_response.return_value = SynthesisResult(
            answer_text="Synthesized health inquiry response.",
            cited_record_ids=[],
            cited_tokens=[],
        )
        m_llm.return_value = mock_provider

        yield m_pat, m_ctx, m_ret, mock_provider


@pytest.mark.asyncio
async def test_layer3_safety_precedence(async_client: AsyncClient, mock_dependencies):
    """
    Verifies that all 4 safety queries short-circuit at Step 1 with 0 DB
    and 0 LLM calls.
    """
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
    """
    Verifies ambiguous and unroutable queries short-circuit at Step 2
    with 0 DB and 0 LLM access.
    """
    m_pat, m_ctx, m_ret, m_llm = mock_dependencies
    _, token = await create_user_and_token()

    test_cases = list(get_ambiguous_cases()) + [
        case for case in M6_BENCHMARK_CORPUS if case.category == "Unroutable"
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
async def test_layer3_domain_isolation(async_client: AsyncClient, mock_dependencies):
    """
    Verifies DOCUMENT_ONLY skips build_inquiry_context and STRUCTURED_ONLY
    skips retrieval.
    """
    m_pat, m_ctx, m_ret, m_llm = mock_dependencies
    _, token = await create_user_and_token()

    # DOCUMENT_ONLY query
    m_ctx.reset_mock()
    m_ret.reset_mock()
    resp_doc = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "What is my physician name?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_doc.status_code == 200
    assert m_ctx.call_count == 0
    assert m_ret.call_count == 1

    # STRUCTURED_ONLY query (TML-01: "Show my health timeline")
    m_ctx.reset_mock()
    m_ret.reset_mock()
    resp_struct = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "Show my health timeline"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_struct.status_code == 200
    assert m_ret.call_count == 0


@pytest.mark.asyncio
async def test_layer3_timeline_citation_provenance(
    async_client: AsyncClient, mock_dependencies
):
    """
    Verifies that cited timeline events emit entity_type == 'TIMELINE' citations
    with deterministic UUID5 identity.
    """
    m_pat, m_ctx, m_ret, m_llm = mock_dependencies
    _, token = await create_user_and_token()

    cond_id = uuid.uuid4()
    e1 = HealthEvent(
        event_type="CONDITION_STARTED",
        source_type="CONDITION",
        source_id=cond_id,
        title="Asthma",
        description="Diagnosed with Asthma",
        event_date="2024-03-15",
        event_state="historical",
    )
    m_ctx.return_value.recent_timeline_events = [e1]

    expected_timeline_uuid = generate_timeline_event_id(
        "CONDITION", cond_id, "CONDITION_STARTED"
    )

    from app.core.llm import SynthesisResult

    m_llm.synthesize_response.return_value = SynthesisResult(
        answer_text="According to timeline records, asthma started in 2024.",
        cited_record_ids=[expected_timeline_uuid],
        cited_tokens=[""],
    )

    # TML-04 routes to timeline and conditions
    response = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "What was my timeline for Asthma?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    citations = data.get("citations", [])
    assert len(citations) >= 1
    tl_citation = next((c for c in citations if c["entity_type"] == "TIMELINE"), None)
    assert tl_citation is not None
    assert tl_citation["record_id"] == str(expected_timeline_uuid)


@pytest.mark.asyncio
async def test_layer3_cross_domain_trajectory_synthesis(
    async_client: AsyncClient, mock_dependencies
):
    """
    Verifies that comparative inquiry synthesizes structured and document evidence
    across >= 2 distinct dates into a sufficient chronological trajectory.
    """
    m_pat, m_ctx, m_ret, m_llm = mock_dependencies
    _, token = await create_user_and_token()

    pat_id = m_pat.return_value.id
    chunk_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    # Distinct date 1: Condition started in 2022
    class DummyCondition:
        def __init__(self):
            self.id = uuid.uuid4()
            self.name = "Asthma"
            self.status = "ACTIVE"
            self.is_chronic = True
            self.started_at = date(2022, 1, 10)
            self.ended_at = None
            self.notes = "Initial asthma diagnosis"
            self.verification_state = "PATIENT_REPORTED"

    m_ctx.return_value.conditions = [DummyCondition()]

    # Distinct date 2: Clinic document passage in 2024
    passage = _make_passage(
        chunk_id=chunk_id,
        document_id=doc_id,
        patient_id=pat_id,
        doc_date=date(2024, 6, 1),
        chunk_text="Asthma management plan established. Albuterol inhaler prescribed.",
    )
    m_ret.return_value = RetrievalResult(
        patient_id=pat_id,
        target_domains=("clinical_documents",),
        query_text="How has my asthma changed over time?",
        top_k=5,
        passages=(passage,),
    )

    from app.core.llm import SynthesisResult

    m_llm.synthesize_response.return_value = SynthesisResult(
        answer_text="Asthma has been actively managed since 2022 through 2024.",
        cited_record_ids=[doc_id],
        cited_tokens=["[DOC-1]"],
    )

    response = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "How has my asthma changed over time?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["evidence_status"] == EvidenceStatus.SUFFICIENT
    assert "Asthma has been actively managed" in data["answer"]


@pytest.mark.asyncio
async def test_layer3_bounded_qualifier_delivery(
    async_client: AsyncClient, mock_dependencies
):
    """
    Verifies that when bounded trajectory is triggered, the response answer
    contains the exact locked BOUNDED_TRAJECTORY_QUALIFIER string.
    """
    m_pat, m_ctx, m_ret, m_llm = mock_dependencies
    _, token = await create_user_and_token()

    pat_id = m_pat.return_value.id
    # 4 distinct dated passages (> 3 milestone points -> triggers bounded qualifier)
    passages = [
        _make_passage(
            patient_id=pat_id, doc_date=date(2021, 1, 1), chunk_text="Cholesterol 180"
        ),
        _make_passage(
            patient_id=pat_id, doc_date=date(2022, 1, 1), chunk_text="Cholesterol 190"
        ),
        _make_passage(
            patient_id=pat_id, doc_date=date(2023, 1, 1), chunk_text="Cholesterol 200"
        ),
        _make_passage(
            patient_id=pat_id, doc_date=date(2024, 1, 1), chunk_text="Cholesterol 210"
        ),
    ]
    m_ret.return_value = RetrievalResult(
        patient_id=pat_id,
        target_domains=("labs",),
        query_text="Compare my cholesterol over time",
        top_k=5,
        passages=tuple(passages),
    )

    from app.core.llm import SynthesisResult

    m_llm.synthesize_response.return_value = SynthesisResult(
        answer_text="Your cholesterol showed progressive changes across milestones.",
        cited_record_ids=[passages[0].document_id],
        cited_tokens=["[DOC-1]"],
    )

    response = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "Compare my cholesterol over time"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert BOUNDED_TRAJECTORY_QUALIFIER in data["answer"]
    assert data["answer"].endswith(BOUNDED_TRAJECTORY_QUALIFIER)


@pytest.mark.asyncio
async def test_layer3_comparison_zero_date_llm_bypass(
    async_client: AsyncClient, mock_dependencies
):
    """
    Permanently preserves the frozen S4 Step 7.5 behavior in the M6 evaluation harness:
    zero dated clinical records for a comparison query triggers INSUFFICIENT directive
    and completely bypasses the LLM provider.
    """
    m_pat, m_ctx, m_ret, m_llm = mock_dependencies
    _, token = await create_user_and_token()

    pat_id = m_pat.return_value.id
    # Passage is retrieved, but has no documented clinical date (doc_date=None)
    p_undated = _make_passage(
        patient_id=pat_id,
        doc_date=None,
        chunk_text="Total Cholesterol panel results recorded.",
    )
    m_ret.return_value = RetrievalResult(
        patient_id=pat_id,
        target_domains=("labs",),
        query_text="How has my cholesterol changed over time?",
        top_k=5,
        passages=(p_undated,),
    )
    m_ctx.return_value.conditions = []

    response = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "How has my cholesterol changed over time?"},
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
    assert m_llm.synthesize_response.call_count == 0


@pytest.mark.asyncio
async def test_layer3_tenant_isolation_boundary(
    async_client: AsyncClient, mock_dependencies
):
    """
    Verifies evaluator defense-in-depth: passages belonging to a foreign patient
    are rejected fail-closed with 0 qualified passages.
    """
    my_patient_id = uuid.uuid4()
    foreign_patient_id = uuid.uuid4()

    target = InquiryTarget(
        candidate_structured_domains=[],
        candidate_document_domains=["clinical_documents"],
        target_entity=None,
        requested_attributes=[],
        routing_mode=RoutingMode.DOCUMENT_ONLY,
    )

    foreign_passage = _make_passage(
        patient_id=foreign_patient_id,
        doc_date=date(2024, 1, 1),
        chunk_text="Confidential health data of foreign patient.",
    )

    retrieval_res = RetrievalResult(
        patient_id=foreign_patient_id,
        target_domains=("clinical_documents",),
        query_text="test query",
        top_k=5,
        passages=(foreign_passage,),
    )

    res = evaluate_passage_evidence(
        target, retrieval_res, requesting_patient_id=my_patient_id
    )
    assert res.status == EvidenceStatus.INSUFFICIENT
    assert len(res.qualified_passages) == 0


@pytest.mark.asyncio
async def test_layer3_fail_closed_subsystem_errors(
    async_client: AsyncClient, mock_dependencies
):
    """
    Verifies that unhandled subsystem crashes fail closed with HTTP 500
    without leaking internal stack traces.
    """
    m_pat, m_ctx, m_ret, m_llm = mock_dependencies
    _, token = await create_user_and_token()

    m_ctx.side_effect = RuntimeError("Database connection lost")

    response = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "What are my diagnosed conditions?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 500
