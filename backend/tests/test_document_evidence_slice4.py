"""
Phase 2 — M3 Slice 4: Document Evidence Evaluator Tests

Verifies deterministic, tenant-safe, diagnostic-inference-free evaluation of
document extraction content against InquiryTargets.

Covers:
  - COMPLETED extraction with matching content -> SUFFICIENT
  - COMPLETED extraction with no matching content -> INSUFFICIENT
  - COMPLETED extraction with partial attribute match -> PARTIALLY_SUFFICIENT
  - Empty / None extracted_text -> INSUFFICIENT
  - FAILED extraction -> INSUFFICIENT
  - UNSUPPORTED extraction -> INSUFFICIENT
  - Tenant isolation: wrong patient_id -> INSUFFICIENT (silent)
  - No negative diagnostic assertions in any directive
  - No treatment inference in any directive
  - Absence directives use safe, document-scoped language
"""

import uuid
from datetime import date

from app.health.evidence_evaluator import (
    DocumentExtractionEvidence,
    evaluate_document_evidence,
)
from app.schemas.inquiry import EvidenceStatus, InquiryTarget

# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------

PATIENT_A = uuid.uuid4()
PATIENT_B = uuid.uuid4()
DOC_ID = uuid.uuid4()

# A realistic lab report text
LAB_REPORT_TEXT = """
Patient: John Doe
Date: 2024-01-15

Blood Results:
Creatinine: 0.9 mg/dL (Normal: 0.6-1.2 mg/dL)
HbA1c: 5.6%
Glucose: 95 mg/dL
HDL Cholesterol: 58 mg/dL
LDL Cholesterol: 112 mg/dL
Vitamin D: 32 ng/mL
TSH: 2.1 mIU/L
Hemoglobin: 13.8 g/dL
"""


def make_completed_evidence(
    text: str = LAB_REPORT_TEXT,
    patient_id: uuid.UUID = PATIENT_A,
    document_date: date | None = None,
) -> DocumentExtractionEvidence:
    return DocumentExtractionEvidence(
        document_id=DOC_ID,
        patient_id=patient_id,
        extraction_status="COMPLETED",
        extracted_text=text,
        document_date=document_date,
    )


def make_failed_evidence(
    patient_id: uuid.UUID = PATIENT_A,
) -> DocumentExtractionEvidence:
    return DocumentExtractionEvidence(
        document_id=DOC_ID,
        patient_id=patient_id,
        extraction_status="FAILED",
        extracted_text=None,
    )


def make_unsupported_evidence(
    patient_id: uuid.UUID = PATIENT_A,
) -> DocumentExtractionEvidence:
    return DocumentExtractionEvidence(
        document_id=DOC_ID,
        patient_id=patient_id,
        extraction_status="UNSUPPORTED",
        extracted_text=None,
    )


def lab_target(entity: str, attributes: list[str] | None = None) -> InquiryTarget:
    return InquiryTarget(
        target_domain="labs",
        target_entity=entity,
        requested_attributes=attributes or [],
    )


# ---------------------------------------------------------------------------
# 1. COMPLETED extraction + matching content -> SUFFICIENT
# ---------------------------------------------------------------------------


def test_completed_creatinine_found_sufficient():
    """Document contains 'creatinine' -> SUFFICIENT."""
    evidence = make_completed_evidence()
    target = lab_target("creatinine")
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    assert result.status == EvidenceStatus.SUFFICIENT


def test_completed_hba1c_found_sufficient():
    evidence = make_completed_evidence()
    target = lab_target("hba1c")
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    assert result.status == EvidenceStatus.SUFFICIENT


def test_completed_glucose_found_sufficient():
    evidence = make_completed_evidence()
    target = lab_target("glucose")
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    assert result.status == EvidenceStatus.SUFFICIENT


def test_completed_vitamin_d_found_sufficient():
    evidence = make_completed_evidence()
    # "vitamin d" as multi-word topic
    target = lab_target("vitamin d")
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    assert result.status == EvidenceStatus.SUFFICIENT


def test_completed_tsh_found_sufficient():
    evidence = make_completed_evidence()
    target = lab_target("tsh")
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    assert result.status == EvidenceStatus.SUFFICIENT


# ---------------------------------------------------------------------------
# 2. COMPLETED extraction + missing content -> INSUFFICIENT
# ---------------------------------------------------------------------------


def test_completed_analyte_absent_insufficient():
    """Document does not contain 'Troponin' -> INSUFFICIENT."""
    evidence = make_completed_evidence()
    target = lab_target("troponin")
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    assert result.status == EvidenceStatus.INSUFFICIENT


def test_completed_analyte_absent_uses_safe_directive():
    """Absence directive must NOT assert the patient does not have the condition."""
    evidence = make_completed_evidence()
    target = lab_target("troponin")
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    directive_lower = result.evidence_directive.lower()
    # Safe absence language
    assert "does not contain" in directive_lower or "not found" in directive_lower
    # Must NOT claim patient lacks it
    assert "does not have" not in directive_lower
    assert "patient does not" not in directive_lower
    assert "normal" not in directive_lower
    assert "healthy" not in directive_lower


def test_completed_no_match_directive_references_document():
    """Absence directive should reference the document, not the patient."""
    evidence = make_completed_evidence()
    target = lab_target("procalcitonin")
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    assert "document" in result.evidence_directive.lower()


# ---------------------------------------------------------------------------
# 3. Partial attribute match -> PARTIALLY_SUFFICIENT
# ---------------------------------------------------------------------------


def test_partial_attributes_partially_sufficient():
    """Request creatinine (present) and troponin (absent) -> PARTIALLY_SUFFICIENT."""
    evidence = make_completed_evidence()
    target = InquiryTarget(
        target_domain="labs",
        requested_attributes=["creatinine", "troponin"],
    )
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    assert result.status == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert "creatinine" in result.matched_fields
    assert "troponin" in result.missing_fields


def test_partial_attributes_directive_notes_missing():
    evidence = make_completed_evidence()
    target = InquiryTarget(
        target_domain="labs",
        requested_attributes=["hba1c", "d-dimer"],
    )
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    assert result.status == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert "d-dimer" in result.missing_fields
    assert "hba1c" in result.matched_fields
    assert "not found in document" in result.evidence_directive.lower()


def test_all_attributes_present_sufficient():
    """All requested attributes found -> SUFFICIENT."""
    evidence = make_completed_evidence()
    target = InquiryTarget(
        target_domain="labs",
        requested_attributes=["creatinine", "glucose", "hba1c"],
    )
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    assert result.status == EvidenceStatus.SUFFICIENT
    assert set(result.matched_fields) == {"creatinine", "glucose", "hba1c"}
    assert not result.missing_fields


def test_all_attributes_absent_insufficient():
    """No requested attributes found -> INSUFFICIENT."""
    evidence = make_completed_evidence()
    target = InquiryTarget(
        target_domain="labs",
        requested_attributes=["troponin", "d-dimer", "procalcitonin"],
    )
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    assert result.status == EvidenceStatus.INSUFFICIENT
    assert len(result.missing_fields) == 3


# ---------------------------------------------------------------------------
# 4. Empty extracted_text -> INSUFFICIENT
# ---------------------------------------------------------------------------


def test_empty_string_extraction_insufficient():
    evidence = DocumentExtractionEvidence(
        document_id=DOC_ID,
        patient_id=PATIENT_A,
        extraction_status="COMPLETED",
        extracted_text="",
    )
    target = lab_target("creatinine")
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    assert result.status == EvidenceStatus.INSUFFICIENT


def test_whitespace_only_extraction_insufficient():
    evidence = DocumentExtractionEvidence(
        document_id=DOC_ID,
        patient_id=PATIENT_A,
        extraction_status="COMPLETED",
        extracted_text="   \n  ",
    )
    target = lab_target("hba1c")
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    # Empty/whitespace text -> INSUFFICIENT (falsy check catches whitespace)
    assert result.status == EvidenceStatus.INSUFFICIENT


def test_none_extracted_text_insufficient():
    evidence = DocumentExtractionEvidence(
        document_id=DOC_ID,
        patient_id=PATIENT_A,
        extraction_status="COMPLETED",
        extracted_text=None,
    )
    target = lab_target("glucose")
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    assert result.status == EvidenceStatus.INSUFFICIENT


# ---------------------------------------------------------------------------
# 5. FAILED extraction -> INSUFFICIENT
# ---------------------------------------------------------------------------


def test_failed_extraction_insufficient():
    evidence = make_failed_evidence()
    target = lab_target("creatinine")
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    assert result.status == EvidenceStatus.INSUFFICIENT


def test_failed_extraction_directive_mentions_failed():
    evidence = make_failed_evidence()
    target = lab_target("hba1c")
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    assert "failed" in result.evidence_directive.lower()
    assert "no content" in result.evidence_directive.lower()


def test_failed_extraction_no_diagnostic_inference():
    evidence = make_failed_evidence()
    target = lab_target("hba1c")
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    directive_lower = result.evidence_directive.lower()
    assert "does not have" not in directive_lower
    assert "normal" not in directive_lower
    assert "deficiency" not in directive_lower


# ---------------------------------------------------------------------------
# 6. UNSUPPORTED extraction -> INSUFFICIENT
# ---------------------------------------------------------------------------


def test_unsupported_extraction_insufficient():
    evidence = make_unsupported_evidence()
    target = lab_target("creatinine")
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    assert result.status == EvidenceStatus.INSUFFICIENT


def test_unsupported_extraction_directive_mentions_unsupported():
    evidence = make_unsupported_evidence()
    target = lab_target("vitamin d")
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    assert "unsupported" in result.evidence_directive.lower()


# ---------------------------------------------------------------------------
# 7. Tenant isolation
# ---------------------------------------------------------------------------


def test_patient_b_document_patient_a_cannot_access():
    """Evidence belonging to Patient B must be invisible to Patient A."""
    evidence = DocumentExtractionEvidence(
        document_id=DOC_ID,
        patient_id=PATIENT_B,
        extraction_status="COMPLETED",
        extracted_text=LAB_REPORT_TEXT,
    )
    target = lab_target("creatinine")
    # Patient A requests — must get INSUFFICIENT
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    assert result.status == EvidenceStatus.INSUFFICIENT


def test_tenant_isolation_directive_reveals_no_content():
    """The directive for a tenant mismatch must NOT reveal that the document exists."""
    evidence = DocumentExtractionEvidence(
        document_id=DOC_ID,
        patient_id=PATIENT_B,
        extraction_status="COMPLETED",
        extracted_text=LAB_REPORT_TEXT,
    )
    target = lab_target("creatinine")
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    directive_lower = result.evidence_directive.lower()
    # Should not reveal the text or existence
    assert "creatinine" not in directive_lower
    assert "0.9" not in directive_lower


def test_patient_b_document_accessible_by_patient_b():
    """The correct patient can access their own document."""
    evidence = DocumentExtractionEvidence(
        document_id=DOC_ID,
        patient_id=PATIENT_B,
        extraction_status="COMPLETED",
        extracted_text=LAB_REPORT_TEXT,
    )
    target = lab_target("creatinine")
    result = evaluate_document_evidence(target, evidence, PATIENT_B)
    assert result.status == EvidenceStatus.SUFFICIENT


def test_patient_a_document_accessible_by_patient_a():
    """Patient A's own document is accessible."""
    evidence = make_completed_evidence(patient_id=PATIENT_A)
    target = lab_target("glucose")
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    assert result.status == EvidenceStatus.SUFFICIENT


# ---------------------------------------------------------------------------
# 8. No negative diagnostic claims or treatment inference
# ---------------------------------------------------------------------------


def test_no_diagnostic_claim_on_absence():
    """Absent analyte directive must NOT imply patient does not have a condition."""
    evidence = make_completed_evidence()
    target = lab_target("vitamin b12")  # Not in report
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    directive_lower = result.evidence_directive.lower()
    assert "deficiency" not in directive_lower
    assert "does not have" not in directive_lower
    assert "normal" not in directive_lower
    assert "no vitamin" not in directive_lower


def test_no_treatment_inference_on_presence():
    """Finding an analyte must NOT suggest any treatment or clinical interpretation."""
    evidence = make_completed_evidence()
    target = lab_target("creatinine")
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    directive_lower = result.evidence_directive.lower()
    assert "prescribe" not in directive_lower
    assert "treatment" not in directive_lower
    assert "diagnos" not in directive_lower
    assert "should" not in directive_lower


def test_insufficient_directive_not_diagnostic_no_vitamin_d():
    """
    Mimics spec example: query for Vitamin D, not in doc.
    Must NOT say 'You do not have a Vitamin D deficiency'.
    """
    text = "Creatinine: 0.9 mg/dL\nHbA1c: 5.6%\n"  # no vitamin D
    evidence = make_completed_evidence(text=text)
    target = lab_target("vitamin d")
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    assert result.status == EvidenceStatus.INSUFFICIENT
    directive_lower = result.evidence_directive.lower()
    assert "deficiency" not in directive_lower
    assert "does not have" not in directive_lower
    assert "your vitamin" not in directive_lower
    # Safe wording expected
    assert "does not contain" in directive_lower


# ---------------------------------------------------------------------------
# 9. Document date in directive (temporal labelling only)
# ---------------------------------------------------------------------------


def test_document_date_appears_in_absence_directive():
    doc_date = date(2024, 1, 15)
    evidence = make_completed_evidence(
        text="Creatinine: 0.9",
        document_date=doc_date,
    )
    target = lab_target("troponin")
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    assert result.status == EvidenceStatus.INSUFFICIENT
    # Date should appear in the directive for temporal context
    assert "2024-01-15" in result.evidence_directive


def test_no_document_date_directive_has_no_none():
    evidence = make_completed_evidence(document_date=None)
    target = lab_target("troponin")
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    assert "None" not in result.evidence_directive


# ---------------------------------------------------------------------------
# 10. No topic / no entity -> generic SUFFICIENT when text exists
# ---------------------------------------------------------------------------


def test_no_entity_no_attributes_generic_sufficient():
    """When no entity or attributes are specified, presence of text is SUFFICIENT."""
    evidence = make_completed_evidence()
    target = InquiryTarget(target_domain="labs")
    result = evaluate_document_evidence(target, evidence, PATIENT_A)
    assert result.status == EvidenceStatus.SUFFICIENT
