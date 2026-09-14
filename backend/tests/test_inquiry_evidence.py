import uuid
from datetime import date, datetime, timezone

from app.health.evidence_evaluator import evaluate_evidence
from app.health.inquiry_context import StructuredHealthContext
from app.health.query_understanding import parse_natural_language_query
from app.schemas.condition import ConditionResponse
from app.schemas.health_profile import HealthProfileResponse
from app.schemas.inquiry import EvidenceStatus, InquiryTarget
from app.schemas.medication import MedicationResponse
from app.schemas.provenance import VerificationState


def make_base_fields():
    return {
        "id": uuid.uuid4(),
        "patient_id": uuid.uuid4(),
        "recorded_at": datetime.now(timezone.utc),
        "source_type": "PATIENT_REPORTED",
        "verification_state": VerificationState.PATIENT_REPORTED,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "source_id": uuid.uuid4(),
    }


def create_context():
    return StructuredHealthContext(
        profile=HealthProfileResponse(
            patient_id=uuid.uuid4(),
            biological_sex="male",
            blood_group=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
        conditions=[
            ConditionResponse(**make_base_fields(), name="Asthma", status="active"),
            ConditionResponse(
                **make_base_fields(),
                name="Bronchitis",
                status="resolved",
                ended_at=date(2021, 1, 1),
            ),
        ],
        medications=[
            MedicationResponse(
                **make_base_fields(), name="Lisinopril", status="active", dosage="10mg"
            ),
            MedicationResponse(
                **make_base_fields(),
                name="Albuterol",
                status="stopped",
                ended_at=date(2023, 1, 1),
            ),
        ],
        allergies=[],
        symptoms=[],
        goals=[],
        recent_timeline_events=[],
    )


def test_1_exact_structured_record_lookup():
    context = create_context()
    target = InquiryTarget(target_domain="medications", requested_attributes=["dosage"])
    result = evaluate_evidence(target, context)
    assert result.status == EvidenceStatus.SUFFICIENT
    assert "dosage" in result.matched_fields


def test_2_entity_domain_matching():
    context = create_context()
    target = InquiryTarget(target_domain="conditions", target_entity="Asthma")
    result = evaluate_evidence(target, context)
    assert result.status == EvidenceStatus.SUFFICIENT
    assert len(result.matched_records) == 1
    assert result.matched_records[0].name == "Asthma"


def test_3_requested_attribute_present():
    context = create_context()
    target = InquiryTarget(
        target_domain="medications",
        target_entity="Lisinopril",
        requested_attributes=["dosage"],
    )
    result = evaluate_evidence(target, context)
    assert result.status == EvidenceStatus.SUFFICIENT
    assert result.matched_fields == ["dosage"]
    assert not result.missing_fields


def test_4_requested_attribute_null():
    context = create_context()
    # Profile has blood_group=None
    target = InquiryTarget(
        target_domain="profile", requested_attributes=["blood_group"]
    )
    result = evaluate_evidence(target, context)
    assert result.status == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert "blood_group" in result.missing_fields
    assert not result.matched_fields


def test_5_entity_absent():
    context = create_context()
    target = InquiryTarget(target_domain="medications", target_entity="Ibuprofen")
    result = evaluate_evidence(target, context)
    assert result.status == EvidenceStatus.INSUFFICIENT
    # Ensure it's not present
    assert not result.matched_records


def test_6_empty_domain():
    context = create_context()
    # Allergies is empty in context
    target = InquiryTarget(target_domain="allergies", target_entity="Peanut")
    result = evaluate_evidence(target, context)
    assert result.status == EvidenceStatus.INSUFFICIENT
    assert not result.matched_records


def test_7_current_temporal_scope():
    context = create_context()
    target = InquiryTarget(
        target_domain="medications", target_entity="Albuterol", temporal_scope="current"
    )
    result = evaluate_evidence(target, context)
    # Albuterol is stopped
    assert result.status == EvidenceStatus.INSUFFICIENT


def test_8_historical_temporal_scope():
    context = create_context()
    target = InquiryTarget(
        target_domain="medications",
        target_entity="Albuterol",
        temporal_scope="historical",
    )
    result = evaluate_evidence(target, context)
    # Albuterol is stopped (historical)
    assert result.status == EvidenceStatus.SUFFICIENT
    assert result.matched_records[0].name == "Albuterol"


def test_9_all_temporal_scope():
    context = create_context()
    target = InquiryTarget(
        target_domain="medications", target_entity="Albuterol", temporal_scope="all"
    )
    result = evaluate_evidence(target, context)
    assert result.status == EvidenceStatus.SUFFICIENT


def test_10_partial_evidence():
    context = create_context()
    target = InquiryTarget(
        target_domain="medications",
        target_entity="Lisinopril",
        requested_attributes=["dosage", "clinic"],
    )
    result = evaluate_evidence(target, context)
    assert result.status == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert "dosage" in result.matched_fields
    assert "clinic" in result.missing_fields


def test_10b_partial_evidence_all_attributes_missing():
    context = create_context()
    target = InquiryTarget(
        target_domain="medications",
        target_entity="Lisinopril",
        requested_attributes=["clinic"],
    )
    result = evaluate_evidence(target, context)
    assert result.status == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert not result.matched_fields
    assert "clinic" in result.missing_fields


def test_11_insufficient_evidence():
    context = create_context()
    # Context allergies empty
    target = InquiryTarget(target_domain="allergies")
    result = evaluate_evidence(target, context)
    assert result.status == EvidenceStatus.INSUFFICIENT


def test_12_negative_absence_wording_protection():
    context = create_context()
    # Target entity absent
    target = InquiryTarget(target_domain="allergies", target_entity="Peanut")
    result = evaluate_evidence(target, context)
    assert (
        "Peanut is not recorded" in result.evidence_directive
        or "allergies are not recorded" in result.evidence_directive
    )
    assert "does not have" not in result.evidence_directive.lower()

    # Attribute absent
    target2 = InquiryTarget(
        target_domain="profile", requested_attributes=["blood_group"]
    )
    result2 = evaluate_evidence(target2, context)
    assert "not recorded" in result2.evidence_directive.lower()
    assert "does not have" not in result2.evidence_directive.lower()


def test_13_patient_context_cannot_escape():
    # Only fields inside StructuredHealthContext can be accessed
    context = create_context()
    target = InquiryTarget(target_domain="billing_records")
    result = evaluate_evidence(target, context)
    assert result.status == EvidenceStatus.INSUFFICIENT
    assert "not recorded" in result.evidence_directive


def test_14_query_understanding_abstraction_mockable():
    query = "What is my Lisinopril dosage?"
    target = parse_natural_language_query(query)
    assert target.target_domain == "medications"
    assert target.target_entity == "Lisinopril"
    assert "dosage" in target.requested_attributes

    # Evaluate it
    context = create_context()
    result = evaluate_evidence(target, context)
    assert result.status == EvidenceStatus.SUFFICIENT
