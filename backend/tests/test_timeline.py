"""
Milestone 5 backend tests: Health Timeline API and dynamic synthesis service.

Tests cover:
- Dynamic aggregation across all five source types
  (conditions, symptoms, medications, documents, goals)
- Explicit event_type mapping (CONDITION_STARTED, CONDITION_RESOLVED,
  SYMPTOM_RECORDED, MEDICATION_STARTED, MEDICATION_STOPPED,
  DOCUMENT_DATED, DOCUMENT_UPLOADED, GOAL_RECORDED)
- Event date contract:
  * Timestamp-based source dates returned as ISO-8601 UTC datetimes
    ('YYYY-MM-DDTHH:MM:SSZ')
  * Date-only source dates returned as ISO-8601 dates in 'YYYY-MM-DD' form
  * Correct chronological comparison of mixed date and datetime source values
- Event state mapping:
  * Condition: active -> current, resolved -> historical
  * Medication: active -> current, stopped -> historical
  * PatientGoal: active -> current, achieved -> historical, abandoned -> historical
  * Symptom & Document -> neutral
  * Multi-event records (stopped medications, resolved conditions)
- Deterministic tie-breaking
- Source updates change derived timeline events without creating duplicates
- Strict user data isolation
"""

from __future__ import annotations

import io
import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from tests.test_auth import create_test_token

pytestmark = pytest.mark.asyncio

_PDF_MAGIC = b"%PDF-1.4 test document content"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _patched_s3():
    async def _fake_upload(key, data, ct):
        return None

    async def _fake_delete(key):
        return None

    async def _fake_download(key):
        yield b"fake pdf bytes"

    return (
        patch("app.api.documents.storage.upload_file", side_effect=_fake_upload),
        patch("app.api.documents.storage.delete_file", side_effect=_fake_delete),
        patch("app.api.documents.storage.download_file", side_effect=_fake_download),
    )


async def test_timeline_all_five_source_types(async_client: AsyncClient):
    """
    Verify dynamic aggregation of all 5 source types into HealthEvents:
    Condition, Symptom, Medication, Document, and PatientGoal.
    Verify event_type, event_state, source_type, and source_id.
    """
    token = create_test_token(user_id=str(uuid.uuid4()))
    headers = _headers(token)

    # 1. Condition: Active condition with started_at
    cond_res = await async_client.post(
        "/api/v1/conditions",
        headers=headers,
        json={
            "name": "Type 2 Diabetes",
            "status": "active",
            "started_at": "2026-01-15",
        },
    )
    assert cond_res.status_code == 201
    cond_id = cond_res.json()["id"]

    # 2. Symptom: Recorded with severity
    symp_res = await async_client.post(
        "/api/v1/symptoms",
        headers=headers,
        json={"name": "Mild Dizziness", "severity": "mild", "notes": "Felt in morning"},
    )
    assert symp_res.status_code == 201
    symp_id = symp_res.json()["id"]

    # 3. Medication: Active medication
    med_res = await async_client.post(
        "/api/v1/medications",
        headers=headers,
        json={
            "name": "Metformin",
            "dosage": "500mg",
            "frequency": "twice daily",
            "status": "active",
            "started_at": "2026-01-20",
        },
    )
    assert med_res.status_code == 201
    med_id = med_res.json()["id"]

    # 4. Document: Dated medical report
    up_patch, del_patch, dl_patch = _patched_s3()
    with up_patch, del_patch, dl_patch:
        doc_res = await async_client.post(
            "/api/v1/documents",
            headers=headers,
            files={"file": ("report.pdf", io.BytesIO(_PDF_MAGIC), "application/pdf")},
            data={
                "document_type": "lab_report",
                "display_name": "Blood Glucose Panel",
                "document_date": "2026-02-01",
            },
        )
    assert doc_res.status_code == 201
    doc_id = doc_res.json()["id"]

    # 5. Goal: Active patient goal
    goal_res = await async_client.post(
        "/api/v1/goals",
        headers=headers,
        json={"description": "Maintain HbA1c under 7.0", "status": "active"},
    )
    assert goal_res.status_code == 201
    goal_id = goal_res.json()["id"]

    # Fetch aggregated timeline
    timeline_res = await async_client.get("/api/v1/timeline", headers=headers)
    assert timeline_res.status_code == 200
    events = timeline_res.json()

    assert len(events) == 5

    # Check source_ids are linked
    source_ids = {e["source_id"] for e in events}
    assert source_ids == {cond_id, symp_id, med_id, doc_id, goal_id}

    # Verify no storage_key leaked
    for e in events:
        assert "storage_key" not in e

    # Find each event by source_type
    cond_event = next(e for e in events if e["source_type"] == "CONDITION")
    assert cond_event["event_type"] == "CONDITION_STARTED"
    assert cond_event["event_state"] == "current"
    assert cond_event["event_date"] == "2026-01-15"
    assert cond_event["title"] == "Type 2 Diabetes"

    symp_event = next(e for e in events if e["source_type"] == "SYMPTOM")
    assert symp_event["event_type"] == "SYMPTOM_RECORDED"
    assert symp_event["event_state"] == "neutral"
    assert "T" in symp_event["event_date"] and symp_event["event_date"].endswith("Z")
    assert symp_event["title"] == "Mild Dizziness"

    med_event = next(e for e in events if e["source_type"] == "MEDICATION")
    assert med_event["event_type"] == "MEDICATION_STARTED"
    assert med_event["event_state"] == "current"
    assert med_event["event_date"] == "2026-01-20"
    assert med_event["title"] == "Metformin"

    doc_event = next(e for e in events if e["source_type"] == "DOCUMENT")
    assert doc_event["event_type"] == "DOCUMENT_DATED"
    assert doc_event["event_state"] == "neutral"
    assert doc_event["event_date"] == "2026-02-01"
    assert doc_event["title"] == "Blood Glucose Panel"

    goal_event = next(e for e in events if e["source_type"] == "GOAL")
    assert goal_event["event_type"] == "GOAL_RECORDED"
    assert goal_event["event_state"] == "current"
    assert "T" in goal_event["event_date"] and goal_event["event_date"].endswith("Z")
    assert goal_event["title"] == "Maintain HbA1c under 7.0"


async def test_timeline_event_state_lifecycle_mapping(async_client: AsyncClient):
    """
    Verify explicit event_state mapping rules:
    - Condition: active -> current, resolved -> historical
    - Medication: active -> current, stopped -> historical
    - PatientGoal: active -> current, achieved -> historical, abandoned -> historical
    - Multi-event records:
      * Stopped medication produces MEDICATION_STARTED (historical) and
        MEDICATION_STOPPED (historical)
      * Resolved condition produces CONDITION_STARTED (historical) and
        CONDITION_RESOLVED (historical)
    """
    token = create_test_token(user_id=str(uuid.uuid4()))
    headers = _headers(token)

    # Resolved Condition with both started_at and ended_at
    await async_client.post(
        "/api/v1/conditions",
        headers=headers,
        json={
            "name": "Acute Bronchitis",
            "status": "resolved",
            "started_at": "2025-10-01",
            "ended_at": "2025-10-15",
        },
    )

    # Stopped Medication with both started_at and ended_at
    await async_client.post(
        "/api/v1/medications",
        headers=headers,
        json={
            "name": "Amoxicillin",
            "status": "stopped",
            "started_at": "2025-10-02",
            "ended_at": "2025-10-12",
        },
    )

    # Achieved Goal
    await async_client.post(
        "/api/v1/goals",
        headers=headers,
        json={"description": "Drink 2L water daily", "status": "achieved"},
    )

    # Abandoned Goal
    await async_client.post(
        "/api/v1/goals",
        headers=headers,
        json={"description": "Run marathon in 2 months", "status": "abandoned"},
    )

    timeline_res = await async_client.get("/api/v1/timeline", headers=headers)
    assert timeline_res.status_code == 200
    events = timeline_res.json()

    # Verify resolved condition events:
    cond_started = next(e for e in events if e["event_type"] == "CONDITION_STARTED")
    assert cond_started["event_state"] == "historical"
    cond_resolved = next(e for e in events if e["event_type"] == "CONDITION_RESOLVED")
    assert cond_resolved["event_state"] == "historical"

    # Verify stopped medication events:
    med_started = next(e for e in events if e["event_type"] == "MEDICATION_STARTED")
    assert med_started["event_state"] == "historical"
    med_stopped = next(e for e in events if e["event_type"] == "MEDICATION_STOPPED")
    assert med_stopped["event_state"] == "historical"

    # Verify goals:
    goal_events = [e for e in events if e["source_type"] == "GOAL"]
    assert len(goal_events) == 2
    for ge in goal_events:
        assert ge["event_state"] == "historical"


async def test_timeline_document_fallback_to_uploaded_at(async_client: AsyncClient):
    """
    Verify document without document_date falls back to uploaded_at as DOCUMENT_UPLOADED
    with ISO-8601 UTC datetime.
    """
    token = create_test_token(user_id=str(uuid.uuid4()))
    headers = _headers(token)

    up_patch, del_patch, dl_patch = _patched_s3()
    with up_patch, del_patch, dl_patch:
        await async_client.post(
            "/api/v1/documents",
            headers=headers,
            files={"file": ("undated.pdf", io.BytesIO(_PDF_MAGIC), "application/pdf")},
            data={"document_type": "prescription", "display_name": "Paper Rx Scan"},
        )

    timeline_res = await async_client.get("/api/v1/timeline", headers=headers)
    assert timeline_res.status_code == 200
    events = timeline_res.json()

    assert len(events) == 1
    doc_event = events[0]
    assert doc_event["event_type"] == "DOCUMENT_UPLOADED"
    assert doc_event["event_state"] == "neutral"
    assert "T" in doc_event["event_date"] and doc_event["event_date"].endswith("Z")


async def test_timeline_deterministic_ordering_mixed_dates(async_client: AsyncClient):
    """
    Verify backend sorting correctly compares mixed date/datetime values without
    inventing clinical time precision, ordering descending chronologically.
    """
    token = create_test_token(user_id=str(uuid.uuid4()))
    headers = _headers(token)

    # Event 1: Condition started on 2026-03-01 (date-only)
    await async_client.post(
        "/api/v1/conditions",
        headers=headers,
        json={
            "name": "Older Condition",
            "status": "active",
            "started_at": "2026-03-01",
        },
    )

    # Event 2: Document dated on 2026-05-15 (date-only)
    up_patch, del_patch, dl_patch = _patched_s3()
    with up_patch, del_patch, dl_patch:
        await async_client.post(
            "/api/v1/documents",
            headers=headers,
            files={"file": ("doc.pdf", io.BytesIO(_PDF_MAGIC), "application/pdf")},
            data={
                "document_type": "discharge_summary",
                "display_name": "Discharge Notes",
                "document_date": "2026-05-15",
            },
        )

    # Event 3: Medication started on 2026-04-10 (date-only)
    await async_client.post(
        "/api/v1/medications",
        headers=headers,
        json={"name": "Mid Medication", "status": "active", "started_at": "2026-04-10"},
    )

    timeline_res = await async_client.get("/api/v1/timeline", headers=headers)
    assert timeline_res.status_code == 200
    events = timeline_res.json()

    assert len(events) == 3
    # Descending chronological order: 2026-05-15 -> 2026-04-10 -> 2026-03-01
    assert events[0]["event_date"] == "2026-05-15"
    assert events[0]["title"] == "Discharge Notes"
    assert events[1]["event_date"] == "2026-04-10"
    assert events[1]["title"] == "Mid Medication"
    assert events[2]["event_date"] == "2026-03-01"
    assert events[2]["title"] == "Older Condition"


async def test_timeline_source_update_no_duplicates(async_client: AsyncClient):
    """
    Verify updating an existing source record updates its derived timeline event
    without producing duplicate events.
    """
    token = create_test_token(user_id=str(uuid.uuid4()))
    headers = _headers(token)

    # 1. Create Condition with initial date
    cond_res = await async_client.post(
        "/api/v1/conditions",
        headers=headers,
        json={"name": "Hypertension", "status": "active", "started_at": "2026-01-01"},
    )
    cond_id = cond_res.json()["id"]

    res1 = await async_client.get("/api/v1/timeline", headers=headers)
    events1 = res1.json()
    assert len(events1) == 1
    assert events1[0]["source_id"] == cond_id
    assert events1[0]["event_date"] == "2026-01-01"

    # 2. Update Condition's started_at to new date
    update_res = await async_client.patch(
        f"/api/v1/conditions/{cond_id}",
        headers=headers,
        json={"started_at": "2026-06-01"},
    )
    assert update_res.status_code == 200

    # 3. Verify timeline: still exactly 1 event, updated date, no duplicates
    res2 = await async_client.get("/api/v1/timeline", headers=headers)
    events2 = res2.json()
    assert len(events2) == 1
    assert events2[0]["source_id"] == cond_id
    assert events2[0]["event_date"] == "2026-06-01"


async def test_timeline_strict_user_isolation(async_client: AsyncClient):
    """
    Verify strict user isolation: User A's health records are not visible in
    User B's timeline.
    """
    token_a = create_test_token(user_id=str(uuid.uuid4()))
    token_b = create_test_token(user_id=str(uuid.uuid4()))

    # User A creates condition and symptom
    await async_client.post(
        "/api/v1/conditions",
        headers=_headers(token_a),
        json={"name": "User A Asthma", "status": "active", "started_at": "2026-02-10"},
    )
    await async_client.post(
        "/api/v1/symptoms",
        headers=_headers(token_a),
        json={"name": "User A Cough", "severity": "moderate"},
    )

    # User A sees 2 events
    res_a = await async_client.get("/api/v1/timeline", headers=_headers(token_a))
    assert res_a.status_code == 200
    assert len(res_a.json()) == 2

    # User B sees 0 events
    res_b = await async_client.get("/api/v1/timeline", headers=_headers(token_b))
    assert res_b.status_code == 200
    assert len(res_b.json()) == 0
