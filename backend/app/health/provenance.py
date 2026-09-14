"""
Centralized provenance validation and derivation helper (M6).

All clinical service modules (conditions, symptoms, medications, allergies)
and goals.py MUST delegate to ``validate_and_resolve_provenance()`` rather
than re-implementing the logic individually.

Rules enforced:
  1. verification_state tampering — always rejected (handled at schema layer).
  2. Reserved source_type — always rejected (handled at schema layer).
  3. PATIENT_REPORTED + non-null source_id → HTTP 422.
  4. SOURCE_DOCUMENT + null source_id → HTTP 422.
  5. source_id existence and patient-ownership checks → HTTP 422.
  6. Atomic update rule: if neither source_type nor source_id appear in the
     update payload, skip all provenance validation and preserve existing values.
  7. If either provenance field appears in an update payload, resolve the
     effective pair (supplied fields + existing fallbacks) and validate the
     complete pair.
  8. verification_state is server-derived: PATIENT_REPORTED → PATIENT_REPORTED,
     SOURCE_DOCUMENT → SOURCE_RECORDED.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MedicalDocument
from app.schemas.provenance import HealthSourceType, VerificationState

# ── Public constants ───────────────────────────────────────────────────────────

_PROVENANCE_FIELDS = frozenset({"source_type", "source_id"})

# ── Derivation map ─────────────────────────────────────────────────────────────

_DERIVE_VERIFICATION: dict[str, str] = {
    HealthSourceType.PATIENT_REPORTED: VerificationState.PATIENT_REPORTED,
    HealthSourceType.SOURCE_DOCUMENT: VerificationState.SOURCE_RECORDED,
}


# ── Core helper ───────────────────────────────────────────────────────────────


async def validate_and_resolve_provenance(
    db: AsyncSession,
    patient_id: uuid.UUID,
    data: dict[str, Any],
    existing_source_type: str | None = None,
    existing_source_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Validate and resolve provenance for a create or update operation.

    Parameters
    ----------
    db:
        Async SQLAlchemy session.
    patient_id:
        UUID of the authenticated patient performing the operation.
    data:
        The ``model_dump(exclude_unset=True)`` dict from the Pydantic schema.
        Must NOT contain ``verification_state`` (rejected at the schema layer).
        May contain ``source_type`` and/or ``source_id``.
    existing_source_type:
        The current ``source_type`` value on the record being updated.
        ``None`` for create operations.
    existing_source_id:
        The current ``source_id`` value on the record being updated.
        ``None`` for create operations.

    Returns
    -------
    dict
        A copy of *data* with ``source_type``, ``source_id``, and
        ``verification_state`` resolved to their final, server-authoritative
        values. Pass the returned dict directly to the ORM constructor or
        ``setattr`` loop.

    Raises
    ------
    HTTPException 422
        On any provenance violation.
    """
    data = dict(data)  # work on a copy

    is_create = existing_source_type is None
    has_source_type = "source_type" in data
    has_source_id = "source_id" in data

    # ── Atomic update bypass ───────────────────────────────────────────────────
    # For updates: if NEITHER provenance field is present in the payload,
    # skip all provenance validation entirely and preserve existing values.
    if not is_create and not has_source_type and not has_source_id:
        # Neither field supplied — no provenance mutation; preserve existing.
        return data

    # ── Resolve effective pair ─────────────────────────────────────────────────
    if is_create:
        effective_source_type = (
            data.get("source_type") or HealthSourceType.PATIENT_REPORTED
        )
        effective_source_id = data.get("source_id")  # may be None
    else:
        # Update with at least one provenance field supplied.
        effective_source_type = data.get("source_type", existing_source_type)
        effective_source_id = data.get("source_id", existing_source_id)

    # ── Pair consistency checks ────────────────────────────────────────────────
    if effective_source_type == HealthSourceType.PATIENT_REPORTED:
        if effective_source_id is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=("source_id must be null when source_type is PATIENT_REPORTED."),
            )
    elif effective_source_type == HealthSourceType.SOURCE_DOCUMENT:
        if effective_source_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=("source_id is required when source_type is SOURCE_DOCUMENT."),
            )
    else:
        # Unknown or unsupported source_type value (schema should have caught
        # reserved types, but guard against arbitrary strings here too).
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported source_type value: '{effective_source_type}'.",
        )

    # ── Source document existence + patient-ownership check ───────────────────
    if effective_source_id is not None:
        stmt = select(MedicalDocument).where(MedicalDocument.id == effective_source_id)
        result = await db.execute(stmt)
        doc = result.scalar_one_or_none()
        if doc is None or doc.patient_id != patient_id:
            # Non-existent OR cross-patient — both deterministically 422.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "source_id does not reference a valid document "
                    "owned by this patient."
                ),
            )

    # ── Derive verification_state ──────────────────────────────────────────────
    derived_verification_state = _DERIVE_VERIFICATION[effective_source_type]

    # ── Write resolved provenance back into the data dict ─────────────────────
    data["source_type"] = effective_source_type
    data["source_id"] = effective_source_id
    data["verification_state"] = derived_verification_state

    return data
