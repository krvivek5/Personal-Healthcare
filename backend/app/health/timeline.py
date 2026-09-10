from __future__ import annotations

import functools
import uuid
from datetime import date, datetime, timezone
from typing import Union

from sqlalchemy.ext.asyncio import AsyncSession

from app.health.conditions import get_conditions
from app.health.documents import get_documents
from app.health.goals import get_goals
from app.health.medications import get_medications
from app.health.symptoms import get_symptoms
from app.schemas.timeline import HealthEvent


def _format_source_date(val: Union[datetime, date]) -> str:
    """
    Format source date into canonical API representation:
    - timestamp-based source dates are returned as ISO-8601 UTC datetimes
      ('YYYY-MM-DDTHH:MM:SSZ');
    - date-only source dates are returned as ISO-8601 dates in 'YYYY-MM-DD' form.
    """
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    elif isinstance(val, date):
        return val.strftime("%Y-%m-%d")
    return str(val)


def _timeline_sort_comparator(
    a: tuple[HealthEvent, datetime],
    b: tuple[HealthEvent, datetime],
) -> int:
    """
    Deterministic comparator for HealthEvents:
    1. Primary: event_date descending.
       Lexicographical ISO-8601 string comparison cleanly orders dates (YYYY-MM-DD)
       and UTC datetimes (YYYY-MM-DDTHH:MM:SSZ) across calendar days without
       inventing artificial time precision for date-only sources.
    2. Secondary tie-breaker: created_at descending.
    3. Tertiary tie-breaker: source_type ascending.
    4. Quaternary tie-breaker: source_id ascending.
    5. Quinary tie-breaker: event_type ascending.
    """
    event_a, created_a = a
    event_b, created_b = b

    # 1. Primary: event_date descending
    if event_a.event_date != event_b.event_date:
        return -1 if event_a.event_date > event_b.event_date else 1

    # 2. Secondary: created_at descending
    ca = (
        created_a
        if (created_a and created_a.tzinfo)
        else (
            created_a.replace(tzinfo=timezone.utc)
            if created_a
            else datetime.min.replace(tzinfo=timezone.utc)
        )
    )
    cb = (
        created_b
        if (created_b and created_b.tzinfo)
        else (
            created_b.replace(tzinfo=timezone.utc)
            if created_b
            else datetime.min.replace(tzinfo=timezone.utc)
        )
    )
    if ca != cb:
        return -1 if ca > cb else 1

    # 3. Tertiary: source_type ascending
    if event_a.source_type != event_b.source_type:
        return -1 if event_a.source_type < event_b.source_type else 1

    # 4. Quaternary: source_id ascending
    id_a = str(event_a.source_id)
    id_b = str(event_b.source_id)
    if id_a != id_b:
        return -1 if id_a < id_b else 1

    # 5. Quinary: event_type ascending
    if event_a.event_type != event_b.event_type:
        return -1 if event_a.event_type < event_b.event_type else 1

    return 0


async def get_timeline(db: AsyncSession, patient_id: uuid.UUID) -> list[HealthEvent]:
    """
    Dynamically synthesize the health timeline for a patient from authoritative
    source records.

    Follows explicit event-per-source mapping:
    - Condition:
        * started_at -> CONDITION_STARTED (current if active, historical if resolved)
        * ended_at -> CONDITION_RESOLVED (historical)
    - Symptom:
        * recorded_at -> SYMPTOM_RECORDED (neutral)
    - Medication:
        * started_at -> MEDICATION_STARTED (current if active, historical if stopped)
        * ended_at -> MEDICATION_STOPPED (historical)
    - Document:
        * document_date -> DOCUMENT_DATED (neutral)
        * uploaded_at (fallback if document_date is null) -> DOCUMENT_UPLOADED (neutral)
    - PatientGoal:
        * recorded_at -> GOAL_RECORDED (current if active,
          historical if achieved/abandoned)
    """
    raw_events: list[tuple[HealthEvent, datetime]] = []

    # 1. Conditions
    conditions = await get_conditions(db, patient_id)
    for c in conditions:
        is_active = c.status == "active"
        if c.started_at is not None:
            raw_events.append(
                (
                    HealthEvent(
                        event_date=_format_source_date(c.started_at),
                        event_type="CONDITION_STARTED",
                        event_state="current" if is_active else "historical",
                        title=c.name,
                        description=c.notes,
                        source_type="CONDITION",
                        source_id=c.id,
                    ),
                    c.created_at,
                )
            )
        if c.ended_at is not None:
            raw_events.append(
                (
                    HealthEvent(
                        event_date=_format_source_date(c.ended_at),
                        event_type="CONDITION_RESOLVED",
                        event_state="historical",
                        title=f"{c.name} (Resolved)",
                        description=c.notes,
                        source_type="CONDITION",
                        source_id=c.id,
                    ),
                    c.created_at,
                )
            )

    # 2. Symptoms
    symptoms = await get_symptoms(db, patient_id)
    for s in symptoms:
        if s.recorded_at is not None:
            desc_parts: list[str] = []
            if s.severity:
                desc_parts.append(f"Severity: {s.severity}")
            if s.notes:
                desc_parts.append(s.notes)
            desc = " | ".join(desc_parts) if desc_parts else None

            raw_events.append(
                (
                    HealthEvent(
                        event_date=_format_source_date(s.recorded_at),
                        event_type="SYMPTOM_RECORDED",
                        event_state="neutral",
                        title=s.name,
                        description=desc,
                        source_type="SYMPTOM",
                        source_id=s.id,
                    ),
                    s.created_at,
                )
            )

    # 3. Medications
    medications = await get_medications(db, patient_id)
    for m in medications:
        is_active = m.status == "active"
        if m.started_at is not None:
            desc_parts = []
            if m.dosage:
                desc_parts.append(f"Dosage: {m.dosage}")
            if m.frequency:
                desc_parts.append(f"Frequency: {m.frequency}")
            if m.notes:
                desc_parts.append(m.notes)
            desc = " | ".join(desc_parts) if desc_parts else None

            raw_events.append(
                (
                    HealthEvent(
                        event_date=_format_source_date(m.started_at),
                        event_type="MEDICATION_STARTED",
                        event_state="current" if is_active else "historical",
                        title=m.name,
                        description=desc,
                        source_type="MEDICATION",
                        source_id=m.id,
                    ),
                    m.created_at,
                )
            )
        if m.ended_at is not None:
            raw_events.append(
                (
                    HealthEvent(
                        event_date=_format_source_date(m.ended_at),
                        event_type="MEDICATION_STOPPED",
                        event_state="historical",
                        title=f"{m.name} (Stopped)",
                        description=m.notes,
                        source_type="MEDICATION",
                        source_id=m.id,
                    ),
                    m.created_at,
                )
            )

    # 4. Documents
    documents = await get_documents(db, patient_id)
    for d in documents:
        display_name = d.display_name or d.file_name
        doc_desc = d.notes if d.notes else f"Type: {d.document_type}"
        if d.document_date is not None:
            raw_events.append(
                (
                    HealthEvent(
                        event_date=_format_source_date(d.document_date),
                        event_type="DOCUMENT_DATED",
                        event_state="neutral",
                        title=display_name,
                        description=doc_desc,
                        source_type="DOCUMENT",
                        source_id=d.id,
                    ),
                    d.created_at,
                )
            )
        elif d.uploaded_at is not None:
            raw_events.append(
                (
                    HealthEvent(
                        event_date=_format_source_date(d.uploaded_at),
                        event_type="DOCUMENT_UPLOADED",
                        event_state="neutral",
                        title=display_name,
                        description=doc_desc,
                        source_type="DOCUMENT",
                        source_id=d.id,
                    ),
                    d.created_at,
                )
            )

    # 5. Patient Goals
    goals = await get_goals(db, patient_id)
    for g in goals:
        if g.recorded_at is not None:
            is_active = g.status == "active"
            raw_events.append(
                (
                    HealthEvent(
                        event_date=_format_source_date(g.recorded_at),
                        event_type="GOAL_RECORDED",
                        event_state="current" if is_active else "historical",
                        title=g.description,
                        description=g.notes,
                        source_type="GOAL",
                        source_id=g.id,
                    ),
                    g.created_at,
                )
            )

    # Sort with deterministic tie-breaking
    raw_events.sort(key=functools.cmp_to_key(_timeline_sort_comparator))

    return [item[0] for item in raw_events]
