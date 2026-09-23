import uuid
from datetime import date
from typing import Any

from app.health.evidence_evaluator import EvidenceResult
from app.health.evidence_fusion import fuse_cross_domain_evidence
from app.health.retrieval import RetrievedPassage
from app.schemas.inquiry import EvidenceStatus, InquiryTarget, RoutingMode


def _make_target(has_attrs: bool = False) -> InquiryTarget:
    return InquiryTarget(
        target_domain="conditions",
        target_entity="Diabetes",
        requested_attributes=["status", "notes"] if has_attrs else [],
        routing_mode=RoutingMode.CROSS_DOMAIN,
        candidate_structured_domains=["conditions"],
        candidate_document_domains=["clinical_notes"],
    )


def _make_struct(
    status: EvidenceStatus, records: list[Any] = None, matched_fields: list[str] = None
) -> EvidenceResult:
    return EvidenceResult(
        status=status,
        matched_records=records or [],
        matched_fields=matched_fields or [],
        evidence_directive=f"Structured: {status.value}",
    )


def _make_doc(
    status: EvidenceStatus,
    passages: list[RetrievedPassage] = None,
    matched_fields: list[str] = None,
) -> EvidenceResult:
    return EvidenceResult(
        status=status,
        matched_records=[],
        matched_fields=matched_fields or [],
        evidence_directive=f"Document: {status.value}",
        qualified_passages=passages or [],
    )


class DummyRecord:
    def __init__(self):
        self.id = uuid.uuid4()


def _make_passage() -> RetrievedPassage:
    return RetrievedPassage(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        patient_id=uuid.uuid4(),
        page_number=1,
        document_date=date.today(),
        chunk_index=0,
        chunk_text="Patient has diabetes.",
        document_display_name="Note",
        document_type="clinical_notes",
        cosine_distance=0.1,
        similarity=0.9,
    )


def test_fuse_both_sufficient_with_attrs():
    """Case 1: SUFFICIENT + SUFFICIENT -> SUFFICIENT (Complementary Sufficiency)"""
    target = _make_target(has_attrs=True)
    struct_evidence = _make_struct(
        EvidenceStatus.PARTIALLY_SUFFICIENT, [DummyRecord()], ["status"]
    )
    doc_evidence = _make_doc(
        EvidenceStatus.PARTIALLY_SUFFICIENT, [_make_passage()], ["notes"]
    )

    fused = fuse_cross_domain_evidence(target, struct_evidence, doc_evidence)

    assert fused.status == EvidenceStatus.SUFFICIENT
    assert fused.evidence_directive == "All requested information is recorded."
    assert len(fused.matched_records) == 1
    assert len(fused.qualified_passages) == 1
    assert set(fused.matched_fields) == {"status", "notes"}


def test_fuse_struct_sufficient_doc_insufficient():
    """Case 2: SUFFICIENT + INSUFFICIENT -> SUFFICIENT (Structured Dominant)"""
    target = _make_target(has_attrs=False)
    struct_evidence = _make_struct(EvidenceStatus.SUFFICIENT, [DummyRecord()])
    doc_evidence = _make_doc(EvidenceStatus.INSUFFICIENT)

    fused = fuse_cross_domain_evidence(target, struct_evidence, doc_evidence)

    assert fused.status == EvidenceStatus.SUFFICIENT
    assert fused.evidence_directive == "Relevant records found."
    assert len(fused.matched_records) == 1
    assert len(fused.qualified_passages) == 0


def test_fuse_struct_insufficient_doc_sufficient():
    """Case 3: INSUFFICIENT + SUFFICIENT -> SUFFICIENT (Document Dominant)"""
    target = _make_target(has_attrs=False)
    struct_evidence = _make_struct(EvidenceStatus.INSUFFICIENT)
    doc_evidence = _make_doc(EvidenceStatus.SUFFICIENT, [_make_passage()])

    fused = fuse_cross_domain_evidence(target, struct_evidence, doc_evidence)

    assert fused.status == EvidenceStatus.SUFFICIENT
    assert fused.evidence_directive == "Relevant records found."
    assert len(fused.matched_records) == 0
    assert len(fused.qualified_passages) == 1


def test_fuse_partial_in_both():
    """
    Case 4: PARTIALLY_SUFFICIENT + PARTIALLY_SUFFICIENT -> PARTIALLY_SUFFICIENT
    (Missing some attrs)
    """
    target = _make_target(has_attrs=True)
    # We request ["status", "notes"]. Provide only "status" across both.
    struct_evidence = _make_struct(
        EvidenceStatus.PARTIALLY_SUFFICIENT, [DummyRecord()], ["status"]
    )
    doc_evidence = _make_doc(
        EvidenceStatus.PARTIALLY_SUFFICIENT, [_make_passage()], ["status"]
    )

    fused = fuse_cross_domain_evidence(target, struct_evidence, doc_evidence)

    assert fused.status == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert (
        "Diabetes is recorded, but not found in records: notes"
        in fused.evidence_directive
    )
    assert len(fused.matched_records) == 1
    assert len(fused.qualified_passages) == 1


def test_fuse_entity_present_all_attrs_missing():
    """Case 5: Entity Present, All Attributes Missing -> PARTIALLY_SUFFICIENT"""
    target = _make_target(has_attrs=True)
    struct_evidence = _make_struct(
        EvidenceStatus.PARTIALLY_SUFFICIENT, [DummyRecord()], []
    )
    doc_evidence = _make_doc(EvidenceStatus.PARTIALLY_SUFFICIENT, [_make_passage()], [])

    fused = fuse_cross_domain_evidence(target, struct_evidence, doc_evidence)

    assert fused.status == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert (
        "Diabetes is recorded, but not found in records: status, notes"
        in fused.evidence_directive
    )


def test_fuse_both_insufficient():
    """Case 6: INSUFFICIENT + INSUFFICIENT -> INSUFFICIENT (Entity Absent Everywhere)"""
    target = _make_target(has_attrs=False)
    struct_evidence = _make_struct(EvidenceStatus.INSUFFICIENT)
    doc_evidence = _make_doc(EvidenceStatus.INSUFFICIENT)

    fused = fuse_cross_domain_evidence(target, struct_evidence, doc_evidence)

    assert fused.status == EvidenceStatus.INSUFFICIENT
    assert (
        fused.evidence_directive
        == "Your records and documents do not contain a record of: Diabetes."
    )
    assert len(fused.matched_records) == 0
    assert len(fused.qualified_passages) == 0


def test_fuse_attribute_only_absent_everywhere():
    """Case 7: Attribute-Only Absent Everywhere -> INSUFFICIENT"""
    target = InquiryTarget(
        target_domain="conditions",
        target_entity=None,
        requested_attributes=["status"],
        routing_mode=RoutingMode.CROSS_DOMAIN,
        candidate_structured_domains=["conditions"],
        candidate_document_domains=["clinical_notes"],
    )
    struct_evidence = _make_struct(EvidenceStatus.INSUFFICIENT)
    doc_evidence = _make_doc(EvidenceStatus.INSUFFICIENT)

    fused = fuse_cross_domain_evidence(target, struct_evidence, doc_evidence)

    assert fused.status == EvidenceStatus.INSUFFICIENT
    assert (
        "Your uploaded records were searched, but do not contain a record of: status"
        in fused.evidence_directive
    )


def test_fuse_anti_misattribution_guard():
    """
    Verify that document attributes are not borrowed if the document
    does not confirm the entity.
    """
    target = _make_target(has_attrs=True)
    # Structured confirms entity but misses 'notes'.
    struct_evidence = _make_struct(
        EvidenceStatus.PARTIALLY_SUFFICIENT, [DummyRecord()], ["status"]
    )
    # Document misses entity (INSUFFICIENT) but hallucinated/extracted 'notes' anyway.
    doc_evidence = _make_doc(EvidenceStatus.INSUFFICIENT, [_make_passage()], ["notes"])

    fused = fuse_cross_domain_evidence(target, struct_evidence, doc_evidence)

    assert fused.status == EvidenceStatus.PARTIALLY_SUFFICIENT
    assert "notes" not in fused.matched_fields
    assert "notes" in fused.missing_fields
    assert (
        len(fused.qualified_passages) == 0
    )  # Should not borrow passages if doc didn't confirm entity
