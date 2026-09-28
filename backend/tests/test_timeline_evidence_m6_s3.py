"""Phase 2 — Milestone 6 — Slice 3: Timeline Evidence & Citation Integration Tests.

Validates:
- RFC-4122 UUID5 deterministic timeline event identity derivation (TID-01..04)
- Context loading on 'timeline' domain and tenant isolation (CTX-01..04)
- Deterministic timeline evidence evaluation and Rule F caveat propagation (EVAL-01..13)
- Multi-source citation assembly and independent deduplication (CIT-01..06)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.health_inquiry import _build_record_map
from app.core.llm import SynthesisResult
from app.db.models import Condition, Patient
from app.health.evidence_evaluator import (
    EvidenceResult,
    evaluate_evidence,
)
from app.health.inquiry_context import (
    DocumentEvidenceContext,
    StructuredHealthContext,
    build_inquiry_context,
)
from app.schemas.condition import ConditionResponse
from app.schemas.inquiry import (
    EvidenceStatus,
    InquiryTarget,
    RoutingMode,
    SafetyGuardrailState,
    SuperlativeType,
    TemporalConstraint,
    TemporalScope,
    TimelineEventEvidence,
    generate_timeline_event_id,
)
from app.schemas.provenance import VerificationState
from app.schemas.timeline import HealthEvent
from tests.test_health_inquiry_api import create_user_and_token

# ===========================================================================
# Helper Factories
# ===========================================================================


def _create_patient(db: AsyncSession, patient_id: uuid.UUID | None = None) -> uuid.UUID:
    patient_id = patient_id or uuid.uuid4()
    p = Patient(id=patient_id, user_id=uuid.uuid4())
    db.add(p)
    return patient_id


def _make_timeline_event(
    title: str = "Condition: Asthma",
    description: str | None = "status: active, started_at: 2024-01-01",
    event_date: str = "2024-01-01",
    event_type: str = "CONDITION_STARTED",
    event_state: str = "current",
    source_type: str = "CONDITION",
    source_id: uuid.UUID | None = None,
) -> HealthEvent:
    return HealthEvent(
        title=title,
        description=description,
        event_date=event_date,
        event_type=event_type,
        event_state=event_state,
        source_type=source_type,
        source_id=source_id or uuid.uuid4(),
    )


def _make_condition_response(
    cond_id: uuid.UUID | None = None,
    name: str = "Asthma",
    status: str = "active",
) -> ConditionResponse:
    cid = cond_id or uuid.uuid4()
    return ConditionResponse(
        id=cid,
        patient_id=uuid.uuid4(),
        name=name,
        status=status,
        recorded_at=datetime.now(timezone.utc),
        source_type="PATIENT_REPORTED",
        source_id=cid,
        verification_state="PATIENT_REPORTED",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


# ===========================================================================
# Suite 1: Timeline Identity & UUID5 Tests (TID-01 .. TID-04)
# ===========================================================================


def test_uuid5_deterministic_stability():
    """TID-01: Identical inputs produce identical UUID5 values across runs."""
    src_id = uuid.uuid4()
    id1 = generate_timeline_event_id("CONDITION", src_id, "CONDITION_STARTED")
    id2 = generate_timeline_event_id("CONDITION", src_id, "CONDITION_STARTED")
    assert id1 == id2
    assert isinstance(id1, uuid.UUID)


def test_uuid5_event_type_separation():
    """TID-02: Same source_id, different event_type -> distinct IDs."""
    src_id = uuid.uuid4()
    id_start = generate_timeline_event_id("CONDITION", src_id, "CONDITION_STARTED")
    id_resolved = generate_timeline_event_id("CONDITION", src_id, "CONDITION_RESOLVED")
    assert id_start != id_resolved

    med_id = uuid.uuid4()
    med_start = generate_timeline_event_id("MEDICATION", med_id, "MEDICATION_STARTED")
    med_stop = generate_timeline_event_id("MEDICATION", med_id, "MEDICATION_STOPPED")
    assert med_start != med_stop


def test_uuid5_source_id_separation():
    """TID-03: Different source_ids -> distinct IDs."""
    src1 = uuid.uuid4()
    src2 = uuid.uuid4()
    id1 = generate_timeline_event_id("CONDITION", src1, "CONDITION_STARTED")
    id2 = generate_timeline_event_id("CONDITION", src2, "CONDITION_STARTED")
    assert id1 != id2


def test_uuid5_reproducibility():
    """TID-04: RFC-4122 namespace repeatability."""
    src_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    expected = uuid.uuid5(
        uuid.NAMESPACE_URL, f"timeline:CONDITION:{src_id}:CONDITION_STARTED"
    )
    actual = generate_timeline_event_id("CONDITION", src_id, "CONDITION_STARTED")
    assert actual == expected
    assert actual.version == 5


# ===========================================================================
# Suite 2: Context Loading Tests (CTX-01 .. CTX-04)
# ===========================================================================


@pytest.mark.asyncio
async def test_timeline_domain_loads_context(db: AsyncSession):
    """CTX-01: 'timeline' in domains loads events into recent_timeline_events."""
    pid = _create_patient(db)
    db.add(
        Condition(
            patient_id=pid,
            name="Asthma",
            status="active",
            source_type="PATIENT_REPORTED",
            started_at=date(2024, 1, 1),
        )
    )
    await db.commit()

    ctx = await build_inquiry_context(db, pid, domains=["timeline"])
    assert len(ctx.recent_timeline_events) > 0
    assert len(ctx.conditions) == 0  # conditions domain was not requested


@pytest.mark.asyncio
async def test_non_timeline_does_not_regress(db: AsyncSession):
    """CTX-02: 'conditions' leaves timeline empty; domains=None loads all events."""
    pid = _create_patient(db)
    db.add(
        Condition(
            patient_id=pid,
            name="Hypertension",
            status="active",
            source_type="PATIENT_REPORTED",
            started_at=date(2023, 5, 10),
        )
    )
    await db.commit()

    # 1. Single domain excluding timeline
    ctx_cond = await build_inquiry_context(db, pid, domains=["conditions"])
    assert len(ctx_cond.recent_timeline_events) == 0
    assert len(ctx_cond.conditions) == 1

    # 2. domains=None loads full context including timeline
    ctx_all = await build_inquiry_context(db, pid, domains=None)
    assert len(ctx_all.recent_timeline_events) > 0
    assert len(ctx_all.conditions) == 1


@pytest.mark.asyncio
async def test_timeline_multi_domain_context(db: AsyncSession):
    """CTX-03: domains=['timeline', 'conditions'] loads both conditions and timeline."""
    pid = _create_patient(db)
    db.add(
        Condition(
            patient_id=pid,
            name="Migraine",
            status="active",
            source_type="PATIENT_REPORTED",
            started_at=date(2024, 2, 1),
        )
    )
    await db.commit()

    ctx = await build_inquiry_context(db, pid, domains=["timeline", "conditions"])
    assert len(ctx.recent_timeline_events) > 0
    assert len(ctx.conditions) == 1


@pytest.mark.asyncio
async def test_timeline_tenant_isolation(db: AsyncSession):
    """CTX-04: Patient A never loads Patient B events."""
    p1 = _create_patient(db)
    p2 = _create_patient(db)

    db.add(
        Condition(
            patient_id=p1,
            name="P1 Condition",
            status="active",
            source_type="PATIENT_REPORTED",
            started_at=date(2024, 1, 1),
        )
    )
    db.add(
        Condition(
            patient_id=p2,
            name="P2 Condition",
            status="active",
            source_type="PATIENT_REPORTED",
            started_at=date(2024, 1, 1),
        )
    )
    await db.commit()

    ctx_p1 = await build_inquiry_context(db, p1, domains=["timeline"])
    assert len(ctx_p1.recent_timeline_events) > 0
    for e in ctx_p1.recent_timeline_events:
        assert "P2 Condition" not in e.title
        assert "P1 Condition" in e.title


# ===========================================================================
# Suite 3: Evidence Evaluation Tests (EVAL-01 .. EVAL-13)
# ===========================================================================


def test_eval_timeline_entity_matching():
    """EVAL-01: Entity match against title and description (case-insensitive)."""
    e1 = _make_timeline_event(
        title="Condition: Asthma",
        description="status: active",
    )
    e2 = _make_timeline_event(
        title="Medication: Lisinopril",
        description="Prescribed for Hypertension control",
    )
    ctx = StructuredHealthContext(recent_timeline_events=[e1, e2])

    # 1. Match title
    t1 = InquiryTarget(
        candidate_structured_domains=["timeline"], target_entity="asthma"
    )
    res1 = evaluate_evidence(t1, ctx)
    assert res1.status == EvidenceStatus.SUFFICIENT
    assert len(res1.matched_records) == 1
    assert res1.matched_records[0].title == "Condition: Asthma"

    # 2. Match description
    t2 = InquiryTarget(
        candidate_structured_domains=["timeline"], target_entity="HYPERTENSION"
    )
    res2 = evaluate_evidence(t2, ctx)
    assert res2.status == EvidenceStatus.SUFFICIENT
    assert len(res2.matched_records) == 1
    assert "Hypertension" in res2.matched_records[0].description


def test_eval_timeline_attributes():
    """EVAL-02: Attribute match in event description."""
    e = _make_timeline_event(
        title="Medication: Lisinopril",
        description="dosage: 10mg, frequency: daily, status: active",
    )
    ctx = StructuredHealthContext(recent_timeline_events=[e])

    target = InquiryTarget(
        candidate_structured_domains=["timeline"],
        target_entity="Lisinopril",
        requested_attributes=["dosage", "frequency"],
    )
    res = evaluate_evidence(target, ctx)
    assert res.status == EvidenceStatus.SUFFICIENT
    assert set(res.matched_fields) == {"dosage", "frequency"}
    assert res.missing_fields == []
    assert len(res.matched_records) == 1


def test_eval_timeline_interval_filter():
    """EVAL-03: Filter events strictly within [start_date, end_date]."""
    e1 = _make_timeline_event(title="Event Jan", event_date="2024-01-15")
    e2 = _make_timeline_event(title="Event Jun", event_date="2024-06-15")
    e3 = _make_timeline_event(title="Event Dec", event_date="2024-12-15")
    ctx = StructuredHealthContext(recent_timeline_events=[e1, e2, e3])

    target = InquiryTarget(
        candidate_structured_domains=["timeline"],
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.INTERVAL,
            start_date=date(2024, 5, 1),
            end_date=date(2024, 7, 1),
            raw_expression="between May and July 2024",
        ),
    )
    res = evaluate_evidence(target, ctx)
    assert res.status == EvidenceStatus.SUFFICIENT
    assert len(res.matched_records) == 1
    assert res.matched_records[0].title == "Event Jun"

    # Interval with 0 surviving records
    target_empty = InquiryTarget(
        candidate_structured_domains=["timeline"],
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.INTERVAL,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 2, 1),
            raw_expression="in early 2025",
        ),
    )
    res_empty = evaluate_evidence(target_empty, ctx)
    assert res_empty.status == EvidenceStatus.INSUFFICIENT
    assert "No timeline events found for in early 2025." in res_empty.evidence_directive


def test_eval_timeline_current_historical():
    """EVAL-04: Filter CURRENT (current only) and HISTORICAL (historical only)."""
    e_curr = _make_timeline_event(title="Current Cond", event_state="current")
    e_hist = _make_timeline_event(title="Resolved Cond", event_state="historical")
    ctx = StructuredHealthContext(recent_timeline_events=[e_curr, e_hist])

    # Current scope
    target_curr = InquiryTarget(
        candidate_structured_domains=["timeline"],
        temporal_constraint=TemporalConstraint(scope=TemporalScope.CURRENT),
    )
    res_curr = evaluate_evidence(target_curr, ctx)
    assert res_curr.status == EvidenceStatus.SUFFICIENT
    assert len(res_curr.matched_records) == 1
    assert res_curr.matched_records[0].title == "Current Cond"

    # Historical scope
    target_hist = InquiryTarget(
        candidate_structured_domains=["timeline"],
        temporal_constraint=TemporalConstraint(scope=TemporalScope.HISTORICAL),
    )
    res_hist = evaluate_evidence(target_hist, ctx)
    assert res_hist.status == EvidenceStatus.SUFFICIENT
    assert len(res_hist.matched_records) == 1
    assert res_hist.matched_records[0].title == "Resolved Cond"


def test_eval_timeline_superlatives():
    """EVAL-05: LATEST and FIRST extremity with same-date ties kept."""
    e_old = _make_timeline_event(title="Old Event", event_date="2022-01-01")
    e_mid = _make_timeline_event(title="Mid Event", event_date="2023-01-01")
    e_new1 = _make_timeline_event(
        title="Latest Event A",
        event_date="2024-05-01",
        source_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
    )
    e_new2 = _make_timeline_event(
        title="Latest Event B",
        event_date="2024-05-01",
        source_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
    )
    ctx = StructuredHealthContext(recent_timeline_events=[e_old, e_mid, e_new1, e_new2])

    # 1. LATEST: Should retain both events on 2024-05-01 ordered by record.id ASC
    t_latest = InquiryTarget(
        candidate_structured_domains=["timeline"],
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.ALL, superlative=SuperlativeType.LATEST
        ),
    )
    res_latest = evaluate_evidence(t_latest, ctx)
    assert res_latest.status == EvidenceStatus.SUFFICIENT
    assert len(res_latest.matched_records) == 2
    assert res_latest.matched_records[0].event_date == "2024-05-01"
    assert res_latest.matched_records[1].event_date == "2024-05-01"
    assert res_latest.matched_records[0].id < res_latest.matched_records[1].id

    # 2. FIRST: Should retain single oldest event on 2022-01-01
    t_first = InquiryTarget(
        candidate_structured_domains=["timeline"],
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.ALL, superlative=SuperlativeType.FIRST
        ),
    )
    res_first = evaluate_evidence(t_first, ctx)
    assert res_first.status == EvidenceStatus.SUFFICIENT
    assert len(res_first.matched_records) == 1
    assert res_first.matched_records[0].title == "Old Event"


def test_eval_timeline_undated_honesty():
    """EVAL-06: Date-absence honesty for entity-anchored & entity-less superlatives."""
    e_undated1 = _make_timeline_event(
        title="Condition: Asthma",
        description="status: active",
        event_date="",  # undated
    )
    e_undated2 = _make_timeline_event(
        title="Medication: Albuterol",
        description="status: current",
        event_date="",  # undated
    )
    ctx = StructuredHealthContext(recent_timeline_events=[e_undated1, e_undated2])

    # 1. Entity-anchored superlative with undated evidence
    target_entity = InquiryTarget(
        candidate_structured_domains=["timeline"],
        target_entity="Asthma",
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.ALL, superlative=SuperlativeType.LATEST
        ),
    )
    res_entity = evaluate_evidence(target_entity, ctx)
    assert res_entity.status == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert res_entity.matched_records
    assert all(
        isinstance(record, TimelineEventEvidence)
        for record in res_entity.matched_records
    )
    assert all(
        isinstance(record.id, uuid.UUID) for record in res_entity.matched_records
    )
    assert target_entity.target_entity in res_entity.evidence_directive
    assert "lack documented clinical dates" in res_entity.evidence_directive

    # 2. Entity-less timeline superlative with undated evidence
    target_entityless = InquiryTarget(
        candidate_structured_domains=["timeline"],
        target_entity=None,
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.ALL, superlative=SuperlativeType.LATEST
        ),
    )
    res_entityless = evaluate_evidence(target_entityless, ctx)
    assert res_entityless.status == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert res_entityless.matched_records
    assert all(
        isinstance(record, TimelineEventEvidence)
        for record in res_entityless.matched_records
    )
    assert all(
        isinstance(record.id, uuid.UUID) for record in res_entityless.matched_records
    )
    assert "None" not in res_entityless.evidence_directive
    assert "lack documented clinical dates" in res_entityless.evidence_directive


def test_eval_document_uploaded_exclusion():
    """EVAL-07: DOCUMENT_UPLOADED excluded from clinical temporal evidence."""
    e_upload = _make_timeline_event(
        title="Document Uploaded",
        event_date="2024-12-01",
        event_type="DOCUMENT_UPLOADED",
    )
    ctx_only_upload = StructuredHealthContext(recent_timeline_events=[e_upload])

    target = InquiryTarget(
        candidate_structured_domains=["timeline"],
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.ALL, superlative=SuperlativeType.LATEST
        ),
    )
    # Upload event excluded -> no dated clinical events -> PARTIALLY_SUFFICIENT honesty
    res = evaluate_evidence(target, ctx_only_upload)
    assert res.status == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert "lack documented clinical dates" in res.evidence_directive

    # If clinical event also exists, DOCUMENT_UPLOADED is excluded from winning
    e_clinical = _make_timeline_event(
        title="Condition: Asthma",
        event_date="2024-06-01",
        event_type="CONDITION_STARTED",
    )
    ctx_mixed = StructuredHealthContext(recent_timeline_events=[e_upload, e_clinical])
    res_mixed = evaluate_evidence(target, ctx_mixed)
    assert res_mixed.status == EvidenceStatus.SUFFICIENT
    assert len(res_mixed.matched_records) == 1
    assert res_mixed.matched_records[0].title == "Condition: Asthma"


def test_eval_timeline_entity_absent():
    """EVAL-08: Entity absent -> INSUFFICIENT with safe, honest directive."""
    e = _make_timeline_event(title="Condition: Asthma")
    ctx = StructuredHealthContext(recent_timeline_events=[e])

    target = InquiryTarget(
        candidate_structured_domains=["timeline"],
        target_entity="Diabetes",
    )
    res = evaluate_evidence(target, ctx)
    assert res.status == EvidenceStatus.INSUFFICIENT
    assert (
        "No timeline events were recorded matching: Diabetes." in res.evidence_directive
    )


def test_eval_timeline_partial_evidence():
    """EVAL-09: Some requested attributes absent -> PARTIALLY_SUFFICIENT (Rule B)."""
    e = _make_timeline_event(
        title="Medication: Lisinopril",
        description="dosage: 10mg",
    )
    ctx = StructuredHealthContext(recent_timeline_events=[e])

    target = InquiryTarget(
        candidate_structured_domains=["timeline"],
        target_entity="Lisinopril",
        requested_attributes=["dosage", "physician_name"],
    )
    res = evaluate_evidence(target, ctx)
    assert res.status == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert res.matched_fields == ["dosage"]
    assert res.missing_fields == ["physician_name"]
    assert "physician name" in res.evidence_directive


def test_eval_timeline_attribute_only():
    """EVAL-10: Attribute-only query preserves M5 attribute semantics (Rule C)."""
    e = _make_timeline_event(
        title="Medication: Lisinopril",
        description="dosage: 10mg, frequency: daily",
    )
    ctx = StructuredHealthContext(recent_timeline_events=[e])

    # 1. All present -> SUFFICIENT
    t1 = InquiryTarget(
        candidate_structured_domains=["timeline"],
        requested_attributes=["dosage", "frequency"],
    )
    res1 = evaluate_evidence(t1, ctx)
    assert res1.status == EvidenceStatus.SUFFICIENT
    assert set(res1.matched_fields) == {"dosage", "frequency"}

    # 2. Some present -> PARTIALLY_SUFFICIENT
    t2 = InquiryTarget(
        candidate_structured_domains=["timeline"],
        requested_attributes=["dosage", "clinic"],
    )
    res2 = evaluate_evidence(t2, ctx)
    assert res2.status == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert res2.matched_fields == ["dosage"]
    assert res2.missing_fields == ["clinic"]

    # 3. None present -> INSUFFICIENT
    t3 = InquiryTarget(
        candidate_structured_domains=["timeline"],
        requested_attributes=["clinic", "contact_number"],
    )
    res3 = evaluate_evidence(t3, ctx)
    assert res3.status == EvidenceStatus.INSUFFICIENT
    assert "No timeline events contain a record of:" in res3.evidence_directive


def test_eval_timeline_generic_query():
    """EVAL-11: Generic query: >=1 event -> SUFFICIENT, 0 -> INSUFFICIENT (Rule D)."""
    # >= 1 event
    ctx_with_events = StructuredHealthContext(
        recent_timeline_events=[_make_timeline_event()]
    )
    target = InquiryTarget(candidate_structured_domains=["timeline"])
    res_pos = evaluate_evidence(target, ctx_with_events)
    assert res_pos.status == EvidenceStatus.SUFFICIENT
    assert len(res_pos.matched_records) == 1

    # 0 events
    ctx_empty = StructuredHealthContext(recent_timeline_events=[])
    res_neg = evaluate_evidence(target, ctx_empty)
    assert res_neg.status == EvidenceStatus.INSUFFICIENT
    assert "Timeline events are not recorded." in res_neg.evidence_directive


def test_eval_timeline_anti_misattribution():
    """EVAL-12: Unrelated entity events never qualify into matched_records (Rule E)."""
    e1 = _make_timeline_event(title="Condition: Diabetes", description="Type 2")
    e2 = _make_timeline_event(title="Medication: Metformin", description="500mg daily")
    ctx = StructuredHealthContext(recent_timeline_events=[e1, e2])

    target = InquiryTarget(
        candidate_structured_domains=["timeline"],
        target_entity="Asthma",
    )
    res = evaluate_evidence(target, ctx)
    assert res.status == EvidenceStatus.INSUFFICIENT
    assert len(res.matched_records) == 0


def test_eval_multi_domain_pooling():
    """EVAL-13: Multi-domain dispatch and pooling with Rule F caveat propagation."""
    cond_id = uuid.uuid4()
    cond_record = _make_condition_response(
        cond_id=cond_id, name="Asthma", status="active"
    )

    timeline_src_id = uuid.uuid4()
    timeline_event = _make_timeline_event(
        title="Condition: Asthma",
        description="Recorded on timeline without clinical date",
        event_date="",  # undated
        source_id=timeline_src_id,
    )
    expected_timeline_id = generate_timeline_event_id(
        timeline_event.source_type,
        timeline_event.source_id,
        timeline_event.event_type,
    )

    ctx = StructuredHealthContext(
        conditions=[cond_record],
        recent_timeline_events=[timeline_event],
    )

    # -----------------------------------------------------------------------
    # Case 1: Caveat Preservation vs. Sufficient Domain
    # Timeline = PARTIALLY_SUFFICIENT (undated superlative), missing_fields = []
    # Conditions = SUFFICIENT, missing_fields = []
    # -----------------------------------------------------------------------
    target_case1 = InquiryTarget(
        candidate_structured_domains=["timeline", "conditions"],
        target_entity="Asthma",
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.ALL, superlative=SuperlativeType.LATEST
        ),
    )
    res_case1 = evaluate_evidence(target_case1, ctx)

    assert res_case1.status == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert "lack documented clinical dates" in res_case1.evidence_directive
    # Executable assertions proving BOTH domain records survive pooling:
    assert len(res_case1.matched_records) == 2
    timeline_recs = [
        r for r in res_case1.matched_records if isinstance(r, TimelineEventEvidence)
    ]
    condition_recs = [
        r for r in res_case1.matched_records if isinstance(r, ConditionResponse)
    ]
    assert len(timeline_recs) == 1
    assert len(condition_recs) == 1
    assert timeline_recs[0].id == expected_timeline_id
    assert condition_recs[0].id == cond_record.id

    # -----------------------------------------------------------------------
    # Case 2: Mixed Caveat & Missing Attribute Preservation
    # Timeline = PARTIALLY_SUFFICIENT, missing_fields = []
    # Conditions = PARTIALLY_SUFFICIENT, missing_fields = ["clinic"]
    # -----------------------------------------------------------------------
    target_case2 = InquiryTarget(
        candidate_structured_domains=["timeline", "conditions"],
        target_entity="Asthma",
        requested_attributes=["clinic"],
        temporal_constraint=TemporalConstraint(
            scope=TemporalScope.ALL, superlative=SuperlativeType.LATEST
        ),
    )
    res_case2 = evaluate_evidence(target_case2, ctx)

    assert res_case2.status == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert res_case2.missing_fields == ["clinic"]
    assert "lack documented clinical dates" in res_case2.evidence_directive
    assert "clinic" in res_case2.evidence_directive
    # Both domain records remain in matched_records
    assert len(res_case2.matched_records) == 2
    timeline_recs2 = [
        r for r in res_case2.matched_records if isinstance(r, TimelineEventEvidence)
    ]
    condition_recs2 = [
        r for r in res_case2.matched_records if isinstance(r, ConditionResponse)
    ]
    assert len(timeline_recs2) == 1
    assert len(condition_recs2) == 1
    assert timeline_recs2[0].id == expected_timeline_id
    assert condition_recs2[0].id == cond_record.id


# ===========================================================================
# Suite 4: Citation Integration Tests (CIT-01 .. CIT-06)
# ===========================================================================


def test_timeline_citation_emitted():
    """CIT-01: 'TIMELINE' citation emitted with SOURCE_RECORDED verification state."""
    src_id = uuid.uuid4()
    event = _make_timeline_event(
        title="Asthma Diagnosis",
        event_date="2024-03-15",
        event_type="CONDITION_STARTED",
        source_id=src_id,
    )
    ctx = StructuredHealthContext(recent_timeline_events=[event])
    record_map = _build_record_map(ctx)

    event_id = generate_timeline_event_id("CONDITION", src_id, "CONDITION_STARTED")
    assert event_id in record_map
    entity_type, label, verif_state = record_map[event_id]
    assert entity_type == "TIMELINE"
    assert label == "Asthma Diagnosis (Condition Started) - 2024-03-15"
    assert verif_state == VerificationState.SOURCE_RECORDED


def test_timeline_citation_stable_uuid5():
    """CIT-02: record_id in citation matches deterministic UUID5 generator."""
    src_id = uuid.uuid4()
    event = _make_timeline_event(
        title="Albuterol Prescription",
        event_type="MEDICATION_STARTED",
        source_type="MEDICATION",
        source_id=src_id,
    )
    wrapped = TimelineEventEvidence(**event.model_dump())
    expected_uuid5 = generate_timeline_event_id(
        "MEDICATION", src_id, "MEDICATION_STARTED"
    )

    assert wrapped.id == expected_uuid5
    assert wrapped.id.version == 5

    ctx = StructuredHealthContext(recent_timeline_events=[event])
    record_map = _build_record_map(ctx)
    assert wrapped.id in record_map


@pytest.mark.asyncio
async def test_condition_events_both_survive(
    async_client: AsyncClient, db: AsyncSession
):
    """CIT-03: Same source_id STARTED + RESOLVED survive independently."""
    cond_src_id = uuid.uuid4()
    e_start = _make_timeline_event(
        title="Asthma",
        event_type="CONDITION_STARTED",
        event_date="2022-01-01",
        source_id=cond_src_id,
    )
    e_resolved = _make_timeline_event(
        title="Asthma",
        event_type="CONDITION_RESOLVED",
        event_date="2024-01-01",
        source_id=cond_src_id,
    )

    ctx = StructuredHealthContext(recent_timeline_events=[e_start, e_resolved])
    record_map = _build_record_map(ctx)

    id_start = generate_timeline_event_id("CONDITION", cond_src_id, "CONDITION_STARTED")
    id_res = generate_timeline_event_id("CONDITION", cond_src_id, "CONDITION_RESOLVED")

    assert id_start in record_map
    assert id_res in record_map
    assert id_start != id_res

    # Test via API pipeline: both IDs cited by LLM
    with (
        patch("app.api.health_inquiry.evaluate_safety") as mock_safe,
        patch("app.api.health_inquiry.parse_natural_language_query") as mock_pq,
        patch(
            "app.api.health_inquiry.get_or_create_patient", new_callable=AsyncMock
        ) as mock_pt,
        patch(
            "app.api.health_inquiry.build_inquiry_context", new_callable=AsyncMock
        ) as mock_ctx,
        patch("app.api.health_inquiry.evaluate_evidence") as mock_ev,
        patch("app.api.health_inquiry.get_llm_gateway") as mock_gw,
    ):
        mock_safe.return_value = SafetyGuardrailState(triggered=False)
        mock_pq.return_value = InquiryTarget(
            candidate_structured_domains=["timeline"],
            routing_mode=RoutingMode.STRUCTURED_ONLY,
        )
        mock_pt.return_value = Patient(id=uuid.uuid4())
        mock_ctx.return_value = ctx
        mock_ev.return_value = EvidenceResult(
            status=EvidenceStatus.SUFFICIENT,
            matched_records=[
                TimelineEventEvidence(**e_start.model_dump()),
                TimelineEventEvidence(**e_resolved.model_dump()),
            ],
        )

        mock_llm = AsyncMock()
        mock_llm.synthesize_response.return_value = SynthesisResult(
            answer_text="Asthma started in 2022 and resolved in 2024.",
            cited_record_ids=[id_start, id_res],
            cited_tokens=["", ""],
        )
        mock_gw.return_value = mock_llm

        user, token = await create_user_and_token()
        response = await async_client.post(
            "/api/v1/health-inquiry",
            json={"query": "What is my timeline for Asthma?"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        citations = data["citations"]
        assert len(citations) == 2
        assert citations[0]["record_id"] == str(id_start)
        assert citations[1]["record_id"] == str(id_res)
        assert citations[0]["entity_type"] == "TIMELINE"
        assert citations[1]["entity_type"] == "TIMELINE"


@pytest.mark.asyncio
async def test_medication_events_both_survive(
    async_client: AsyncClient, db: AsyncSession
):
    """CIT-04: Same source_id / STARTED + STOPPED survive independently without drop."""
    med_src_id = uuid.uuid4()
    e_start = _make_timeline_event(
        title="Lisinopril",
        event_type="MEDICATION_STARTED",
        source_type="MEDICATION",
        source_id=med_src_id,
        event_date="2023-01-01",
    )
    e_stop = _make_timeline_event(
        title="Lisinopril",
        event_type="MEDICATION_STOPPED",
        source_type="MEDICATION",
        source_id=med_src_id,
        event_date="2024-01-01",
    )

    ctx = StructuredHealthContext(recent_timeline_events=[e_start, e_stop])
    id_start = generate_timeline_event_id(
        "MEDICATION", med_src_id, "MEDICATION_STARTED"
    )
    id_stop = generate_timeline_event_id("MEDICATION", med_src_id, "MEDICATION_STOPPED")

    with (
        patch("app.api.health_inquiry.evaluate_safety") as mock_safe,
        patch("app.api.health_inquiry.parse_natural_language_query") as mock_pq,
        patch(
            "app.api.health_inquiry.get_or_create_patient", new_callable=AsyncMock
        ) as mock_pt,
        patch(
            "app.api.health_inquiry.build_inquiry_context", new_callable=AsyncMock
        ) as mock_ctx,
        patch("app.api.health_inquiry.evaluate_evidence") as mock_ev,
        patch("app.api.health_inquiry.get_llm_gateway") as mock_gw,
    ):
        mock_safe.return_value = SafetyGuardrailState(triggered=False)
        mock_pq.return_value = InquiryTarget(
            candidate_structured_domains=["timeline"],
            routing_mode=RoutingMode.STRUCTURED_ONLY,
        )
        mock_pt.return_value = Patient(id=uuid.uuid4())
        mock_ctx.return_value = ctx
        mock_ev.return_value = EvidenceResult(status=EvidenceStatus.SUFFICIENT)

        mock_llm = AsyncMock()
        mock_llm.synthesize_response.return_value = SynthesisResult(
            answer_text="Lisinopril timeline.",
            cited_record_ids=[id_start, id_stop],
            cited_tokens=["", ""],
        )
        mock_gw.return_value = mock_llm

        user, token = await create_user_and_token()
        response = await async_client.post(
            "/api/v1/health-inquiry",
            json={"query": "Lisinopril timeline?"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        citations = data["citations"]
        assert len(citations) == 2
        assert {c["record_id"] for c in citations} == {str(id_start), str(id_stop)}


@pytest.mark.asyncio
async def test_no_overlap_with_structured(async_client: AsyncClient, db: AsyncSession):
    """CIT-05: Timeline UUID5 does not overwrite structured citations."""
    cond_id = uuid.uuid4()
    cond = _make_condition_response(cond_id=cond_id, name="Asthma", status="active")
    e_tl = _make_timeline_event(
        title="Asthma Started",
        event_type="CONDITION_STARTED",
        source_id=cond_id,
    )
    tl_id = generate_timeline_event_id("CONDITION", cond_id, "CONDITION_STARTED")

    ctx = StructuredHealthContext(
        conditions=[cond],
        recent_timeline_events=[e_tl],
    )
    record_map = _build_record_map(ctx)
    assert cond_id in record_map
    assert tl_id in record_map
    assert cond_id != tl_id

    with (
        patch("app.api.health_inquiry.evaluate_safety") as mock_safe,
        patch("app.api.health_inquiry.parse_natural_language_query") as mock_pq,
        patch(
            "app.api.health_inquiry.get_or_create_patient", new_callable=AsyncMock
        ) as mock_pt,
        patch(
            "app.api.health_inquiry.build_inquiry_context", new_callable=AsyncMock
        ) as mock_ctx,
        patch("app.api.health_inquiry.evaluate_evidence") as mock_ev,
        patch("app.api.health_inquiry.get_llm_gateway") as mock_gw,
    ):
        mock_safe.return_value = SafetyGuardrailState(triggered=False)
        mock_pq.return_value = InquiryTarget(
            candidate_structured_domains=["conditions", "timeline"],
            routing_mode=RoutingMode.STRUCTURED_ONLY,
        )
        mock_pt.return_value = Patient(id=uuid.uuid4())
        mock_ctx.return_value = ctx
        mock_ev.return_value = EvidenceResult(status=EvidenceStatus.SUFFICIENT)

        mock_llm = AsyncMock()
        mock_llm.synthesize_response.return_value = SynthesisResult(
            answer_text="Asthma record and timeline.",
            cited_record_ids=[cond_id, tl_id],
            cited_tokens=["", ""],
        )
        mock_gw.return_value = mock_llm

        user, token = await create_user_and_token()
        response = await async_client.post(
            "/api/v1/health-inquiry",
            json={"query": "Tell me about my asthma."},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        citations = response.json()["citations"]
        assert len(citations) == 2
        entity_types = {c["entity_type"] for c in citations}
        assert entity_types == {"CONDITION", "TIMELINE"}


@pytest.mark.asyncio
async def test_existing_citations_preserved(
    async_client: AsyncClient, db: AsyncSession
):
    """CIT-06: Existing document tokens & structured citations continue functioning."""
    cond_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    tl_event = _make_timeline_event(title="Timeline Event")
    tl_id = generate_timeline_event_id(
        tl_event.source_type, tl_event.source_id, tl_event.event_type
    )

    ctx = StructuredHealthContext(
        conditions=[
            _make_condition_response(
                cond_id=cond_id, name="Hypertension", status="active"
            )
        ],
        documents=[
            DocumentEvidenceContext(
                document_id=doc_id,
                display_name="Lab Results",
                document_type="lab_result",
                extracted_excerpt="Blood pressure 120/80",
            )
        ],
        recent_timeline_events=[tl_event],
    )

    record_map = _build_record_map(ctx)
    assert cond_id in record_map
    assert doc_id in record_map
    assert tl_id in record_map

    assert record_map[cond_id][0] == "CONDITION"
    assert record_map[doc_id][0] == "DOCUMENT"
    assert record_map[tl_id][0] == "TIMELINE"
