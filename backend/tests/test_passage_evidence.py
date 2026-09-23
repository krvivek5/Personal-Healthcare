"""Unit tests for passage-level evidence evaluation — Phase 2 Milestone 4 Slice 5.

Tests cover:
 - Rule A: attribute pooling across multiple passages
   (SUFFICIENT / PARTIALLY_SUFFICIENT / INSUFFICIENT)
 - Rule B: entity-only topical matching
 - Rule C: generic domain queries
 - Deterministic field ordering (preserves target.requested_attributes order)
 - Tenant fail-closed isolation (retrieval_result.patient_id + per-passage patient_id)
 - Empty retrieval result gating
 - Safe absence directives (corpus-level, not document-specific)
 - Backward compatibility: existing evaluate_evidence and
   evaluate_document_evidence unaffected
"""

import uuid
from datetime import date
from typing import Optional

from app.health.evidence_evaluator import (
    _absent_records_directive,
    evaluate_passage_evidence,
)
from app.health.retrieval import RetrievalResult, RetrievedPassage
from app.schemas.inquiry import EvidenceStatus, InquiryTarget

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

PATIENT_A: uuid.UUID = uuid.uuid4()
PATIENT_B: uuid.UUID = uuid.uuid4()

_DOC_A: uuid.UUID = uuid.uuid4()
_DOC_B: uuid.UUID = uuid.uuid4()


def _passage(
    chunk_text: str,
    *,
    patient_id: uuid.UUID = PATIENT_A,
    chunk_id: Optional[uuid.UUID] = None,
    document_id: Optional[uuid.UUID] = None,
    chunk_index: int = 0,
    page_number: Optional[int] = 1,
    document_type: str = "lab_report",
    cosine_distance: float = 0.10,
) -> RetrievedPassage:
    """Build a minimal ``RetrievedPassage`` for testing."""
    return RetrievedPassage(
        chunk_id=chunk_id or uuid.uuid4(),
        document_id=document_id or _DOC_A,
        patient_id=patient_id,
        chunk_index=chunk_index,
        page_number=page_number,
        chunk_text=chunk_text,
        document_display_name="Test Document",
        document_type=document_type,
        document_date=date(2025, 1, 15),
        cosine_distance=cosine_distance,
        similarity=max(0.0, 1.0 - cosine_distance),
    )


def _result(
    passages: list[RetrievedPassage],
    *,
    patient_id: uuid.UUID = PATIENT_A,
) -> RetrievalResult:
    """Build a ``RetrievalResult`` for testing."""
    return RetrievalResult(
        patient_id=patient_id,
        target_domains=("labs",),
        query_text="test query",
        top_k=5,
        passages=tuple(passages),
    )


def _target(
    *,
    domain: Optional[str] = "labs",
    entity: Optional[str] = None,
    attributes: Optional[list[str]] = None,
) -> InquiryTarget:
    return InquiryTarget(
        target_domain=domain,
        target_entity=entity,
        requested_attributes=attributes or [],
    )


# ---------------------------------------------------------------------------
# Rule A — attribute pooling across multiple passages
# ---------------------------------------------------------------------------


class TestRuleAAttributePooling:
    """Tests for Rule A: all requested attributes pooled across passages."""

    def test_all_attributes_found_across_two_passages(self) -> None:
        """SUFFICIENT when each attribute appears in a different passage."""
        p1 = _passage("Cholesterol: 195 mg/dL. HDL: 55 mg/dL (ref: 40-60).")
        p2 = _passage("LDL: 120 mg/dL. Normal reference range 0-129 mg/dL.")

        target = _target(attributes=["cholesterol", "hdl", "ldl"])
        result = evaluate_passage_evidence(target, _result([p1, p2]), PATIENT_A)

        assert result.status == EvidenceStatus.SUFFICIENT
        assert set(result.matched_fields) == {"cholesterol", "hdl", "ldl"}
        assert result.missing_fields == []
        assert "All requested information" in result.evidence_directive

    def test_all_attributes_in_single_passage(self) -> None:
        """SUFFICIENT when a single passage contains all attributes."""
        p = _passage("Hemoglobin: 14.2 g/dL. Hematocrit: 42%. MCV: 88 fL.")
        target = _target(attributes=["hemoglobin", "hematocrit", "mcv"])
        result = evaluate_passage_evidence(target, _result([p]), PATIENT_A)

        assert result.status == EvidenceStatus.SUFFICIENT
        assert result.missing_fields == []

    def test_partially_sufficient_with_missing_fields(self) -> None:
        """PARTIALLY_SUFFICIENT when some attributes are absent from all passages."""
        p1 = _passage("Fasting glucose: 95 mg/dL. Reference: 70-100.")
        target = _target(attributes=["fasting glucose", "hba1c", "insulin"])

        result = evaluate_passage_evidence(target, _result([p1]), PATIENT_A)

        assert result.status == EvidenceStatus.PARTIALLY_SUFFICIENT
        assert result.matched_fields == ["fasting glucose"]
        # missing_fields preserves target ordering
        assert result.missing_fields == ["hba1c", "insulin"]
        assert "hba1c" in result.evidence_directive
        assert "insulin" in result.evidence_directive

    def test_missing_fields_ordering_preserved(self) -> None:
        """missing_fields preserves requested_attributes order, not match order."""
        p = _passage("Sodium: 140 mEq/L. Potassium: 4.0 mEq/L.")
        # Declare attributes in reverse alphabetical order
        target = _target(attributes=["sodium", "potassium", "chloride", "bicarbonate"])

        result = evaluate_passage_evidence(target, _result([p]), PATIENT_A)

        assert result.status == EvidenceStatus.PARTIALLY_SUFFICIENT
        # matched in target order
        assert result.matched_fields == ["sodium", "potassium"]
        # missing in target order
        assert result.missing_fields == ["chloride", "bicarbonate"]

    def test_no_attributes_found_is_insufficient(self) -> None:
        """INSUFFICIENT with safe absence directive when zero attributes match."""
        p = _passage("WBC: 6.8 K/uL. RBC: 4.90 M/uL. Hemoglobin: 15.2 g/dL.")
        target = _target(attributes=["creatinine"])

        result = evaluate_passage_evidence(target, _result([p]), PATIENT_A)

        assert result.status == EvidenceStatus.INSUFFICIENT
        assert "creatinine" in result.evidence_directive
        assert "Your uploaded records were searched" in result.evidence_directive
        assert result.missing_fields == ["creatinine"]

    def test_absence_directive_does_not_make_medical_claim(self) -> None:
        """INSUFFICIENT directive names missing attribute but makes no
        clinical assertion."""
        p = _passage("Sodium: 140 mEq/L.")
        target = _target(attributes=["creatinine"])

        result = evaluate_passage_evidence(target, _result([p]), PATIENT_A)

        # Must NOT assert the patient lacks creatinine — only that it is not in records
        assert "do not have" not in result.evidence_directive.lower()
        assert "do not contain" in result.evidence_directive.lower()

    def test_pooling_across_five_passages(self) -> None:
        """Attribute pooling works across the maximum number of S4 passages."""
        passages = [
            _passage("eGFR: 65 mL/min", chunk_index=0, cosine_distance=0.05),
            _passage("Creatinine: 1.1 mg/dL", chunk_index=1, cosine_distance=0.08),
            _passage("BUN: 18 mg/dL", chunk_index=2, cosine_distance=0.12),
            _passage("Sodium: 140 mEq/L", chunk_index=3, cosine_distance=0.15),
            _passage("Potassium: 4.0 mEq/L", chunk_index=4, cosine_distance=0.18),
        ]
        target = _target(
            attributes=["eGFR", "creatinine", "BUN", "sodium", "potassium"]
        )
        result = evaluate_passage_evidence(target, _result(passages), PATIENT_A)

        assert result.status == EvidenceStatus.SUFFICIENT
        assert len(result.matched_fields) == 5

    def test_cross_document_fusion_allowed_for_attributes_only(self) -> None:
        """Attributes from different documents ARE fused (no target_entity)."""
        p1 = _passage("eGFR: 65 mL/min", document_id=_DOC_A)
        p2 = _passage("Creatinine: 1.1 mg/dL", document_id=_DOC_B)

        target = _target(attributes=["eGFR", "creatinine"])
        result = evaluate_passage_evidence(target, _result([p1, p2]), PATIENT_A)

        assert result.status == EvidenceStatus.SUFFICIENT
        assert len(result.matched_fields) == 2
        assert len(result.missing_fields) == 0


# ---------------------------------------------------------------------------
# Rule B — entity-only matching
# ---------------------------------------------------------------------------


class TestRuleBEntityOnly:
    """Tests for Rule B: entity present or absent across all passages."""

    def test_entity_found_in_passage_is_sufficient(self) -> None:
        """SUFFICIENT when topical entity found in at least one passage."""
        p = _passage("Ejection fraction estimated at 55-60%. Normal systolic function.")
        target = _target(domain="reports", entity="ejection fraction")
        result = evaluate_passage_evidence(target, _result([p]), PATIENT_A)

        assert result.status == EvidenceStatus.SUFFICIENT

    def test_entity_absent_from_all_passages_is_insufficient(self) -> None:
        """INSUFFICIENT with entity named when entity absent from all passages."""
        p = _passage("WBC normal. Hemoglobin within range.")
        target = _target(domain="reports", entity="ejection fraction")
        result = evaluate_passage_evidence(target, _result([p]), PATIENT_A)

        assert result.status == EvidenceStatus.INSUFFICIENT
        assert "ejection fraction" in result.evidence_directive

    def test_entity_found_in_second_of_two_passages(self) -> None:
        """Entity in any passage (not just first) qualifies as SUFFICIENT."""
        p1 = _passage("BNP: 220 pg/mL. Elevated.")
        p2 = _passage("Ejection fraction: 35%. Severely reduced.")
        target = _target(domain="reports", entity="ejection fraction")
        result = evaluate_passage_evidence(target, _result([p1, p2]), PATIENT_A)

        assert result.status == EvidenceStatus.SUFFICIENT

    def test_word_boundary_prevents_false_positive(self) -> None:
        """_keyword_present word-boundary matching prevents sub-word false positives."""
        # "pt" should NOT match "patient"
        p = _passage("patient id: 1234")
        target = _target(entity="pt")
        result = evaluate_passage_evidence(target, _result([p]), PATIENT_A)

        assert result.status == EvidenceStatus.INSUFFICIENT

    def test_entity_binding_per_document(self) -> None:
        """Entity presence is required in the SAME document as the attributes."""
        # DOC_A has entity but not attribute
        p1 = _passage("Ejection fraction discussed.", document_id=_DOC_A)
        # DOC_B has attribute but not entity
        p2 = _passage("status: normal.", document_id=_DOC_B)

        target = _target(entity="ejection fraction", attributes=["status"])
        result = evaluate_passage_evidence(target, _result([p1, p2]), PATIENT_A)

        assert result.status == EvidenceStatus.PARTIALLY_SUFFICIENT
        assert "status" in result.missing_fields


# ---------------------------------------------------------------------------
# Rule C — generic domain query
# ---------------------------------------------------------------------------


class TestRuleCGenericDomain:
    """Tests for Rule C: no entity, no attributes."""

    def test_passages_present_is_sufficient(self) -> None:
        """Generic query with passages → SUFFICIENT."""
        p = _passage("Some lab report content.")
        target = _target(domain="labs")
        result = evaluate_passage_evidence(target, _result([p]), PATIENT_A)

        assert result.status == EvidenceStatus.SUFFICIENT

    def test_no_passages_is_insufficient(self) -> None:
        """Generic query with zero passages → INSUFFICIENT."""
        target = _target(domain="labs")
        result = evaluate_passage_evidence(target, _result([]), PATIENT_A)

        assert result.status == EvidenceStatus.INSUFFICIENT


# ---------------------------------------------------------------------------
# Empty retrieval result gating
# ---------------------------------------------------------------------------


class TestEmptyRetrieval:
    """Tests for the empty-result gate (before any rule evaluation)."""

    def test_empty_passages_attributes_returns_insufficient(self) -> None:
        """Zero passages → INSUFFICIENT naming the missing attributes."""
        target = _target(attributes=["cholesterol", "ldl"])
        result = evaluate_passage_evidence(target, _result([]), PATIENT_A)

        assert result.status == EvidenceStatus.INSUFFICIENT
        assert (
            "cholesterol" in result.evidence_directive
            or "ldl" in result.evidence_directive
        )
        assert result.missing_fields == ["cholesterol", "ldl"]

    def test_empty_passages_entity_names_entity_in_directive(self) -> None:
        """Zero passages with entity → INSUFFICIENT naming the entity."""
        target = _target(entity="ejection fraction")
        result = evaluate_passage_evidence(target, _result([]), PATIENT_A)

        assert result.status == EvidenceStatus.INSUFFICIENT
        assert "ejection fraction" in result.evidence_directive

    def test_empty_passages_generic_returns_domain_directive(self) -> None:
        """Zero passages, generic target → INSUFFICIENT with domain message."""
        target = _target(domain="labs")
        result = evaluate_passage_evidence(target, _result([]), PATIENT_A)

        assert result.status == EvidenceStatus.INSUFFICIENT


# ---------------------------------------------------------------------------
# Tenant isolation — fail-closed
# ---------------------------------------------------------------------------


class TestTenantIsolation:
    """Tenant integrity gate: any mismatch must produce INSUFFICIENT silently."""

    def test_retrieval_result_patient_id_mismatch_fails_closed(self) -> None:
        """retrieval_result.patient_id != requesting_patient_id → INSUFFICIENT."""
        p = _passage("cholesterol: 195", patient_id=PATIENT_A)
        wrong_result = _result([p], patient_id=PATIENT_B)
        target = _target(attributes=["cholesterol"])

        result = evaluate_passage_evidence(target, wrong_result, PATIENT_A)

        assert result.status == EvidenceStatus.INSUFFICIENT
        # Directive must NOT reveal that matching content exists
        assert "cholesterol" not in result.evidence_directive
        assert result.matched_fields == []

    def test_individual_passage_patient_id_mismatch_fails_closed(self) -> None:
        """Foreign patient_id on any individual passage → fail-closed INSUFFICIENT."""
        good = _passage("cholesterol: 195", patient_id=PATIENT_A)
        bad = _passage("hdl: 55", patient_id=PATIENT_B)

        target = _target(attributes=["cholesterol", "hdl"])
        result = evaluate_passage_evidence(target, _result([good, bad]), PATIENT_A)

        assert result.status == EvidenceStatus.INSUFFICIENT
        # No matched content from good passage should leak
        assert result.matched_fields == []
        # Directive must not reference specific clinical values
        assert "hdl" not in result.evidence_directive
        assert "cholesterol" not in result.evidence_directive

    def test_all_matching_patient_id_is_sufficient(self) -> None:
        """Correct patient_id on all passages → normal evaluation proceeds."""
        p = _passage("cholesterol: 195", patient_id=PATIENT_A)
        target = _target(attributes=["cholesterol"])
        result = evaluate_passage_evidence(
            target, _result([p], patient_id=PATIENT_A), PATIENT_A
        )

        assert result.status == EvidenceStatus.SUFFICIENT


# ---------------------------------------------------------------------------
# Absence directive helper
# ---------------------------------------------------------------------------


class TestAbsentRecordsDirective:
    """Unit tests for the corpus-level _absent_records_directive helper."""

    def test_single_term(self) -> None:
        directive = _absent_records_directive(["creatinine"])
        assert "creatinine" in directive
        assert "do not contain" in directive
        assert "uploaded records were searched" in directive

    def test_multiple_terms(self) -> None:
        directive = _absent_records_directive(["hba1c", "insulin"])
        assert "hba1c" in directive
        assert "insulin" in directive

    def test_does_not_reference_document_date(self) -> None:
        """Corpus-level directive must not reference a specific document date."""
        directive = _absent_records_directive(["creatinine"])
        assert "dated" not in directive
        assert "uploaded document" not in directive


# ---------------------------------------------------------------------------
# Backward compatibility — existing M3 functions unaffected
# ---------------------------------------------------------------------------


class TestM3BackwardCompatibility:
    """Ensure existing evaluate_evidence and evaluate_document_evidence still work."""

    def test_evaluate_evidence_still_importable(self) -> None:
        """evaluate_evidence (M1/M3 structured context path) still available."""
        from app.health.evidence_evaluator import evaluate_evidence

        assert callable(evaluate_evidence)

    def test_evaluate_document_evidence_still_importable(self) -> None:
        """evaluate_document_evidence (M3 single-document path) still available."""
        from app.health.evidence_evaluator import evaluate_document_evidence

        assert callable(evaluate_document_evidence)

    def test_absent_directive_m3_signature_unchanged(self) -> None:
        """M3 _absent_directive still takes (terms, document_date) signature."""
        from app.health.evidence_evaluator import _absent_directive

        directive = _absent_directive(["creatinine"], date(2025, 1, 1))
        assert "uploaded document" in directive
        assert "2025-01-01" in directive

    def test_absent_directive_m3_and_s5_are_distinct(self) -> None:
        """M3 _absent_directive and S5 _absent_records_directive differ semantically."""
        from app.health.evidence_evaluator import _absent_directive

        m3 = _absent_directive(["creatinine"], date(2025, 6, 1))
        s5 = _absent_records_directive(["creatinine"])

        # M3 mentions specific document; S5 mentions uploaded records corpus
        assert "uploaded document" in m3
        assert "uploaded records" in s5
        assert m3 != s5
