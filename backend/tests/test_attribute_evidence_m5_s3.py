"""Unit tests for M5-S3 attribute evidence contextual qualification.

Tests the deterministic clinical evidence lexicon for the 8 canonical attributes.
"""

import uuid

from app.health.evidence_evaluator import evaluate_passage_evidence
from app.health.retrieval import RetrievalResult, RetrievedPassage
from app.schemas.inquiry import EvidenceStatus, InquiryTarget

PATIENT_A: uuid.UUID = uuid.uuid4()
_DOC_A: uuid.UUID = uuid.uuid4()


def _passage(chunk_text: str, document_id: uuid.UUID = _DOC_A) -> RetrievedPassage:
    """Build a minimal RetrievedPassage for testing."""
    return RetrievedPassage(
        chunk_id=uuid.uuid4(),
        document_id=document_id,
        patient_id=PATIENT_A,
        chunk_index=0,
        page_number=1,
        chunk_text=chunk_text,
        document_display_name="Test Document",
        document_type="lab_report",
        document_date=None,
        cosine_distance=0.1,
        similarity=0.9,
    )


def _result(passages: list[RetrievedPassage]) -> RetrievalResult:
    return RetrievalResult(
        patient_id=PATIENT_A,
        target_domains=("clinical_documents",),
        query_text="test query",
        top_k=5,
        passages=tuple(passages),
    )


def _target(attributes: list[str]) -> InquiryTarget:
    return InquiryTarget(
        target_domain="clinical_documents",
        target_entity=None,
        requested_attributes=attributes,
    )


# --- physician_name ---
def test_physician_name_valid():
    texts = [
        "Dr. John Doe recommended...",
        "Doctor Smith is the attending.",
        "physician: Sarah Jenkins",
        "prescriber: J. Doe MD",
        "ordered by: Dr. Alice",
        "Signed by: Robert Paulson, DO",
    ]
    for text in texts:
        res = evaluate_passage_evidence(
            _target(["physician_name"]), _result([_passage(text)]), PATIENT_A
        )
        assert res.status == EvidenceStatus.SUFFICIENT, f"Failed on: {text}"


def test_physician_name_invalid():
    texts = [
        "Patient should see a doctor.",
        "Referred to a physician.",
        "Physician: follow up in 2 weeks",
        "Provider: patient seen today",
        "Prescriber: recommended rest",
    ]
    for text in texts:
        res = evaluate_passage_evidence(
            _target(["physician_name"]), _result([_passage(text)]), PATIENT_A
        )
        assert res.status == EvidenceStatus.INSUFFICIENT, f"Failed on: {text}"


# --- clinic ---
def test_clinic_valid():
    texts = [
        "Treated at Mayo Clinic.",
        "Sent to General Hospital.",
        "Admitted to Health Center.",
        "Facility: Cleveland Clinic",
    ]
    for text in texts:
        res = evaluate_passage_evidence(
            _target(["clinic"]), _result([_passage(text)]), PATIENT_A
        )
        assert res.status == EvidenceStatus.SUFFICIENT, f"Failed on: {text}"


def test_clinic_invalid():
    texts = [
        "Went to the hospital.",
        "Arrived at the clinic.",
        "Transferred to a different center.",
    ]
    for text in texts:
        res = evaluate_passage_evidence(
            _target(["clinic"]), _result([_passage(text)]), PATIENT_A
        )
        assert res.status == EvidenceStatus.INSUFFICIENT, f"Failed on: {text}"


# --- contact_number ---
def test_contact_number_valid():
    texts = [
        "Call us at 555-123-4567.",
        "Phone: (800) 555-0199.",
        "Contact: +1-202-555-0143",
        "Reach out at 123.456.7890",
    ]
    for text in texts:
        res = evaluate_passage_evidence(
            _target(["contact_number"]), _result([_passage(text)]), PATIENT_A
        )
        assert res.status == EvidenceStatus.SUFFICIENT, f"Failed on: {text}"


def test_contact_number_invalid():
    texts = [
        "Patient id is 555123.",
        "Date of birth: 01-12-1980.",
        "Values were 12.3 and 45.6",
    ]
    for text in texts:
        res = evaluate_passage_evidence(
            _target(["contact_number"]), _result([_passage(text)]), PATIENT_A
        )
        assert res.status == EvidenceStatus.INSUFFICIENT, f"Failed on: {text}"


# --- dosage ---
def test_dosage_valid():
    texts = [
        "Dose: 10 mg",
        "Dosage: 20 mg daily",
        "Strength: 500 mg",
        "Take 1 tablet (10 mg) daily",
        "10 mg once daily",
    ]
    for text in texts:
        res = evaluate_passage_evidence(
            _target(["dosage"]), _result([_passage(text)]), PATIENT_A
        )
        assert res.status == EvidenceStatus.SUFFICIENT, f"Failed on: {text}"


def test_dosage_invalid():
    texts = [
        "He weighs 70 kg.",
        "Length is 5 cm.",
        "Just mg alone",
        "The mg concentration",
        "10 alone without unit",
    ]
    for text in texts:
        res = evaluate_passage_evidence(
            _target(["dosage"]), _result([_passage(text)]), PATIENT_A
        )
        assert res.status == EvidenceStatus.INSUFFICIENT, f"Failed on: {text}"


# --- frequency ---
def test_frequency_valid():
    texts = [
        "Take it daily.",
        "Administer BID.",
        "Use as needed (PRN).",
        "QID with meals.",
        "once a day",
        "every 8 hours",
    ]
    for text in texts:
        res = evaluate_passage_evidence(
            _target(["frequency"]), _result([_passage(text)]), PATIENT_A
        )
        assert res.status == EvidenceStatus.SUFFICIENT, f"Failed on: {text}"


def test_frequency_invalid():
    texts = [
        "He visits regularly.",
        "I always take it.",
        "Sometimes feels pain.",
    ]
    for text in texts:
        res = evaluate_passage_evidence(
            _target(["frequency"]), _result([_passage(text)]), PATIENT_A
        )
        assert res.status == EvidenceStatus.INSUFFICIENT, f"Failed on: {text}"


# --- blood_group ---
def test_blood_group_valid():
    texts = [
        "Blood type: O+",
        "Patient is A-",
        "Blood group AB positive",
        "Tested as B negative",
    ]
    for text in texts:
        res = evaluate_passage_evidence(
            _target(["blood_group"]), _result([_passage(text)]), PATIENT_A
        )
        assert res.status == EvidenceStatus.SUFFICIENT, f"Failed on: {text}"


def test_blood_group_invalid():
    texts = [
        "Patient got an A on the test.",
        "Positive for flu.",
        "Grade B negative.",
        "Blood was drawn.",
    ]
    for text in texts:
        res = evaluate_passage_evidence(
            _target(["blood_group"]), _result([_passage(text)]), PATIENT_A
        )
        assert res.status == EvidenceStatus.INSUFFICIENT, f"Failed on: {text}"


# --- status ---
def test_status_valid():
    texts = [
        "Status: Active",
        "Medication discontinued",
        "Condition is resolved",
        "Prescription inactive",
    ]
    for text in texts:
        res = evaluate_passage_evidence(
            _target(["status"]), _result([_passage(text)]), PATIENT_A
        )
        assert res.status == EvidenceStatus.SUFFICIENT, f"Failed on: {text}"


def test_status_invalid():
    texts = [
        "He is active in sports.",
        "Resolved to do better.",
    ]
    for text in texts:
        res = evaluate_passage_evidence(
            _target(["status"]), _result([_passage(text)]), PATIENT_A
        )
        assert res.status == EvidenceStatus.INSUFFICIENT, f"Failed on: {text}"


# --- consultation_notes ---
def test_consultation_notes_valid():
    texts = [
        "Assessment: Patient is improving.",
        "Notes: Follow up in 2 weeks.",
        "Impression: Normal scan.",
        "Plan: Start physical therapy.",
        "Conclusion: No acute findings.",
    ]
    for text in texts:
        res = evaluate_passage_evidence(
            _target(["consultation_notes"]), _result([_passage(text)]), PATIENT_A
        )
        assert res.status == EvidenceStatus.SUFFICIENT, f"Failed on: {text}"


def test_consultation_notes_invalid():
    texts = [
        "She noted the time.",
        "Made a plan for vacation.",
        "Left some notes on the desk.",
    ]
    for text in texts:
        res = evaluate_passage_evidence(
            _target(["consultation_notes"]), _result([_passage(text)]), PATIENT_A
        )
        assert res.status == EvidenceStatus.INSUFFICIENT, f"Failed on: {text}"


# --- Scenario 4-8: Entity + Attribute Binding ---


def test_named_entity_plus_prescriber_same_chunk():
    target = InquiryTarget(
        target_domain="clinical_documents",
        target_entity="Lisinopril",
        requested_attributes=["physician_name"],
    )
    res = evaluate_passage_evidence(
        target,
        _result([_passage("Lisinopril 10mg. Prescribed by Dr. Adams")]),
        PATIENT_A,
    )
    assert res.status == EvidenceStatus.SUFFICIENT


def test_entity_present_attribute_absent():
    target = InquiryTarget(
        target_domain="clinical_documents",
        target_entity="Lisinopril",
        requested_attributes=["physician_name"],
    )
    res = evaluate_passage_evidence(
        target, _result([_passage("Lisinopril 10mg.")]), PATIENT_A
    )
    assert res.status == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert (
        "not recorded" in res.evidence_directive.lower()
        or "not found" in res.evidence_directive.lower()
    )


def test_unrelated_attribute_passage_rejection():
    target = InquiryTarget(
        target_domain="clinical_documents",
        target_entity="Lisinopril",
        requested_attributes=["physician_name"],
    )
    res = evaluate_passage_evidence(
        target, _result([_passage("Ankle sprain. Prescribed by Dr. Jones")]), PATIENT_A
    )
    assert res.status == EvidenceStatus.INSUFFICIENT
    assert "lisinopril" in res.evidence_directive.lower()


def test_same_document_multi_passage_qualification():
    target = InquiryTarget(
        target_domain="clinical_documents",
        target_entity="Lisinopril",
        requested_attributes=["physician_name"],
    )
    p1 = _passage("Lisinopril 10mg.", document_id=_DOC_A)
    p2 = _passage("Prescribed by Dr. Adams", document_id=_DOC_A)
    p3 = _passage("Irrelevant passage.", document_id=_DOC_A)
    res = evaluate_passage_evidence(target, _result([p1, p2, p3]), PATIENT_A)
    assert res.status == EvidenceStatus.SUFFICIENT
    assert len(res.qualified_passages) == 2


def test_cross_document_combination_prohibition():
    target = InquiryTarget(
        target_domain="clinical_documents",
        target_entity="Lisinopril",
        requested_attributes=["physician_name"],
    )
    p1 = _passage("Lisinopril 10mg.", document_id=uuid.uuid4())
    p2 = _passage("Prescribed by Dr. Adams", document_id=uuid.uuid4())
    res = evaluate_passage_evidence(target, _result([p1, p2]), PATIENT_A)
    assert res.status == EvidenceStatus.PARTIALLY_SUFFICIENT


# --- Scenario 9-13: Anti-Topic Negatives ---


def test_anti_topic_negative_physician_role_header_with_generic_prose():
    res = evaluate_passage_evidence(
        _target(["physician_name"]),
        _result([_passage("Physician: follow up")]),
        PATIENT_A,
    )
    assert res.status == EvidenceStatus.INSUFFICIENT


def test_anti_topic_negative_product_package_quantity_containing_mg():
    res = evaluate_passage_evidence(
        _target(["dosage"]),
        _result([_passage("Supplied in 500 mg bottles")]),
        PATIENT_A,
    )
    assert res.status == EvidenceStatus.INSUFFICIENT


def test_anti_topic_negative_tablet_quantity_without_dosage_semantics():
    res = evaluate_passage_evidence(
        _target(["dosage"]), _result([_passage("Dispense 30 tablets")]), PATIENT_A
    )
    assert res.status == EvidenceStatus.INSUFFICIENT


def test_anti_topic_negative_generic_clinic_hospital_attendance():
    res = evaluate_passage_evidence(
        _target(["clinic"]),
        _result([_passage("Patient visited the hospital")]),
        PATIENT_A,
    )
    assert res.status == EvidenceStatus.INSUFFICIENT


def test_anti_topic_negative_arbitrary_numeric_string():
    res = evaluate_passage_evidence(
        _target(["contact_number"]),
        _result([_passage("Specimen ID: 9876543210")]),
        PATIENT_A,
    )
    assert res.status == EvidenceStatus.INSUFFICIENT


# --- Scenario 17-18: Multi-Attribute & Absence ---


def test_multi_attribute_partial_evidence():
    target = _target(["physician_name", "contact_number"])
    res = evaluate_passage_evidence(target, _result([_passage("Dr. Smith")]), PATIENT_A)
    assert res.status == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert res.missing_fields == ["contact_number"]


def test_absent_attribute_honesty():
    target = _target(["contact_number"])
    res = evaluate_passage_evidence(target, _result([_passage("Dr. Smith")]), PATIENT_A)
    assert res.status == EvidenceStatus.INSUFFICIENT
    assert "contact phone number" in res.evidence_directive.lower()


# --- Scenario 19: Multi-Document Dosage (Temporal Boundary) ---
def test_multi_document_dosage_temporal_boundary():
    doc_a = uuid.uuid4()
    p1 = RetrievedPassage(
        chunk_id=uuid.uuid4(),
        document_id=doc_a,
        patient_id=PATIENT_A,
        chunk_index=0,
        page_number=1,
        chunk_text="Take 10 mg daily.",
        document_display_name="Doc A",
        document_type="lab_report",
        document_date=None,
        cosine_distance=0.1,
        similarity=0.9,
    )

    doc_b = uuid.uuid4()
    p2 = RetrievedPassage(
        chunk_id=uuid.uuid4(),
        document_id=doc_b,
        patient_id=PATIENT_A,
        chunk_index=0,
        page_number=1,
        chunk_text="Dosage: 20 mg daily",
        document_display_name="Doc B",
        document_type="lab_report",
        document_date=None,
        cosine_distance=0.1,
        similarity=0.9,
    )

    target = _target(["dosage"])
    result = RetrievalResult(
        patient_id=PATIENT_A,
        target_domains=("clinical_documents",),
        query_text="dosage inquiry",
        top_k=5,
        passages=(p1, p2),
    )

    res = evaluate_passage_evidence(target, result, PATIENT_A)

    assert res.status == EvidenceStatus.SUFFICIENT
    assert len(res.qualified_passages) == 2
    cited_chunk_texts = [p.chunk_text for p in res.qualified_passages]
    assert "Take 10 mg daily." in cited_chunk_texts
    assert "Dosage: 20 mg daily" in cited_chunk_texts


# --- Scenario 21: Deterministic Repeated Evaluation ---
def test_deterministic_repeated_evaluation():
    target = _target(["physician_name"])
    result = _result([_passage("Dr. Smith advised bed rest.")])

    first_res = evaluate_passage_evidence(target, result, PATIENT_A)

    for _ in range(100):
        res = evaluate_passage_evidence(target, result, PATIENT_A)
        assert res.status == first_res.status
        assert res.missing_fields == first_res.missing_fields
        assert res.qualified_passages == first_res.qualified_passages
        assert res.evidence_directive == first_res.evidence_directive
