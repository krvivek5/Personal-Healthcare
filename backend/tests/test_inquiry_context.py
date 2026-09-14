import uuid
from datetime import date, datetime, timezone

import pytest

from app.db.models import (
    Allergy,
    Condition,
    HealthProfile,
    MedicalDocument,
    Medication,
    Patient,
    PatientGoal,
    Symptom,
)
from app.health.inquiry_context import build_inquiry_context


def _create_patient(db, patient_id: uuid.UUID = None) -> uuid.UUID:
    patient_id = patient_id or uuid.uuid4()
    user_id = uuid.uuid4()
    p = Patient(id=patient_id, user_id=user_id)
    db.add(p)
    return patient_id


@pytest.mark.asyncio
async def test_full_structured_context_assembly(db):
    """1. Full structured context assembly for one patient."""
    patient_id = _create_patient(db)

    profile = HealthProfile(patient_id=patient_id, biological_sex="male")
    cond = Condition(
        patient_id=patient_id,
        name="Asthma",
        status="active",
        source_type="PATIENT_REPORTED",
    )
    med = Medication(
        patient_id=patient_id,
        name="Albuterol",
        status="active",
        source_type="PATIENT_REPORTED",
    )
    alg = Allergy(
        patient_id=patient_id, allergen="Peanuts", source_type="PATIENT_REPORTED"
    )
    sym = Symptom(patient_id=patient_id, name="Cough", source_type="PATIENT_REPORTED")
    goal = PatientGoal(
        patient_id=patient_id,
        description="Lose weight",
        status="active",
        source_type="PATIENT_REPORTED",
    )

    doc = MedicalDocument(
        patient_id=patient_id,
        file_name="test.pdf",
        display_name="Test Doc",
        document_type="lab_result",
        content_type="application/pdf",
        file_size_bytes=1024,
        storage_key="test.pdf",
    )

    db.add_all([profile, cond, med, alg, sym, goal, doc])
    await db.commit()

    ctx = await build_inquiry_context(db, patient_id)

    assert ctx.profile is not None
    assert ctx.profile.biological_sex == "male"

    assert len(ctx.conditions) == 1
    assert ctx.conditions[0].name == "Asthma"

    assert len(ctx.medications) == 1
    assert ctx.medications[0].name == "Albuterol"

    assert len(ctx.allergies) == 1
    assert ctx.allergies[0].allergen == "Peanuts"

    assert len(ctx.symptoms) == 1
    assert ctx.symptoms[0].name == "Cough"

    assert len(ctx.goals) == 1
    assert ctx.goals[0].description == "Lose weight"


@pytest.mark.asyncio
async def test_patient_isolation(db):
    """2. Patient isolation: records for another patient are never included."""
    p1 = _create_patient(db)
    p2 = _create_patient(db)

    db.add(
        Condition(
            patient_id=p1,
            name="Cond P1",
            status="active",
            source_type="PATIENT_REPORTED",
        )
    )
    db.add(
        Condition(
            patient_id=p2,
            name="Cond P2",
            status="active",
            source_type="PATIENT_REPORTED",
        )
    )

    db.add(
        Medication(
            patient_id=p1,
            name="Med P1",
            status="active",
            source_type="PATIENT_REPORTED",
        )
    )
    db.add(
        Medication(
            patient_id=p2,
            name="Med P2",
            status="active",
            source_type="PATIENT_REPORTED",
        )
    )

    await db.commit()

    ctx1 = await build_inquiry_context(db, p1)
    assert len(ctx1.conditions) == 1
    assert ctx1.conditions[0].name == "Cond P1"
    assert len(ctx1.medications) == 1
    assert ctx1.medications[0].name == "Med P1"

    ctx2 = await build_inquiry_context(db, p2)
    assert len(ctx2.conditions) == 1
    assert ctx2.conditions[0].name == "Cond P2"


@pytest.mark.asyncio
async def test_temporal_states_and_timeline(db):
    """
    Test 3, 4, 5, 6, 7, 8: Correct temporal states for all domains,
    plus timeline preservation and Allergy lack of inferred state.
    """
    p = _create_patient(db)

    # Condition: status and ended_at
    db.add(
        Condition(
            patient_id=p,
            name="Active Cond",
            status="active",
            started_at=date(2020, 1, 1),
            source_type="PATIENT_REPORTED",
        )
    )
    db.add(
        Condition(
            patient_id=p,
            name="Resolved Cond",
            status="resolved",
            ended_at=date(2021, 1, 1),
            source_type="PATIENT_REPORTED",
        )
    )

    # Medication: status and ended_at
    db.add(
        Medication(
            patient_id=p,
            name="Active Med",
            status="active",
            started_at=date(2022, 1, 1),
            source_type="PATIENT_REPORTED",
        )
    )
    db.add(
        Medication(
            patient_id=p,
            name="Stopped Med",
            status="stopped",
            ended_at=date(2023, 1, 1),
            source_type="PATIENT_REPORTED",
        )
    )

    # Symptom: started_at and ended_at
    db.add(
        Symptom(
            patient_id=p,
            name="Past Symptom",
            started_at=date(2021, 5, 1),
            ended_at=date(2021, 5, 5),
            recorded_at=datetime(2021, 5, 1, tzinfo=timezone.utc),
            source_type="PATIENT_REPORTED",
        )
    )

    # Allergy: recorded entry only, no active/resolved
    db.add(Allergy(patient_id=p, allergen="Dust", source_type="PATIENT_REPORTED"))

    # Goal: status
    db.add(
        PatientGoal(
            patient_id=p,
            description="Active Goal",
            status="active",
            recorded_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            source_type="PATIENT_REPORTED",
        )
    )
    db.add(
        PatientGoal(
            patient_id=p,
            description="Achieved Goal",
            status="achieved",
            recorded_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
            source_type="PATIENT_REPORTED",
        )
    )

    await db.commit()

    ctx = await build_inquiry_context(db, p)

    # 3. Condition temporal state
    assert len(ctx.conditions) == 2
    active_c = next(c for c in ctx.conditions if c.name == "Active Cond")
    res_c = next(c for c in ctx.conditions if c.name == "Resolved Cond")
    assert active_c.status == "active"
    assert active_c.started_at == date(2020, 1, 1)
    assert res_c.status == "resolved"
    assert res_c.ended_at == date(2021, 1, 1)

    # 4. Medication temporal state
    assert len(ctx.medications) == 2
    active_m = next(m for m in ctx.medications if m.name == "Active Med")
    stop_m = next(m for m in ctx.medications if m.name == "Stopped Med")
    assert active_m.status == "active"
    assert active_m.started_at == date(2022, 1, 1)
    assert stop_m.status == "stopped"
    assert stop_m.ended_at == date(2023, 1, 1)

    # 5. Symptom temporal state
    assert len(ctx.symptoms) == 1
    assert ctx.symptoms[0].started_at == date(2021, 5, 1)
    assert ctx.symptoms[0].ended_at == date(2021, 5, 5)

    # 6. Allergy remains recorded entry without inferred active/resolved state
    assert len(ctx.allergies) == 1
    assert not hasattr(ctx.allergies[0], "status")
    assert not hasattr(ctx.allergies[0], "ended_at")

    # 7. Goal state mapping
    assert len(ctx.goals) == 2
    active_g = next(g for g in ctx.goals if g.description == "Active Goal")
    ach_g = next(g for g in ctx.goals if g.description == "Achieved Goal")
    assert active_g.status == "active"
    assert ach_g.status == "achieved"

    # 8. Timeline event state preservation
    # Verify that events exist and event_state is carried over
    timeline_types = [e.event_type for e in ctx.recent_timeline_events]
    assert "CONDITION_STARTED" in timeline_types
    assert "CONDITION_RESOLVED" in timeline_types
    assert "MEDICATION_STARTED" in timeline_types
    assert "MEDICATION_STOPPED" in timeline_types
    assert "SYMPTOM_RECORDED" in timeline_types
    assert "GOAL_RECORDED" in timeline_types

    c_res_event = next(
        e for e in ctx.recent_timeline_events if e.event_type == "CONDITION_RESOLVED"
    )
    assert c_res_event.event_state == "historical"
    c_start_event = next(
        e for e in ctx.recent_timeline_events if e.event_type == "CONDITION_STARTED"
    )
    assert c_start_event.event_state == "current"


@pytest.mark.asyncio
async def test_empty_domains_safe(db):
    """9. Empty domains are represented safely."""
    patient_id = _create_patient(db)
    await db.commit()

    ctx = await build_inquiry_context(db, patient_id)
    assert ctx.profile is None
    assert ctx.conditions == []
    assert ctx.medications == []
    assert ctx.allergies == []
    assert ctx.symptoms == []
    assert ctx.goals == []
    assert ctx.recent_timeline_events == []


@pytest.mark.asyncio
async def test_medical_documents_not_loaded(db):
    """10. MedicalDocument contents are never loaded into the context."""
    patient_id = _create_patient(db)

    doc = MedicalDocument(
        patient_id=patient_id,
        file_name="test.pdf",
        display_name="Test Doc",
        document_type="lab_result",
        content_type="application/pdf",
        file_size_bytes=1024,
        storage_key="test.pdf",
    )
    db.add(doc)
    await db.commit()

    ctx = await build_inquiry_context(db, patient_id)

    # Context does not expose documents
    assert not hasattr(ctx, "documents")
    assert not hasattr(ctx, "medical_documents")

    # The timeline might expose a DOCUMENT_UPLOADED event but NO content
    # Let's ensure the event doesn't leak content
    doc_events = [e for e in ctx.recent_timeline_events if e.source_type == "DOCUMENT"]
    if doc_events:
        for event in doc_events:
            assert "application/pdf" not in str(event.description)
            assert not hasattr(event, "file_size")
            assert not hasattr(event, "storage_key")
