import logging
from datetime import date
from typing import Any, Optional

from app.health.evidence_evaluator import (
    HUMAN_ATTRIBUTE_LABELS,
    EvidenceResult,
    _qualifies_for_superlative,
    allocate_superlative_document_passages,
    evaluate_longitudinal_trajectory,
    extract_canonical_clinical_date,
    get_candidate_sort_key,
    resolve_superlative_attribute_status,
)
from app.health.retrieval import RetrievedPassage
from app.schemas.inquiry import EvidenceStatus, InquiryTarget, SuperlativeType

logger = logging.getLogger(__name__)


def fuse_cross_domain_evidence(
    target: InquiryTarget,
    struct_evidence: EvidenceResult,
    doc_evidence: EvidenceResult,
    structured_candidates: Optional[list[Any]] = None,
    document_candidates: Optional[list[RetrievedPassage]] = None,
) -> EvidenceResult:
    """Pure-function module to fuse evidence from structured health records
    and unstructured documents.
    Implements the 7-case truth table for cross-domain evidence sufficiency,
    cross-domain comparison longitudinal trajectory delegation, and
    cross-domain superlative reconciliation under Zero Silent Supersession.
    """
    is_comparison = target.question_intent == "COMPARISON"
    is_superlative = bool(
        target.temporal_constraint
        and target.temporal_constraint.superlative
        in (SuperlativeType.LATEST, SuperlativeType.FIRST)
    )

    # Invariant: COMPARISON and CROSS_DOMAIN SUPERLATIVES mandate candidate pools
    if is_comparison or is_superlative:
        if structured_candidates is None or document_candidates is None:
            intent_label = "comparison" if is_comparison else "superlative"
            raise ValueError(
                f"Cross-domain {intent_label} resolution requires full untruncated "
                "structured_candidates and document_candidates. Silent fallback "
                "to pre-truncated single-domain EvidenceResult evidence is forbidden."
            )

    if is_comparison:
        return evaluate_longitudinal_trajectory(
            structured_candidates=structured_candidates,
            document_candidates=document_candidates,
            target=target,
        )

    if is_superlative:
        superlative = target.temporal_constraint.superlative

        # 1. Superlative Semantic Qualification Preceding Recency Ranking
        qual_struct = [
            r for r in structured_candidates if _qualifies_for_superlative(r, target)
        ]
        qual_docs = [
            p for p in document_candidates if _qualifies_for_superlative(p, target)
        ]

        # 2. Extract Canonical Clinical Dates
        struct_dates = {
            extract_canonical_clinical_date(r)
            for r in qual_struct
            if extract_canonical_clinical_date(r) is not None
        }
        doc_dates = {
            extract_canonical_clinical_date(p)
            for p in qual_docs
            if extract_canonical_clinical_date(p) is not None
        }
        all_dates = struct_dates.union(doc_dates)

        if not all_dates:
            qual_struct_sorted = sorted(qual_struct, key=get_candidate_sort_key)
            retained_docs = allocate_superlative_document_passages(
                winning_date=None,
                passages=qual_docs,
                superlative=superlative,
            )
            has_matching = bool(qual_struct or qual_docs)
            entity_label = target.target_entity or "health"
            query_label = target.target_entity or "health query"
            return EvidenceResult(
                status=(
                    EvidenceStatus.PARTIALLY_SUFFICIENT
                    if has_matching
                    else EvidenceStatus.INSUFFICIENT
                ),
                matched_records=qual_struct_sorted,
                qualified_passages=retained_docs,
                matched_fields=[],
                missing_fields=(
                    list(target.requested_attributes)
                    if target.requested_attributes
                    else []
                ),
                temporal_interpretation="superlative",
                evidence_directive=(
                    f"Identified {entity_label} records, but no verifiable clinical "
                    "dates were recorded to establish recency."
                    if has_matching
                    else f"No records found for {query_label}."
                ),
            )

        winning_date = (
            max(all_dates) if superlative == SuperlativeType.LATEST else min(all_dates)
        )

        retained_struct = sorted(
            qual_struct,
            key=lambda c: (
                extract_canonical_clinical_date(c) or date.min,
                *get_candidate_sort_key(c),
            ),
        )
        retained_docs = allocate_superlative_document_passages(
            winning_date=winning_date,
            passages=qual_docs,
            superlative=superlative,
        )

        full_win_evidence = [
            c
            for c in (qual_struct + qual_docs)
            if extract_canonical_clinical_date(c) == winning_date
        ]
        serialized_win_evidence = [
            c
            for c in (retained_struct + retained_docs)
            if extract_canonical_clinical_date(c) == winning_date
        ]

        direction_word = (
            "Most recent" if superlative == SuperlativeType.LATEST else "Earliest"
        )
        entity_name = target.target_entity or "health"
        win_iso = winning_date.isoformat()
        base_directive = (
            f"{direction_word} {entity_name} record identified on {win_iso}."
        )

        status, matched_fields, missing_fields, directive = (
            resolve_superlative_attribute_status(
                full_win_evidence=full_win_evidence,
                serialized_win_evidence=serialized_win_evidence,
                target=target,
                base_directive=base_directive,
                winning_date=winning_date,
            )
        )

        return EvidenceResult(
            status=status,
            matched_records=retained_struct,
            qualified_passages=retained_docs,
            matched_fields=matched_fields,
            missing_fields=missing_fields,
            temporal_interpretation="superlative",
            evidence_directive=directive,
        )
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
