import logging

from app.health.evidence_evaluator import HUMAN_ATTRIBUTE_LABELS, EvidenceResult
from app.schemas.inquiry import EvidenceStatus, InquiryTarget

logger = logging.getLogger(__name__)


def fuse_cross_domain_evidence(
    target: InquiryTarget,
    struct_evidence: EvidenceResult,
    doc_evidence: EvidenceResult,
) -> EvidenceResult:
    """
    Pure-function module to fuse evidence from structured health records
    and unstructured documents.
    Implements the 7-case truth table for cross-domain evidence sufficiency.
    """
    has_entity = bool(target.target_entity)
    has_attrs = bool(target.requested_attributes)

    # 1. Determine if the entity was confirmed anywhere
    struct_entity_confirmed = struct_evidence.status != EvidenceStatus.INSUFFICIENT
    doc_entity_confirmed = doc_evidence.status != EvidenceStatus.INSUFFICIENT

    entity_confirmed = struct_entity_confirmed or doc_entity_confirmed

    # Combine records and passages
    matched_records = struct_evidence.matched_records if struct_entity_confirmed else []
    # Only borrow doc passages if the document establishes the entity
    # (anti-misattribution)
    # If there is no entity requested, we just pool what we have.
    if has_entity:
        qualified_passages = (
            doc_evidence.qualified_passages if doc_entity_confirmed else []
        )
    else:
        qualified_passages = doc_evidence.qualified_passages

    # 2. Pool attributes
    # We only care about attributes that were matched.
    struct_matched = (
        set(struct_evidence.matched_fields) if struct_entity_confirmed else set()
    )
    doc_matched = set(doc_evidence.matched_fields) if doc_entity_confirmed else set()

    # Anti-misattribution: If entity is requested but doc didn't confirm it,
    # we cannot borrow its attributes.
    if has_entity and not doc_entity_confirmed:
        doc_matched = set()

    pooled_matched = struct_matched.union(doc_matched)

    # Determine missing attributes based on target
    pooled_missing = [
        attr for attr in target.requested_attributes if attr not in pooled_matched
    ]
    pooled_matched_list = [
        attr for attr in target.requested_attributes if attr in pooled_matched
    ]

    human_missing_fields = [HUMAN_ATTRIBUTE_LABELS.get(a, a) for a in pooled_missing]
    human_missing_str = ", ".join(human_missing_fields)

    status: EvidenceStatus
    directive: str

    if has_entity and has_attrs:
        if not entity_confirmed:
            # Case 6: Entity Absent Everywhere
            status = EvidenceStatus.INSUFFICIENT
            directive = (
                "Your records and documents do not contain a record of: "
                f"{target.target_entity}."
            )
        elif not pooled_missing:
            # Case 1: Complementary Sufficiency
            status = EvidenceStatus.SUFFICIENT
            directive = "All requested information is recorded."
        elif not pooled_matched:
            # Case 5: Entity Present, All Attributes Missing
            status = EvidenceStatus.PARTIALLY_SUFFICIENT
            directive = (
                f"{target.target_entity} is recorded, but not found in records: "
                f"{human_missing_str}."
            )
        else:
            # Case 4: Partial in Both (Entity Present, Some attributes satisfied,
            # some missing)
            status = EvidenceStatus.PARTIALLY_SUFFICIENT
            directive = (
                f"{target.target_entity} is recorded, but not found in records: "
                f"{human_missing_str}."
            )

    elif has_entity and not has_attrs:
        if not entity_confirmed:
            # Case 6: Entity Absent Everywhere
            status = EvidenceStatus.INSUFFICIENT
            directive = (
                "Your records and documents do not contain a record of: "
                f"{target.target_entity}."
            )
        elif struct_entity_confirmed:
            # Case 2: Structured Dominant
            status = EvidenceStatus.SUFFICIENT
            directive = "Relevant records found."
        else:
            # Case 3: Document Dominant
            status = EvidenceStatus.SUFFICIENT
            directive = "Relevant records found."

    elif not has_entity and has_attrs:
        if not pooled_matched:
            # Case 7: Attribute-Only Absent Everywhere
            status = EvidenceStatus.INSUFFICIENT
            directive = (
                "Your uploaded records were searched, but do not contain a record of: "
                f"{human_missing_str}."
            )
        elif not pooled_missing:
            status = EvidenceStatus.SUFFICIENT
            directive = "All requested information is recorded."
        else:
            status = EvidenceStatus.PARTIALLY_SUFFICIENT
            directive = (
                "Information partially found. Not found in records: "
                f"{human_missing_str}."
            )

    else:
        # Neither entity nor attributes (e.g. "show me my profile")
        if struct_entity_confirmed or doc_entity_confirmed:
            status = EvidenceStatus.SUFFICIENT
            directive = "Relevant records found."
        else:
            status = EvidenceStatus.INSUFFICIENT
            directive = "No records are available for this domain."

    return EvidenceResult(
        status=status,
        matched_records=matched_records,
        matched_fields=pooled_matched_list,
        missing_fields=pooled_missing,
        evidence_directive=directive,
        qualified_passages=qualified_passages,
        temporal_interpretation=target.temporal_scope,
    )
