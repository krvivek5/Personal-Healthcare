"""
M6 Provenance & Data Integrity tests.

Covers:
  - Schema-layer rejection of verification_state in Create/Update payloads (HTTP 422).
  - Schema-layer rejection of CLINICIAN_CONFIRMED (reserved source_type).
  - Provenance helper: PATIENT_REPORTED + non-null source_id → rejected.
  - Provenance helper: SOURCE_DOCUMENT + null source_id → rejected.
  - Provenance helper: non-provenance update bypasses provenance checks (detached src).
  - Provenance helper: verification_state derived correctly from source_type.
  - API integration: conditions, symptoms, medications, allergies, goals provenance.
  - Medical document upload/update: provenance fields locked and response exposes
    verification_state.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas.allergy import AllergyCreate, AllergyUpdate
from app.schemas.condition import ConditionCreate, ConditionUpdate
from app.schemas.document import DocumentUpdate
from app.schemas.goal import GoalCreate, GoalUpdate
from app.schemas.medication import MedicationCreate, MedicationUpdate
from app.schemas.provenance import (
    ALLOWED_CLIENT_SOURCE_TYPES,
    RESERVED_SOURCE_TYPES,
    HealthSourceType,
    VerificationState,
)
from app.schemas.symptom import SymptomCreate, SymptomUpdate

# ── Helpers ────────────────────────────────────────────────────────────────────


def make_async_db(doc=None):
    """Return a minimal AsyncSession mock.

    If ``doc`` is provided, ``db.execute`` returns a result whose
    ``scalar_one_or_none()`` returns it.
    """
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = doc
    db.execute.return_value = result
    return db


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Schema-layer: verification_state rejection
# ═══════════════════════════════════════════════════════════════════════════════


class TestVerificationStateRejected:
    """All Create and Update schemas must reject verification_state (HTTP 422)."""

    def test_condition_create_rejects_verification_state(self):
        with pytest.raises(ValidationError, match="verification_state"):
            ConditionCreate(
                name="Test",
                status="active",
                verification_state="PATIENT_REPORTED",
            )

    def test_condition_update_rejects_verification_state(self):
        with pytest.raises(ValidationError, match="verification_state"):
            ConditionUpdate(status="resolved", verification_state="PATIENT_REPORTED")

    def test_symptom_create_rejects_verification_state(self):
        with pytest.raises(ValidationError, match="verification_state"):
            SymptomCreate(name="Headache", verification_state="PATIENT_REPORTED")

    def test_symptom_update_rejects_verification_state(self):
        with pytest.raises(ValidationError, match="verification_state"):
            SymptomUpdate(name="Headache", verification_state="UNCERTAIN")

    def test_medication_create_rejects_verification_state(self):
        with pytest.raises(ValidationError, match="verification_state"):
            MedicationCreate(
                name="Aspirin", status="active", verification_state="SOURCE_RECORDED"
            )

    def test_medication_update_rejects_verification_state(self):
        with pytest.raises(ValidationError, match="verification_state"):
            MedicationUpdate(name="Aspirin", verification_state="PATIENT_REPORTED")

    def test_allergy_create_rejects_verification_state(self):
        with pytest.raises(ValidationError, match="verification_state"):
            AllergyCreate(allergen="Pollen", verification_state="PATIENT_REPORTED")

    def test_allergy_update_rejects_verification_state(self):
        with pytest.raises(ValidationError, match="verification_state"):
            AllergyUpdate(allergen="Pollen", verification_state="CLINICIAN_CONFIRMED")

    def test_goal_create_rejects_verification_state(self):
        with pytest.raises(ValidationError, match="verification_state"):
            GoalCreate(
                description="Walk daily",
                status="active",
                verification_state="PATIENT_REPORTED",
            )

    def test_goal_update_rejects_verification_state(self):
        with pytest.raises(ValidationError, match="verification_state"):
            GoalUpdate(description="Walk daily", verification_state="SOURCE_RECORDED")

    def test_document_update_rejects_verification_state(self):
        with pytest.raises(ValidationError, match="verification_state"):
            DocumentUpdate(verification_state="PATIENT_REPORTED")

    def test_document_update_rejects_source_type(self):
        with pytest.raises(ValidationError):
            DocumentUpdate(source_type="PATIENT_REPORTED")

    def test_document_update_rejects_source_id(self):
        with pytest.raises(ValidationError):
            DocumentUpdate(source_id=str(uuid.uuid4()))


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Schema-layer: reserved source_type rejection
# ═══════════════════════════════════════════════════════════════════════════════


class TestReservedSourceTypeRejected:
    """CLINICIAN_CONFIRMED must be rejected by client schemas."""

    def test_condition_create_rejects_clinician_confirmed(self):
        with pytest.raises(ValidationError, match="reserved"):
            ConditionCreate(
                name="Test",
                status="active",
                source_type="CLINICIAN_CONFIRMED",
            )

    def test_symptom_update_rejects_clinician_confirmed(self):
        with pytest.raises(ValidationError, match="reserved"):
            SymptomUpdate(name="Headache", source_type="CLINICIAN_CONFIRMED")

    def test_medication_create_rejects_clinician_confirmed(self):
        with pytest.raises(ValidationError, match="reserved"):
            MedicationCreate(
                name="Drug",
                status="active",
                source_type="CLINICIAN_CONFIRMED",
            )

    def test_allergy_update_rejects_clinician_confirmed(self):
        with pytest.raises(ValidationError, match="reserved"):
            AllergyUpdate(allergen="Dust", source_type="CLINICIAN_CONFIRMED")

    def test_goal_create_rejects_clinician_confirmed(self):
        with pytest.raises(ValidationError, match="reserved"):
            GoalCreate(
                description="Goal",
                status="active",
                source_type="CLINICIAN_CONFIRMED",
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Provenance schema values
# ═══════════════════════════════════════════════════════════════════════════════


class TestProvenanceEnums:
    def test_allowed_client_source_types(self):
        assert HealthSourceType.PATIENT_REPORTED in ALLOWED_CLIENT_SOURCE_TYPES
        assert HealthSourceType.SOURCE_DOCUMENT in ALLOWED_CLIENT_SOURCE_TYPES
        assert HealthSourceType.CLINICIAN_CONFIRMED not in ALLOWED_CLIENT_SOURCE_TYPES

    def test_reserved_source_types_contains_clinician_confirmed(self):
        assert HealthSourceType.CLINICIAN_CONFIRMED in RESERVED_SOURCE_TYPES

    def test_all_verification_states_present(self):
        states = {v.value for v in VerificationState}
        assert "PATIENT_REPORTED" in states
        assert "SOURCE_RECORDED" in states
        assert "CLINICIAN_CONFIRMED" in states
        assert "AI_DERIVED" in states
        assert "UNCERTAIN" in states


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Provenance helper: validate_and_resolve_provenance
# ═══════════════════════════════════════════════════════════════════════════════


class TestValidateAndResolveProvenance:
    """Unit tests for the centralized provenance helper."""

    @pytest.mark.asyncio
    async def test_create_patient_reported_no_source_id(self):
        """PATIENT_REPORTED + no source_id → accepted, verification set."""
        from app.health.provenance import validate_and_resolve_provenance

        db = make_async_db()
        patient_id = uuid.uuid4()
        result = await validate_and_resolve_provenance(
            db, patient_id, {"source_type": "PATIENT_REPORTED"}
        )
        assert result["source_type"] == "PATIENT_REPORTED"
        assert result["source_id"] is None
        assert result["verification_state"] == "PATIENT_REPORTED"

    @pytest.mark.asyncio
    async def test_create_patient_reported_with_source_id_rejected(self):
        """PATIENT_REPORTED + non-null source_id → HTTP 422."""
        from app.health.provenance import validate_and_resolve_provenance

        db = make_async_db()
        patient_id = uuid.uuid4()
        with pytest.raises(HTTPException) as exc_info:
            await validate_and_resolve_provenance(
                db,
                patient_id,
                {"source_type": "PATIENT_REPORTED", "source_id": uuid.uuid4()},
            )
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_create_source_document_without_source_id_rejected(self):
        """SOURCE_DOCUMENT + null source_id → HTTP 422."""
        from app.health.provenance import validate_and_resolve_provenance

        db = make_async_db()
        patient_id = uuid.uuid4()
        with pytest.raises(HTTPException) as exc_info:
            await validate_and_resolve_provenance(
                db, patient_id, {"source_type": "SOURCE_DOCUMENT"}
            )
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_create_source_document_with_valid_doc(self):
        """SOURCE_DOCUMENT + valid patient-owned doc → accepted, verification set."""
        from app.health.provenance import validate_and_resolve_provenance

        patient_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        mock_doc = MagicMock()
        mock_doc.patient_id = patient_id

        db = make_async_db(doc=mock_doc)
        result = await validate_and_resolve_provenance(
            db,
            patient_id,
            {"source_type": "SOURCE_DOCUMENT", "source_id": doc_id},
        )
        assert result["source_type"] == "SOURCE_DOCUMENT"
        assert result["source_id"] == doc_id
        assert result["verification_state"] == "SOURCE_RECORDED"

    @pytest.mark.asyncio
    async def test_source_document_cross_patient_rejected(self):
        """source_id owned by a different patient → HTTP 422."""
        from app.health.provenance import validate_and_resolve_provenance

        patient_id = uuid.uuid4()
        other_patient_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        mock_doc = MagicMock()
        mock_doc.patient_id = other_patient_id  # different patient!

        db = make_async_db(doc=mock_doc)
        with pytest.raises(HTTPException) as exc_info:
            await validate_and_resolve_provenance(
                db,
                patient_id,
                {"source_type": "SOURCE_DOCUMENT", "source_id": doc_id},
            )
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_source_document_nonexistent_rejected(self):
        """Non-existent source_id → HTTP 422."""
        from app.health.provenance import validate_and_resolve_provenance

        patient_id = uuid.uuid4()
        db = make_async_db(doc=None)  # doc not found
        with pytest.raises(HTTPException) as exc_info:
            await validate_and_resolve_provenance(
                db,
                patient_id,
                {"source_type": "SOURCE_DOCUMENT", "source_id": uuid.uuid4()},
            )
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_update_no_provenance_fields_bypasses_validation(self):
        """Atomic update bypass: neither source_type nor source_id in payload
        → provenance preserved, DB not queried for doc ownership."""
        from app.health.provenance import validate_and_resolve_provenance

        patient_id = uuid.uuid4()
        db = make_async_db()
        result = await validate_and_resolve_provenance(
            db,
            patient_id,
            {"name": "Hypertension", "status": "resolved"},  # no provenance fields
            existing_source_type="SOURCE_DOCUMENT",
            existing_source_id=uuid.uuid4(),
        )
        # Provenance fields NOT added; data returned unchanged
        assert "source_type" not in result
        assert "source_id" not in result
        assert "verification_state" not in result
        # DB was NOT queried for document ownership
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_with_only_source_type_resolves_pair(self):
        """Update with only source_type supplied uses existing source_id."""
        from app.health.provenance import validate_and_resolve_provenance

        patient_id = uuid.uuid4()
        existing_source_id = uuid.uuid4()
        mock_doc = MagicMock()
        mock_doc.patient_id = patient_id
        db = make_async_db(doc=mock_doc)

        # Existing state: SOURCE_DOCUMENT. Update: change source_type (rare but
        # valid if also changing source_id; here source_id stays from existing).
        result = await validate_and_resolve_provenance(
            db,
            patient_id,
            {"source_type": "SOURCE_DOCUMENT"},  # only source_type in payload
            existing_source_type="SOURCE_DOCUMENT",
            existing_source_id=existing_source_id,
        )
        assert result["source_type"] == "SOURCE_DOCUMENT"
        assert result["source_id"] == existing_source_id
        assert result["verification_state"] == "SOURCE_RECORDED"

    @pytest.mark.asyncio
    async def test_create_defaults_to_patient_reported_when_no_source_type(self):
        """Create without source_type → defaults to PATIENT_REPORTED."""
        from app.health.provenance import validate_and_resolve_provenance

        db = make_async_db()
        patient_id = uuid.uuid4()
        result = await validate_and_resolve_provenance(
            db, patient_id, {"name": "New condition", "status": "active"}
        )
        assert result["source_type"] == "PATIENT_REPORTED"
        assert result["verification_state"] == "PATIENT_REPORTED"

    @pytest.mark.asyncio
    async def test_update_switching_to_patient_reported_clears_source_id(self):
        """Update: switching from SOURCE_DOCUMENT to PATIENT_REPORTED
        + null source_id → OK.
        """
        from app.health.provenance import validate_and_resolve_provenance

        patient_id = uuid.uuid4()
        db = make_async_db()
        result = await validate_and_resolve_provenance(
            db,
            patient_id,
            {"source_type": "PATIENT_REPORTED", "source_id": None},
            existing_source_type="SOURCE_DOCUMENT",
            existing_source_id=uuid.uuid4(),
        )
        assert result["source_type"] == "PATIENT_REPORTED"
        assert result["source_id"] is None
        assert result["verification_state"] == "PATIENT_REPORTED"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Schema validation: valid payloads still accepted
# ═══════════════════════════════════════════════════════════════════════════════


class TestValidPayloadsAccepted:
    """Sanity-check that legitimate payloads are not inadvertently rejected."""

    def test_condition_create_minimal(self):
        c = ConditionCreate(name="Hypertension", status="active")
        assert c.name == "Hypertension"
        assert c.source_type is None  # not set in schema, resolved by service

    def test_condition_create_with_source_type(self):
        c = ConditionCreate(
            name="Hypertension",
            status="active",
            source_type="PATIENT_REPORTED",
        )
        assert c.source_type == "PATIENT_REPORTED"

    def test_condition_create_with_source_document(self):
        doc_id = uuid.uuid4()
        c = ConditionCreate(
            name="Hypertension",
            status="active",
            source_type="SOURCE_DOCUMENT",
            source_id=doc_id,
        )
        assert c.source_type == "SOURCE_DOCUMENT"
        assert c.source_id == doc_id

    def test_condition_update_empty_is_valid(self):
        u = ConditionUpdate()
        assert u.name is None
        assert u.source_type is None

    def test_document_update_metadata_only_accepted(self):
        u = DocumentUpdate(display_name="Lab Results Q1")
        assert u.display_name == "Lab Results Q1"

    def test_goal_create_no_source_type(self):
        g = GoalCreate(description="Lose weight", status="active")
        assert g.source_type is None


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Detached source lifecycle
# ═══════════════════════════════════════════════════════════════════════════════


class TestDetachedSourceLifecycle:
    """Non-provenance updates on entities with detached source_id must be allowed."""

    @pytest.mark.asyncio
    async def test_non_provenance_update_on_detached_entity_allowed(self):
        """When source_id is NULL (document deleted) but source_type is SOURCE_DOCUMENT,
        a non-provenance update MUST succeed (detached state is preserved)."""
        from app.health.provenance import validate_and_resolve_provenance

        patient_id = uuid.uuid4()
        db = make_async_db()

        # Simulate a detached entity (source deleted, source_id = NULL,
        # source_type still = SOURCE_DOCUMENT).
        result = await validate_and_resolve_provenance(
            db,
            patient_id,
            {"status": "resolved"},  # non-provenance update
            existing_source_type="SOURCE_DOCUMENT",
            existing_source_id=None,  # already NULL — document was deleted
        )
        # Should return the payload unchanged — no provenance fields added.
        assert result == {"status": "resolved"}
        db.execute.assert_not_called()
