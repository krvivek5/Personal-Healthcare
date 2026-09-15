import json
import random
import uuid
from datetime import date, datetime, timezone

import pytest

from app.health.inquiry_context import StructuredHealthContext
from app.health.sanitized_context import (
    UUID_REGEX,
    build_sanitized_context,
    reconcile_reference_tokens,
)
from app.schemas.allergy import AllergyResponse
from app.schemas.condition import ConditionResponse
from app.schemas.goal import GoalResponse
from app.schemas.health_profile import HealthProfileResponse
from app.schemas.medication import MedicationResponse
from app.schemas.symptom import SymptomResponse
from app.schemas.timeline import HealthEvent


@pytest.fixture
def rich_patient_context() -> tuple[StructuredHealthContext, dict[str, uuid.UUID]]:
    patient_id = uuid.uuid4()
    profile_id = uuid.uuid4()
    cond_id_1 = uuid.uuid4()
    cond_id_2 = uuid.uuid4()
    med_id_1 = uuid.uuid4()
    med_id_2 = uuid.uuid4()
    allergy_id = uuid.uuid4()
    symptom_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    timeline_source_id = uuid.uuid4()

    ids = {
        "patient_id": patient_id,
        "profile_id": profile_id,
        "cond_1": cond_id_1,
        "cond_2": cond_id_2,
        "med_1": med_id_1,
        "med_2": med_id_2,
        "allergy": allergy_id,
        "symptom": symptom_id,
        "goal": goal_id,
        "timeline_source": timeline_source_id,
    }

    now = datetime.now(timezone.utc)

    profile = HealthProfileResponse(
        id=profile_id,
        patient_id=patient_id,
        biological_sex="female",
        date_of_birth=date(1990, 5, 20),
        blood_group="A+",
        height_cm=165.5,
        notes="Non-smoker",
        created_at=now,
        updated_at=now,
    )

    conditions = [
        ConditionResponse(
            id=cond_id_1,
            patient_id=patient_id,
            name="Asthma",
            status="active",
            is_chronic=True,
            started_at=date(2020, 1, 15),
            ended_at=None,
            notes="Exercise induced",
            source_type="PATIENT_REPORTED",
            source_id=None,
            verification_state="UNVERIFIED",
            recorded_at=now,
            created_at=now,
            updated_at=now,
        ),
        ConditionResponse(
            id=cond_id_2,
            patient_id=patient_id,
            name="Seasonal Bronchitis",
            status="resolved",
            is_chronic=False,
            started_at=date(2022, 11, 1),
            ended_at=date(2022, 11, 20),
            notes="Treated with rest",
            source_type="SOURCE_RECORDED",
            source_id=uuid.uuid4(),
            verification_state="VERIFIED",
            recorded_at=now,
            created_at=now,
            updated_at=now,
        ),
    ]

    medications = [
        MedicationResponse(
            id=med_id_1,
            patient_id=patient_id,
            name="Albuterol",
            dosage="90mcg",
            frequency="As needed",
            status="active",
            as_needed=True,
            started_at=date(2020, 1, 15),
            ended_at=None,
            notes="Inhaler before workout",
            source_type="SOURCE_RECORDED",
            source_id=uuid.uuid4(),
            verification_state="VERIFIED",
            recorded_at=now,
            created_at=now,
            updated_at=now,
        ),
        MedicationResponse(
            id=med_id_2,
            patient_id=patient_id,
            name="Amoxicillin",
            dosage=None,  # Intentionally null to test null preservation
            frequency="Twice daily",
            status="stopped",
            as_needed=False,
            started_at=date(2022, 11, 1),
            ended_at=date(2022, 11, 10),
            notes=None,
            source_type="PATIENT_REPORTED",
            source_id=None,
            verification_state="UNVERIFIED",
            recorded_at=now,
            created_at=now,
            updated_at=now,
        ),
    ]

    allergies = [
        AllergyResponse(
            id=allergy_id,
            patient_id=patient_id,
            allergen="Penicillin",
            reaction="Hives and facial swelling",
            severity="severe",
            notes="Childhood reaction",
            source_type="PATIENT_REPORTED",
            source_id=None,
            verification_state="UNVERIFIED",
            recorded_at=now,
            created_at=now,
            updated_at=now,
        )
    ]

    symptoms = [
        SymptomResponse(
            id=symptom_id,
            patient_id=patient_id,
            name="Wheezing",
            severity="moderate",
            started_at=date(2024, 2, 1),
            ended_at=None,
            notes="Triggered by cold air",
            source_type="PATIENT_REPORTED",
            source_id=None,
            verification_state="UNVERIFIED",
            recorded_at=now,
            created_at=now,
            updated_at=now,
        )
    ]

    goals = [
        GoalResponse(
            id=goal_id,
            patient_id=patient_id,
            title="Complete 5k run",
            description="Complete 5k run without wheezing",
            status="active",
            target_date=date(2025, 6, 1),
            notes="Use inhaler prior to start",
            source_type="PATIENT_REPORTED",
            source_id=None,
            verification_state="UNVERIFIED",
            recorded_at=now,
            created_at=now,
            updated_at=now,
        )
    ]

    timeline_events = [
        HealthEvent(
            event_type="MEDICATION_STARTED",
            event_date="2020-01-15",
            event_state="current",
            title="Albuterol Inhaler",
            description="Started Albuterol 90mcg",
            source_type="MEDICATION",
            source_id=timeline_source_id,
        )
    ]

    context = StructuredHealthContext(
        profile=profile,
        conditions=conditions,
        medications=medications,
        allergies=allergies,
        symptoms=symptoms,
        goals=goals,
        recent_timeline_events=timeline_events,
    )

    return context, ids


def test_no_database_uuids_in_serialized_payload(rich_patient_context):
    """
    Must guarantee that NO database UUIDs (patient_id, record IDs, source_ids)
    appear in the serialized LLM payload or prompt text.
    """
    context, ids = rich_patient_context
    sanitized = build_sanitized_context(context)

    payload = sanitized.to_llm_payload()
    payload_json = json.dumps(payload)
    prompt_text = sanitized.to_prompt_text()

    # 1. No regex UUID pattern matches in payload JSON or prompt text
    uuid_matches_payload = UUID_REGEX.findall(payload_json)
    assert not uuid_matches_payload, f"UUIDs leaked in payload: {uuid_matches_payload}"

    uuid_matches_prompt = UUID_REGEX.findall(prompt_text)
    assert not uuid_matches_prompt, f"UUIDs leaked in prompt: {uuid_matches_prompt}"

    # 2. None of the actual database UUIDs are substrings
    for id_name, id_val in ids.items():
        assert str(id_val) not in payload_json, f"{id_name} leaked in payload JSON!"
        assert str(id_val) not in prompt_text, f"{id_name} leaked in prompt text!"


def test_no_patient_user_identifiers_or_audit_timestamps(rich_patient_context):
    """
    Payload must strictly omit database and tenant metadata keys:
    patient_id, user_id, source_id, created_at, updated_at, storage_key.
    """
    context, _ = rich_patient_context
    sanitized = build_sanitized_context(context)

    payload_json = json.dumps(sanitized.to_llm_payload())

    forbidden_keys = [
        "patient_id",
        "user_id",
        "source_id",
        "storage_key",
        "upload_id",
        "created_at",
        "updated_at",
    ]

    for key in forbidden_keys:
        assert f'"{key}"' not in payload_json, (
            f"Forbidden key '{key}' found in payload!"
        )


def test_exact_dob_never_appears(rich_patient_context):
    """
    Exact date_of_birth must never appear in the LLM payload or prompt text.
    Age should be represented as a derived age_years integer.
    """
    context, _ = rich_patient_context
    sanitized = build_sanitized_context(context)

    payload_json = json.dumps(sanitized.to_llm_payload())
    prompt_text = sanitized.to_prompt_text()

    dob_str = context.profile.date_of_birth.isoformat()

    assert dob_str not in payload_json, "Exact DOB leaked in payload JSON!"
    assert dob_str not in prompt_text, "Exact DOB leaked in prompt text!"
    assert "age_years" in payload_json, "Derived age_years missing in payload JSON!"
    assert "age_years:" in prompt_text, "Derived age_years missing in prompt text!"


def test_query_scoped_minimization_single_domain(rich_patient_context):
    """
    When query target specifies a single domain (e.g. 'medications'),
    unrelated sensitive records (conditions, symptoms, allergies, goals)
    must be excluded.
    """
    from app.schemas.inquiry import InquiryTarget

    context, _ = rich_patient_context
    target = InquiryTarget(
        target_domain="medications",
        requested_attributes=["name", "dosage"],
    )

    sanitized = build_sanitized_context(context, target=target)

    # 1. Included domains are limited to profile and medications
    assert set(sanitized.included_domains) == {"profile", "medications"}

    # 2. Records contain only medications (and profile if present)
    entity_types = {r.entity_type for r in sanitized.records}
    assert entity_types.issubset({"profile", "medication"})
    assert "condition" not in entity_types
    assert "symptom" not in entity_types
    assert "allergy" not in entity_types
    assert "goal" not in entity_types
    assert "timeline" not in entity_types

    # 3. Content verification: asthma, wheezing, penicillin are NOT in the payload
    payload_str = json.dumps(sanitized.to_llm_payload()).lower()
    assert "asthma" not in payload_str
    assert "wheezing" not in payload_str
    assert "penicillin" not in payload_str
    assert "albuterol" in payload_str

    # 4. Profile exposure minimization verification:
    # Broader profile context (height, blood_group) should be omitted
    # for a medication query.
    assert "height_cm" not in payload_str
    assert "blood_group" not in payload_str
    # The string 'notes' exists in medications ('notes': 'inhaler before workout'),
    # but not as a top level profile attribute.
    # We don't check 'notes' absence globally here.
    assert "biological_sex" in payload_str
    assert "age_years" in payload_str


def test_query_scoped_minimization_unconstrained_target(rich_patient_context):
    """
    When target has no domain restriction, all populated domains are included.
    Broader profile context must be preserved for holistic inquiries.
    """
    from app.schemas.inquiry import InquiryTarget

    context, _ = rich_patient_context

    for target in [None, InquiryTarget(), InquiryTarget(target_domain=None)]:
        sanitized = build_sanitized_context(context, target=target)
        entity_types = {r.entity_type for r in sanitized.records}
        assert "condition" in entity_types
        assert "medication" in entity_types
        assert "allergy" in entity_types
        assert "symptom" in entity_types
        assert "goal" in entity_types
        assert "timeline" in entity_types

        # Profile context verification: broader fields should be present
        payload_str = json.dumps(sanitized.to_llm_payload()).lower()
        assert "height_cm" in payload_str
        assert "blood_group" in payload_str
        assert "biological_sex" in payload_str
        assert "age_years" in payload_str


def test_deterministic_reference_token_assignment(rich_patient_context):
    """
    Reference token assignment must be strictly deterministic across repeated runs,
    even if the in-memory list ordering of records is shuffled.
    """
    context, _ = rich_patient_context

    sanitized_1 = build_sanitized_context(context)
    tokens_1 = [r.token for r in sanitized_1.records]
    ref_map_1 = sanitized_1.reference_map.copy()

    # Shuffle the in-memory condition and medication lists
    shuffled_conditions = list(context.conditions)
    random.shuffle(shuffled_conditions)
    shuffled_medications = list(context.medications)
    random.shuffle(shuffled_medications)

    shuffled_context = StructuredHealthContext(
        profile=context.profile,
        conditions=shuffled_conditions,
        medications=shuffled_medications,
        allergies=context.allergies,
        symptoms=context.symptoms,
        goals=context.goals,
        recent_timeline_events=context.recent_timeline_events,
    )

    sanitized_2 = build_sanitized_context(shuffled_context)
    tokens_2 = [r.token for r in sanitized_2.records]
    ref_map_2 = sanitized_2.reference_map.copy()

    # Token sequences and UUID mappings must match identically
    assert tokens_1 == tokens_2
    assert ref_map_1 == ref_map_2


def test_reference_token_reconciliation_exact_and_bracketed(rich_patient_context):
    """
    Reconciliation must resolve both '[REC-N]' and 'REC-N' strings back to
    authoritative database UUIDs.
    """
    context, ids = rich_patient_context
    sanitized = build_sanitized_context(context)

    # 1. Bracketed tokens
    resolved_bracketed = reconcile_reference_tokens(
        ["[REC-1]", "[REC-2]"], sanitized.reference_map
    )
    assert len(resolved_bracketed) == 2
    assert all(isinstance(uid, uuid.UUID) for uid in resolved_bracketed)

    # 2. Unbracketed tokens
    resolved_unbracketed = reconcile_reference_tokens(
        ["REC-1", "REC-2"], sanitized.reference_map
    )
    assert resolved_bracketed == resolved_unbracketed

    # 3. Whitespace normalization
    resolved_whitespace = reconcile_reference_tokens(
        ["  [REC-1]  ", " REC-2 \n"], sanitized.reference_map
    )
    assert resolved_whitespace == resolved_bracketed


def test_reference_token_reconciliation_drops_foreign_or_hallucinated_tokens(
    rich_patient_context,
):
    """
    Hallucinated, malformed, or cross-tenant tokens must be discarded safely.
    """
    context, _ = rich_patient_context
    sanitized = build_sanitized_context(context)

    # Hallucinated tokens not in reference_map
    hallucinated = ["REC-999", "[REC-999]", "UNKNOWN", "", "   ", "[REC-0]"]
    resolved = reconcile_reference_tokens(hallucinated, sanitized.reference_map)
    assert resolved == []

    # Mixed valid and invalid tokens
    mixed = ["REC-1", "REC-999", "[REC-2]", "INVALID"]
    resolved_mixed = reconcile_reference_tokens(mixed, sanitized.reference_map)
    assert len(resolved_mixed) == 2
    assert resolved_mixed[0] == sanitized.reference_map["REC-1"]
    assert resolved_mixed[1] == sanitized.reference_map["REC-2"]


def test_reference_token_reconciliation_tenant_boundary_enforcement(
    rich_patient_context,
):
    """
    If valid_patient_record_ids is supplied, any token that resolves to a foreign
    UUID outside the patient's record set must be strictly dropped.
    """
    context, _ = rich_patient_context
    sanitized = build_sanitized_context(context)

    foreign_id = uuid.uuid4()
    # Inject a foreign mapping into the map to simulate a corrupted state
    compromised_map = sanitized.reference_map.copy()
    compromised_map["REC-MALICIOUS"] = foreign_id
    compromised_map["[REC-MALICIOUS]"] = foreign_id

    # Valid set containing only genuine patient IDs
    patient_valid_ids = set(sanitized.reference_map.values())

    resolved = reconcile_reference_tokens(
        ["REC-1", "REC-MALICIOUS"],
        compromised_map,
        valid_patient_record_ids=patient_valid_ids,
    )

    assert len(resolved) == 1
    assert foreign_id not in resolved
    assert resolved[0] == sanitized.reference_map["REC-1"]


def test_missing_null_values_preserve_m1_evidence_semantics(rich_patient_context):
    """
    Attributes with None/null values (e.g. unrecorded dosage) must remain explicitly
    null rather than omitted or guessed, preserving M1 evidence evaluation truth.
    """
    context, ids = rich_patient_context
    sanitized = build_sanitized_context(context)

    # Find the Amoxicillin record (where dosage was set to None)
    amox_record = next(
        r
        for r in sanitized.records
        if r.entity_type == "medication" and r.attributes.get("name") == "Amoxicillin"
    )

    assert "dosage" in amox_record.attributes
    assert amox_record.attributes["dosage"] is None

    # Prompt text explicitly represents unrecorded attribute
    prompt_text = sanitized.to_prompt_text()
    assert "dosage: not recorded" in prompt_text


def test_empty_structured_context_safe():
    """
    Empty context must serialize cleanly to empty records without errors.
    """
    empty_context = StructuredHealthContext()
    sanitized = build_sanitized_context(empty_context)

    assert sanitized.profile is None
    assert sanitized.records == []
    assert sanitized.reference_map == {}

    payload = sanitized.to_llm_payload()
    assert payload["records"] == []
    assert "profile" not in payload

    prompt_text = sanitized.to_prompt_text()
    assert prompt_text == ""


def test_to_prompt_text_formatting(rich_patient_context):
    """
    Prompt text output must format records cleanly with [REC-N] and entity tags.
    """
    context, _ = rich_patient_context
    sanitized = build_sanitized_context(context)

    prompt = sanitized.to_prompt_text()
    assert "Patient Profile:" in prompt
    assert "biological_sex: female" in prompt
    assert "Patient Health Records:" in prompt
    assert "[CONDITION]" in prompt
    assert "[MEDICATION]" in prompt
    assert "[ALLERGY]" in prompt
    assert "[REC-1]" in prompt
