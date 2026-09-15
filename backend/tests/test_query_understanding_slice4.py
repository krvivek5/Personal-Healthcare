"""
Phase 2 — M3 Slice 4: Query Understanding Tests

Verifies that the deterministic query parser correctly identifies
document-oriented domains (labs, reports, clinical_documents, prescriptions)
while preserving all existing M1/M2 structured-domain behaviour.

No LLM is used anywhere in this module.
"""

from app.health.query_understanding import parse_natural_language_query
from app.schemas.inquiry import InquiryTarget

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse(q: str) -> InquiryTarget:
    return parse_natural_language_query(q)


# ---------------------------------------------------------------------------
# 1. Lab / blood-test queries  ->  domain="labs"
# ---------------------------------------------------------------------------


def test_lab_domain_creatinine():
    t = parse("What was my creatinine?")
    assert t.target_domain == "labs"
    assert t.target_entity is not None
    assert "creatinine" in t.target_entity.lower()


def test_lab_domain_hba1c():
    t = parse("Show me my HbA1c result")
    assert t.target_domain == "labs"
    assert "hba1c" in t.target_entity.lower()


def test_lab_domain_vitamin_d():
    t = parse("What is my Vitamin D level?")
    assert t.target_domain == "labs"
    assert "vitamin d" in t.target_entity.lower()


def test_lab_domain_cholesterol():
    t = parse("What are my cholesterol levels?")
    assert t.target_domain == "labs"


def test_lab_domain_blood_test_generic():
    t = parse("Can you show me my latest blood test?")
    assert t.target_domain == "labs"


def test_lab_domain_lipid_panel():
    t = parse("Do I have my lipid panel results?")
    assert t.target_domain == "labs"


def test_lab_domain_thyroid():
    t = parse("Show my thyroid results")
    assert t.target_domain == "labs"


# ---------------------------------------------------------------------------
# 2. Generic report queries  ->  domain="reports"
# ---------------------------------------------------------------------------


def test_report_domain_mri():
    t = parse("What did my MRI show?")
    assert t.target_domain == "reports"


def test_report_domain_xray():
    t = parse("Do I have an x-ray report?")
    assert t.target_domain == "reports"


def test_report_domain_ultrasound():
    t = parse("What did the ultrasound say?")
    assert t.target_domain == "reports"


def test_report_domain_ecg():
    t = parse("Show me my ECG")
    assert t.target_domain == "reports"


# ---------------------------------------------------------------------------
# 3. Clinical document queries  ->  domain="clinical_documents"
# ---------------------------------------------------------------------------


def test_clinical_domain_discharge_summary():
    t = parse("What was in my discharge summary?")
    assert t.target_domain == "clinical_documents"


def test_clinical_domain_referral():
    t = parse("Do I have a referral letter?")
    assert t.target_domain == "clinical_documents"


def test_clinical_domain_consultation_note():
    t = parse("What did the consultation note say?")
    assert t.target_domain == "clinical_documents"


def test_clinical_domain_doctor_letter():
    t = parse("Show me the doctor letter from my last visit")
    assert t.target_domain == "clinical_documents"


# ---------------------------------------------------------------------------
# 4. Prescription-document queries  ->  domain="prescriptions"
# ---------------------------------------------------------------------------


def test_prescription_domain_rx():
    t = parse("What was on my prescription?")
    assert t.target_domain == "prescriptions"


def test_prescription_domain_prescribed():
    t = parse("What was prescribed at my last appointment?")
    assert t.target_domain == "prescriptions"


def test_prescription_domain_discharge_prescription():
    t = parse("Show me my discharge prescription")
    assert t.target_domain == "prescriptions"


# ---------------------------------------------------------------------------
# 5. Structured domain precedence over document domains
#    (M1/M2 structured domains must win when present)
# ---------------------------------------------------------------------------


def test_structured_beats_doc_medications():
    """Query contains 'medication' (structured) AND 'lab'-ish terms —
    structured wins.
    """
    t = parse("What medication am I taking?")
    assert t.target_domain == "medications"


def test_structured_beats_doc_conditions():
    t = parse("Do I have any condition recorded?")
    assert t.target_domain == "conditions"


def test_structured_beats_doc_allergies():
    t = parse("Do I have any allergy?")
    assert t.target_domain == "allergies"


def test_structured_beats_doc_profile():
    t = parse("What is my blood type?")
    assert t.target_domain == "profile"


def test_lisinopril_stays_structured():
    """'Lisinopril' is a medication keyword — must NOT route to 'prescriptions'."""
    t = parse("What is my Lisinopril dosage?")
    assert t.target_domain == "medications"
    assert t.target_entity == "Lisinopril"
    assert "dosage" in t.requested_attributes


# ---------------------------------------------------------------------------
# 6. Ambiguous / general inquiry — remains deterministic
# ---------------------------------------------------------------------------


def test_ambiguous_query_is_deterministic():
    """A vague query should produce a consistent, repeatable result."""
    q = "How am I doing?"
    t1 = parse(q)
    t2 = parse(q)
    assert t1 == t2  # identical objects -> deterministic


def test_unknown_query_no_domain():
    t = parse("Hello")
    assert t.target_domain is None


def test_unknown_query_question_intent():
    t = parse("Tell me something useful")
    assert t.question_intent == "QUERY"


# ---------------------------------------------------------------------------
# 7. Backward compatibility: existing M1/M2 structured queries unchanged
# ---------------------------------------------------------------------------


def test_m1_lisinopril_dosage():
    t = parse("What is my Lisinopril dosage?")
    assert t.target_domain == "medications"
    assert t.target_entity == "Lisinopril"
    assert "dosage" in t.requested_attributes


def test_m1_albuterol_historical():
    t = parse("Was Albuterol prescribed to me in the past?")
    assert t.target_domain == "medications"
    assert t.target_entity == "Albuterol"
    assert t.temporal_scope == "historical"


def test_m1_asthma_condition():
    t = parse("Do I have asthma?")
    assert t.target_domain == "conditions"
    assert t.target_entity == "Asthma"


def test_m1_peanut_allergy():
    t = parse("Am I allergic to peanut?")
    assert t.target_domain == "allergies"
    assert t.target_entity == "Peanut"


def test_m1_symptom():
    t = parse("What are my current symptoms?")
    assert t.target_domain == "symptoms"


def test_m1_goals():
    t = parse("What are my health goals?")
    assert t.target_domain == "goals"


def test_m1_blood_type_profile():
    t = parse("What is my blood type?")
    assert t.target_domain == "profile"
    assert "blood_group" in t.requested_attributes


# ---------------------------------------------------------------------------
# 8. Temporal scope is preserved for document queries
# ---------------------------------------------------------------------------


def test_lab_temporal_current():
    t = parse("What are my current creatinine levels?")
    assert t.target_domain == "labs"
    assert t.temporal_scope == "current"


def test_lab_temporal_historical():
    t = parse("What was my HbA1c in the past?")
    assert t.target_domain == "labs"
    assert t.temporal_scope == "historical"
