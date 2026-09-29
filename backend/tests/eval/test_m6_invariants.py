"""Phase 2 — Milestone 6 — Slice 6: Adversarial Invariant Suite (test_m6_invariants.py).

Validates the 12 locked invariants specified in phases/P2-M6-S6-plan.md:
  1. LATEST Selection Invariant
  2. FIRST Selection Invariant
  3. Upload Date Disqualification Invariant
  4. Tenant Isolation Invariant
  5. Deterministic Tie-Breaking Invariant
  6. Undated Exclusion Invariant
  7. Bounded Trajectory Policy Invariant
  8. Deterministic Union Deduplication Invariant
  9. Qualification-Precedes-Ranking Invariant
  10. Adversarial Hybrid-Recall Recency Invariant (Validation Extension)
  11. Lexical Recall Precision / Token-Structure Boundary Invariant
  12. Literal Regex Metacharacter Escaping Invariant

Testing Methodology:
  - Standard deterministic pytest mechanisms.
  - Zero Hypothesis usage. Zero new dependencies.
  - Fixed random seeds using random.Random(42).
"""

import random
import re
import uuid
from datetime import date, datetime
from typing import Literal, Optional, Union

from app.health.evidence_evaluator import (
    allocate_attribute_aware_milestone_passages,
    evaluate_passage_evidence,
    evaluate_timeline_evidence,
    extract_canonical_clinical_date,
    select_longitudinal_milestones,
)
from app.health.inquiry_context import HealthEvent
from app.health.retrieval import (
    RetrievalResult,
    RetrievedPassage,
    build_token_boundary_regex,
    escape_regex_literal,
)
from app.schemas.inquiry import (
    EvidenceStatus,
    InquiryTarget,
    SuperlativeType,
    TemporalConstraint,
    TemporalScope,
)

# ==============================================================================
# Helper Factories
# ==============================================================================

DEFAULT_PATIENT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def make_passage(
    *,
    chunk_id: Optional[uuid.UUID] = None,
    document_id: Optional[uuid.UUID] = None,
    patient_id: Optional[uuid.UUID] = None,
    chunk_index: int = 0,
    page_number: int = 1,
    chunk_text: str = "Cholesterol: 200 mg/dL",
    document_date: Optional[date] = None,
    document_type: str = "LAB_REPORT",
    document_display_name: str = "Lab Report",
    cosine_distance: float = 0.1,
) -> RetrievedPassage:
    """Construct an immutable RetrievedPassage instance for invariant tests."""
    c_id = chunk_id or uuid.uuid4()
    d_id = document_id or uuid.uuid4()
    p_id = patient_id or DEFAULT_PATIENT_ID
    return RetrievedPassage(
        chunk_id=c_id,
        document_id=d_id,
        patient_id=p_id,
        chunk_index=chunk_index,
        page_number=page_number,
        chunk_text=chunk_text,
        document_display_name=document_display_name,
        document_type=document_type,
        document_date=document_date,
        cosine_distance=cosine_distance,
        similarity=max(0.0, 1.0 - cosine_distance),
    )


def make_timeline_event(
    *,
    event_type: str = "CONDITION_STARTED",
    event_date: Union[date, datetime, str] = "2023-01-01",
    title: str = "Condition Event",
    description: str = "Clinical record",
    source_type: Literal[
        "CONDITION", "SYMPTOM", "MEDICATION", "DOCUMENT", "GOAL"
    ] = "CONDITION",
    event_state: Literal["current", "historical", "neutral"] = "current",
) -> HealthEvent:
    """Construct a validated HealthEvent instance for invariant tests."""
    date_str = (
        event_date.isoformat()
        if isinstance(event_date, (date, datetime))
        else str(event_date)
    )
    return HealthEvent(
        event_type=event_type,
        event_date=date_str,
        title=title,
        description=description,
        source_type=source_type,
        source_id=uuid.uuid4(),
        event_state=event_state,
    )


# ==============================================================================
# Invariant 1: LATEST Selection Invariant
# ==============================================================================


def test_inv01_latest_selection():
    """Invariant 1: selected_latest.date == max(q.date for q in Q).

    Evaluates 5 candidate passages across 10 deterministic shuffles. In all 10
    permutations, the winning passage is exactly 2025-11-20.
    """
    dates = [
        date(2021, 3, 1),
        date(2023, 7, 15),
        date(2025, 11, 20),
        date(2022, 1, 10),
        date(2024, 5, 12),
    ]
    target = InquiryTarget(
        target_entity="Cholesterol",
        candidate_document_domains=("lab_results",),
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.ALL,
            superlative=SuperlativeType.LATEST,
        ),
    )
    rng = random.Random(42)

    passages = [
        make_passage(
            document_date=d,
            chunk_text=f"Total Cholesterol: {180 + i} mg/dL on {d.isoformat()}.",
            chunk_index=i,
        )
        for i, d in enumerate(dates)
    ]

    expected_winning_date = max(dates)
    assert expected_winning_date == date(2025, 11, 20)

    for run_idx in range(10):
        shuffled = rng.sample(passages, len(passages))
        res = evaluate_passage_evidence(
            target=target,
            retrieval_result=shuffled,
            requesting_patient_id=DEFAULT_PATIENT_ID,
        )
        assert res.status == EvidenceStatus.SUFFICIENT, f"Run {run_idx} failed status"
        assert len(res.qualified_passages) >= 1, f"Run {run_idx} missing passages"
        assert expected_winning_date.isoformat() in res.evidence_directive
        winning_p = res.qualified_passages[-1]
        actual_date = extract_canonical_clinical_date(winning_p)
        assert actual_date == expected_winning_date, (
            f"Run {run_idx}: expected {expected_winning_date}, got {actual_date}"
        )


# ==============================================================================
# Invariant 2: FIRST Selection Invariant
# ==============================================================================


def test_inv02_first_selection():
    """Invariant 2: selected_first.date == min(q.date for q in Q).

    Evaluates 5 candidate passages across 10 deterministic shuffles. In all 10
    permutations, the winning passage is exactly 2021-03-01.
    """
    dates = [
        date(2021, 3, 1),
        date(2023, 7, 15),
        date(2025, 11, 20),
        date(2022, 1, 10),
        date(2024, 5, 12),
    ]
    target = InquiryTarget(
        target_entity="Cholesterol",
        candidate_document_domains=("lab_results",),
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.ALL,
            superlative=SuperlativeType.FIRST,
        ),
    )
    rng = random.Random(42)

    passages = [
        make_passage(
            document_date=d,
            chunk_text=f"Total Cholesterol: {180 + i} mg/dL on {d.isoformat()}.",
            chunk_index=i,
        )
        for i, d in enumerate(dates)
    ]

    expected_winning_date = min(dates)
    assert expected_winning_date == date(2021, 3, 1)

    for run_idx in range(10):
        shuffled = rng.sample(passages, len(passages))
        res = evaluate_passage_evidence(
            target=target,
            retrieval_result=shuffled,
            requesting_patient_id=DEFAULT_PATIENT_ID,
        )
        assert res.status == EvidenceStatus.SUFFICIENT, f"Run {run_idx} failed status"
        assert len(res.qualified_passages) >= 1, f"Run {run_idx} missing passages"
        winning_p = res.qualified_passages[0]
        actual_date = extract_canonical_clinical_date(winning_p)
        assert actual_date == expected_winning_date, (
            f"Run {run_idx}: expected {expected_winning_date}, got {actual_date}"
        )


# ==============================================================================
# Invariant 3: Upload Date Disqualification Invariant
# ==============================================================================


def test_inv03_upload_date_disqualification():
    """Invariant 3: DOCUMENT_UPLOADED / administrative timestamps cannot win
    superlative.

    Candidate A: DOCUMENT_UPLOADED on 2026-01-01 (extracts None, disqualified).
    Candidate B: CONDITION_STARTED on 2023-05-10 (extracts date(2023, 5, 10), wins).
    """
    cand_a = make_timeline_event(
        event_type="DOCUMENT_UPLOADED",
        event_date=date(2026, 1, 1),
        title="Document Uploaded",
        description="Patient uploaded lab report for Asthma.",
        source_type="DOCUMENT",
        event_state="neutral",
    )
    cand_b = make_timeline_event(
        event_type="CONDITION_STARTED",
        event_date=date(2023, 5, 10),
        title="Asthma",
        description="Patient diagnosed with Asthma.",
        source_type="CONDITION",
        event_state="current",
    )

    # 1. extract_canonical_clinical_date contract
    assert extract_canonical_clinical_date(cand_a) is None
    assert extract_canonical_clinical_date(cand_b) == date(2023, 5, 10)

    # 2. evaluate_timeline_evidence under LATEST
    target = InquiryTarget(
        target_entity="Asthma",
        candidate_structured_domains=("timeline", "conditions"),
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.ALL,
            superlative=SuperlativeType.LATEST,
        ),
    )

    res = evaluate_timeline_evidence(target=target, context=[cand_a, cand_b])
    assert res.status == EvidenceStatus.SUFFICIENT
    assert len(res.matched_records) == 1
    winning_record = res.matched_records[0]
    assert extract_canonical_clinical_date(winning_record) == date(2023, 5, 10)
    assert winning_record.source_id == cand_b.source_id
    assert winning_record.event_type == "CONDITION_STARTED"


# ==============================================================================
# Invariant 4: Tenant Isolation Invariant
# ==============================================================================


def test_inv04_tenant_isolation():
    """Invariant 4: candidate.patient_id == authenticated_patient_id.

    Cross-tenant candidates trigger immediate fail-closed return with
    INSUFFICIENT and zero qualified passages.
    """
    patient_a = uuid.UUID("11111111-1111-1111-1111-111111111111")
    patient_b = uuid.UUID("22222222-2222-2222-2222-222222222222")

    passages_a = [
        make_passage(
            patient_id=patient_a,
            chunk_text="Cholesterol: 190 mg/dL.",
            document_date=date(2024, 1, 15),
        ),
        make_passage(
            patient_id=patient_a,
            chunk_text="Total Cholesterol: 195 mg/dL.",
            document_date=date(2024, 6, 20),
        ),
    ]
    passages_b = [
        make_passage(
            patient_id=patient_b,
            chunk_text="Cholesterol: 240 mg/dL.",
            document_date=date(2025, 2, 1),
        ),
    ]

    target = InquiryTarget(
        target_entity="Cholesterol",
        candidate_document_domains=("lab_results",),
    )

    # Legitimate isolated patient_A evaluation succeeds
    res_isolated = evaluate_passage_evidence(
        target=target,
        retrieval_result=passages_a,
        requesting_patient_id=patient_a,
    )
    assert res_isolated.status == EvidenceStatus.SUFFICIENT
    assert len(res_isolated.qualified_passages) == 2

    # Mismatched retrieval_result.patient_id fails closed
    foreign_result = RetrievalResult(
        patient_id=patient_b,
        target_domains=("lab_results",),
        query_text="Cholesterol",
        top_k=3,
        passages=tuple(passages_b),
    )
    res_foreign_tenant = evaluate_passage_evidence(
        target=target,
        retrieval_result=foreign_result,
        requesting_patient_id=patient_a,
    )
    assert res_foreign_tenant.status == EvidenceStatus.INSUFFICIENT
    assert len(res_foreign_tenant.qualified_passages) == 0

    # Cross-tenant contaminated passage pool fails closed
    mixed_result = RetrievalResult(
        patient_id=patient_a,
        target_domains=("lab_results",),
        query_text="Cholesterol",
        top_k=3,
        passages=tuple(passages_a + passages_b),
    )
    res_contaminated = evaluate_passage_evidence(
        target=target,
        retrieval_result=mixed_result,
        requesting_patient_id=patient_a,
    )
    assert res_contaminated.status == EvidenceStatus.INSUFFICIENT
    assert len(res_contaminated.qualified_passages) == 0
    assert "Your uploaded records were searched" in res_contaminated.evidence_directive


# ==============================================================================
# Invariant 5: Deterministic Tie-Breaking Invariant
# ==============================================================================


def test_inv05_deterministic_tie_breaking():
    """Invariant 5: Same dates -> deterministic doc_id / chunk_index sort.

    4 passages sharing the exact same date (2024-06-15) with distinct
    (document_id, chunk_index) are evaluated across 8 distinct random input
    permutations. All 8 permutations yield the exact same qualified passage order.
    """
    fixed_date = date(2024, 6, 15)
    doc_0 = uuid.UUID("00000000-0000-0000-0000-000000000001")
    doc_1 = uuid.UUID("00000000-0000-0000-0000-000000000002")
    doc_2 = uuid.UUID("00000000-0000-0000-0000-000000000003")

    # 4 distinct items with controlled tie-break precedence:
    # 1. doc_0, chunk 3
    # 2. doc_1, chunk 0
    # 3. doc_1, chunk 2
    # 4. doc_2, chunk 1
    p_d0_c3 = make_passage(
        document_id=doc_0,
        chunk_index=3,
        document_date=fixed_date,
        chunk_text="Cholesterol: 190 mg/dL (d0_c3)",
    )
    p_d1_c0 = make_passage(
        document_id=doc_1,
        chunk_index=0,
        document_date=fixed_date,
        chunk_text="Cholesterol: 191 mg/dL (d1_c0)",
    )
    p_d1_c2 = make_passage(
        document_id=doc_1,
        chunk_index=2,
        document_date=fixed_date,
        chunk_text="Cholesterol: 192 mg/dL (d1_c2)",
    )
    p_d2_c1 = make_passage(
        document_id=doc_2,
        chunk_index=1,
        document_date=fixed_date,
        chunk_text="Cholesterol: 193 mg/dL (d2_c1)",
    )

    passages = [p_d0_c3, p_d1_c0, p_d1_c2, p_d2_c1]

    target = InquiryTarget(
        target_entity="Cholesterol",
        candidate_document_domains=("lab_results",),
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.ALL,
            superlative=SuperlativeType.LATEST,
        ),
    )

    rng = random.Random(42)
    reference_order = None

    for run_idx in range(8):
        shuffled = rng.sample(passages, len(passages))
        res = evaluate_passage_evidence(
            target=target,
            retrieval_result=shuffled,
            requesting_patient_id=DEFAULT_PATIENT_ID,
        )
        assert res.status == EvidenceStatus.SUFFICIENT
        actual_order = [(p.document_id, p.chunk_index) for p in res.qualified_passages]
        if reference_order is None:
            reference_order = actual_order
        else:
            assert actual_order == reference_order, (
                f"Run {run_idx} tie-breaking order diverged: "
                f"{actual_order} != {reference_order}"
            )

    # Confirm tie-break ordering is sorted: doc_id ASC, chunk_index ASC
    sorted_expected = sorted(
        [(p.document_id, p.chunk_index) for p in passages],
        key=lambda pair: (pair[0], pair[1]),
    )
    # allocate_superlative_document_passages retains up to quota (budget 4)
    assert reference_order == sorted_expected


# ==============================================================================
# Invariant 6: Undated Exclusion Invariant
# ==============================================================================


def test_inv06_undated_exclusion():
    """Invariant 6: Undated records never defeat dated records.

    - In mixed set: dated passage (2022-01-01) defeats undated passage.
    - In all-undated set: returns PARTIALLY_SUFFICIENT and refuses to assert
      chronological certainty.
    """
    p_dated = make_passage(
        document_date=date(2022, 1, 1),
        chunk_text="Total Cholesterol: 210 mg/dL dated record.",
    )
    p_undated_1 = make_passage(
        document_date=None,
        chunk_text="Total Cholesterol: 195 mg/dL undated report.",
    )
    p_undated_2 = make_passage(
        document_date=None,
        chunk_text="Cholesterol HDL ratio: 3.5 undated summary.",
    )

    target = InquiryTarget(
        target_entity="Cholesterol",
        candidate_document_domains=("lab_results",),
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.ALL,
            superlative=SuperlativeType.LATEST,
        ),
    )

    # 1. Mixed set: dated candidate wins
    res_mixed = evaluate_passage_evidence(
        target=target,
        retrieval_result=[p_dated, p_undated_1],
        requesting_patient_id=DEFAULT_PATIENT_ID,
    )
    assert res_mixed.status == EvidenceStatus.SUFFICIENT
    assert "2022-01-01" in res_mixed.evidence_directive
    winning_docs = [
        p
        for p in res_mixed.qualified_passages
        if extract_canonical_clinical_date(p) == date(2022, 1, 1)
    ]
    assert len(winning_docs) == 1
    assert winning_docs[0].chunk_id == p_dated.chunk_id

    # 2. All-undated set: fails to establish recency, returns PARTIALLY_SUFFICIENT
    res_all_undated = evaluate_passage_evidence(
        target=target,
        retrieval_result=[p_undated_1, p_undated_2],
        requesting_patient_id=DEFAULT_PATIENT_ID,
    )
    assert res_all_undated.status == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert res_all_undated.temporal_interpretation == "superlative"
    assert (
        "no verifiable clinical dates were recorded to establish recency"
        in res_all_undated.evidence_directive
    )


# ==============================================================================
# Invariant 7: Bounded Longitudinal Trajectory Policy Invariant
# ==============================================================================


def test_inv07_bounded_trajectory_policy():
    """Invariant 7: Milestone dates N <= 3; passage budget K <= 4.

    Given 6 distinct clinical dates:
    - select_longitudinal_milestones returns exactly 3 milestone dates:
      Baseline (oldest), Intermediate (newest intermediate), Latest (newest).
    - allocate_attribute_aware_milestone_passages bounds total passages to K <= 4.
    """
    dates = [
        date(2020, 1, 1),
        date(2021, 2, 1),
        date(2022, 3, 1),
        date(2023, 4, 1),
        date(2024, 5, 1),
        date(2025, 6, 1),
    ]

    # 1. Milestone selection
    milestones = select_longitudinal_milestones(dates)
    assert len(milestones) == 3
    assert milestones[0] == date(2020, 1, 1)  # Baseline
    assert milestones[1] == date(2024, 5, 1)  # Intermediate (newest intermediate)
    assert milestones[2] == date(2025, 6, 1)  # Latest

    # 2. Passage budget allocation
    # Create 2 passages for baseline, 2 for intermediate, 3 for latest = 7 total
    passages = []
    for d in milestones:
        for idx in range(3 if d == milestones[-1] else 2):
            passages.append(
                make_passage(
                    document_date=d,
                    chunk_index=idx,
                    chunk_text=f"Cholesterol: {190 + idx} on {d.isoformat()}.",
                )
            )
    assert len(passages) == 7

    target = InquiryTarget(
        target_entity="Cholesterol",
        question_intent="COMPARISON",
    )
    allocated = allocate_attribute_aware_milestone_passages(
        milestone_dates=milestones,
        passages_or_by_date=passages,
        requested_attributes_or_target=target,
        budget=4,
    )
    assert len(allocated) <= 4
    # All allocated passages belong strictly to one of the 3 milestone dates
    allocated_dates = {extract_canonical_clinical_date(p) for p in allocated}
    assert allocated_dates.issubset(set(milestones))


# ==============================================================================
# Invariant 8: Deterministic Union Deduplication Invariant
# ==============================================================================


def test_inv08_deterministic_union_deduplication():
    """Invariant 8: |C_dense U C_lexical| <= 20; zero duplicate chunk IDs.

    C_dense has 10 chunks, C_lexical has 10 chunks, with 4 overlapping chunk IDs.
    Deduplicated union size |U| == 16.
    Zero duplicate chunk IDs.
    Set of chunk IDs is invariant under union order.
    """
    all_ids = [uuid.uuid4() for _ in range(16)]
    # Dense: 0..9 (10 chunks)
    dense_ids = all_ids[0:10]
    # Lexical: 6..15 (10 chunks, with 6,7,8,9 overlapping)
    lexical_ids = all_ids[6:16]

    dense_passages = [
        make_passage(chunk_id=cid, chunk_text=f"Dense passage {idx}")
        for idx, cid in enumerate(dense_ids)
    ]
    lexical_passages = [
        make_passage(chunk_id=cid, chunk_text=f"Lexical passage {idx}")
        for idx, cid in enumerate(lexical_ids)
    ]

    def deduplicate_union(
        p_list1: list[RetrievedPassage], p_list2: list[RetrievedPassage]
    ) -> list[RetrievedPassage]:
        seen: set[uuid.UUID] = set()
        union: list[RetrievedPassage] = []
        for p in p_list1:
            if p.chunk_id not in seen:
                seen.add(p.chunk_id)
                union.append(p)
        for p in p_list2:
            if p.chunk_id not in seen:
                seen.add(p.chunk_id)
                union.append(p)
        return union

    union_dense_first = deduplicate_union(dense_passages, lexical_passages)
    union_lexical_first = deduplicate_union(lexical_passages, dense_passages)

    # Exactly 16 unique items
    assert len(union_dense_first) == 16
    assert len(union_lexical_first) == 16

    # Zero duplicate chunk IDs
    dense_first_ids = [p.chunk_id for p in union_dense_first]
    lexical_first_ids = [p.chunk_id for p in union_lexical_first]
    assert len(dense_first_ids) == len(set(dense_first_ids))
    assert len(lexical_first_ids) == len(set(lexical_first_ids))

    # Set invariance under union order
    assert set(dense_first_ids) == set(lexical_first_ids)
    assert set(dense_first_ids) == set(all_ids)


# ==============================================================================
# Invariant 9: Qualification-Precedes-Ranking Invariant
# ==============================================================================


def test_inv09_qualification_precedes_ranking():
    """Invariant 9: Uncorroborated newer chunk disqualified before sort.

    Passage A (2025-01-01): Mentions optometrist, does NOT corroborate Cholesterol.
    Passage B (2022-06-15): Mentions Total Cholesterol: 195 mg/dL.
    Superlative: LATEST.
    Passage A is disqualified during qualification; Passage B wins despite older date.
    """
    p_newer_unrelated = make_passage(
        document_date=date(2025, 1, 1),
        chunk_text="Patient visited optometrist for routine eye exam. Vision 20/20.",
    )
    p_older_corroborating = make_passage(
        document_date=date(2022, 6, 15),
        chunk_text="Total Cholesterol: 195 mg/dL. HDL: 50. Triglycerides: 140.",
    )

    target = InquiryTarget(
        target_entity="Cholesterol",
        candidate_document_domains=("lab_results",),
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.ALL,
            superlative=SuperlativeType.LATEST,
        ),
    )

    res = evaluate_passage_evidence(
        target=target,
        retrieval_result=[p_newer_unrelated, p_older_corroborating],
        requesting_patient_id=DEFAULT_PATIENT_ID,
    )
    assert res.status == EvidenceStatus.SUFFICIENT
    assert len(res.qualified_passages) == 1
    winning_passage = res.qualified_passages[0]
    assert winning_passage.chunk_id == p_older_corroborating.chunk_id
    assert extract_canonical_clinical_date(winning_passage) == date(2022, 6, 15)


# ==============================================================================
# Invariant 10: Adversarial Hybrid-Recall Recency Invariant (Validation Extension)
# ==============================================================================


def test_inv10_adversarial_hybrid_recall_recency():
    """Invariant 10: Dense-blind newest/oldest candidate recovered via lexical path.

    Operational Boundary: Validates recency correctness after deterministic
    hybrid candidate union has been formed without calling PostgreSQL.
    """
    target_latest = InquiryTarget(
        target_entity="Cholesterol",
        candidate_document_domains=("lab_results",),
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.ALL,
            superlative=SuperlativeType.LATEST,
        ),
    )
    target_first = InquiryTarget(
        target_entity="Cholesterol",
        candidate_document_domains=("lab_results",),
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.ALL,
            superlative=SuperlativeType.FIRST,
        ),
    )

    # --------------------------------------------------------------------------
    # Scenario 10a: Dense-Blind LATEST Recovery
    # 10 older passages (2020-2023) in dense top-10.
    # True newest candidate P_newest (2026-03-01) recovered via lexical path.
    # --------------------------------------------------------------------------
    simulated_dense_older = [
        make_passage(
            document_date=date(2020 + i % 4, 1 + i % 12, 1),
            chunk_text=f"Total Cholesterol: {190 + i} mg/dL.",
            cosine_distance=0.05 + 0.01 * i,
        )
        for i in range(10)
    ]
    p_newest_lexical = make_passage(
        document_date=date(2026, 3, 1),
        chunk_text="Total Cholesterol: 215 mg/dL on latest panel.",
        cosine_distance=0.99,  # Would have missed dense top-10 cut
    )

    union_10a = simulated_dense_older + [p_newest_lexical]
    res_10a = evaluate_passage_evidence(
        target=target_latest,
        retrieval_result=union_10a,
        requesting_patient_id=DEFAULT_PATIENT_ID,
    )
    assert res_10a.status == EvidenceStatus.SUFFICIENT
    assert "2026-03-01" in res_10a.evidence_directive
    winning_date_10a = extract_canonical_clinical_date(res_10a.qualified_passages[-1])
    assert winning_date_10a == date(2026, 3, 1)
    assert res_10a.qualified_passages[-1].chunk_id == p_newest_lexical.chunk_id

    # --------------------------------------------------------------------------
    # Scenario 10b: Dense-Blind FIRST Recovery
    # 10 newer passages (2021-2025) in dense top-10.
    # True oldest candidate P_oldest (2017-05-10) recovered via lexical path.
    # --------------------------------------------------------------------------
    simulated_dense_newer = [
        make_passage(
            document_date=date(2021 + i % 5, 1 + i % 12, 1),
            chunk_text=f"Total Cholesterol: {185 + i} mg/dL.",
            cosine_distance=0.05 + 0.01 * i,
        )
        for i in range(10)
    ]
    p_oldest_lexical = make_passage(
        document_date=date(2017, 5, 10),
        chunk_text="Total Cholesterol: 175 mg/dL baseline measurement.",
        cosine_distance=0.99,  # Would have missed dense top-10 cut
    )

    union_10b = simulated_dense_newer + [p_oldest_lexical]
    res_10b = evaluate_passage_evidence(
        target=target_first,
        retrieval_result=union_10b,
        requesting_patient_id=DEFAULT_PATIENT_ID,
    )
    assert res_10b.status == EvidenceStatus.SUFFICIENT
    winning_date_10b = extract_canonical_clinical_date(res_10b.qualified_passages[0])
    assert winning_date_10b == date(2017, 5, 10)
    assert res_10b.qualified_passages[0].chunk_id == p_oldest_lexical.chunk_id


# ==============================================================================
# Invariant 11: Lexical Recall Precision / Token-Structure Boundary Invariant
# ==============================================================================


def test_inv11_token_structure_boundary():
    """Invariant 11: Token-structure boundary checks reject substrings and compounds.

    - Scenario 11a: Single-token variant "bp" does NOT match "RBP".
    - Scenario 11b: Single-token variant "chol" does NOT match "cholecystectomy".
    """
    # 1. PostgreSQL ARE token boundary syntax check
    assert build_token_boundary_regex("bp") == r"\mbp\M"
    assert build_token_boundary_regex("chol") == r"\mchol\M"

    # 2. Simulation of whole-token boundary matching
    def matches_whole_token(token: str, text: str) -> bool:
        escaped = re.escape(token)
        pattern = rf"(?<!\w){escaped}(?!\w)"
        return bool(re.search(pattern, text, re.IGNORECASE))

    # Scenario 11a (bp vs RBP)
    rbp_text = "Serum RBP levels measured at 45 mcg/mL."
    assert not matches_whole_token("bp", rbp_text)
    assert matches_whole_token("bp", "Current BP: 120/80 mmHg.")

    # Evaluator qualification rejection for bp
    p_rbp = make_passage(
        chunk_text=rbp_text,
        document_date=date(2025, 1, 1),
    )
    target_bp = InquiryTarget(
        target_entity="bp",
        candidate_document_domains=("vitals",),
    )
    res_bp = evaluate_passage_evidence(
        target=target_bp,
        retrieval_result=[p_rbp],
        requesting_patient_id=DEFAULT_PATIENT_ID,
    )
    assert res_bp.status == EvidenceStatus.INSUFFICIENT
    assert len(res_bp.qualified_passages) == 0

    # Scenario 11b (chol vs cholecystectomy)
    chole_text = "Patient scheduled for elective laparoscopic cholecystectomy."
    assert not matches_whole_token("chol", chole_text)
    assert matches_whole_token("chol", "Total Chol: 190 mg/dL.")

    # Evaluator qualification rejection for chol
    p_chole = make_passage(
        chunk_text=chole_text,
        document_date=date(2025, 1, 1),
    )
    target_chol = InquiryTarget(
        target_entity="chol",
        candidate_document_domains=("lab_results",),
    )
    res_chol = evaluate_passage_evidence(
        target=target_chol,
        retrieval_result=[p_chole],
        requesting_patient_id=DEFAULT_PATIENT_ID,
    )
    assert res_chol.status == EvidenceStatus.INSUFFICIENT
    assert len(res_chol.qualified_passages) == 0


# ==============================================================================
# Invariant 12: Literal Regex Metacharacter Escaping Invariant
# ==============================================================================


def test_inv12_literal_regex_metacharacter_escaping():
    """Invariant 12: Regex metacharacters in entities/variants are escaped literally.

    - Scenario 12a: "a.b" matches literal "a.b", not wildcard "axb".
    - Scenario 12b: "c+d" matches literal "c+d", not repeated "cccd".
    """
    # 1. Escape helper assertions
    assert escape_regex_literal("a.b") == r"a\.b"
    assert escape_regex_literal("c+d") == r"c\+d"
    assert build_token_boundary_regex("a.b") == r"\ma\.b\M"
    assert build_token_boundary_regex("c+d") == r"\mc\+d\M"

    # 2. Literal matching simulation
    def matches_escaped_token(token: str, text: str) -> bool:
        escaped = re.escape(token)
        pattern = rf"(?<!\w){escaped}(?!\w)"
        return bool(re.search(pattern, text, re.IGNORECASE))

    # Scenario 12a: '.' is literal, not wildcard
    assert matches_escaped_token("a.b", "Test result a.b normal.")
    assert not matches_escaped_token("a.b", "Test result axb normal.")

    # Scenario 12b: '+' is literal, not one-or-more quantifier
    assert matches_escaped_token("c+d", "Marker c+d present.")
    assert not matches_escaped_token("c+d", "Marker cccd present.")
