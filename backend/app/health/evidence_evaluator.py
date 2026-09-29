import logging
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.health.inquiry_context import StructuredHealthContext
from app.health.retrieval import RetrievalResult, RetrievedPassage
from app.schemas.inquiry import (
    EvidenceStatus,
    InquiryTarget,
    SuperlativeType,
    TemporalScope,
    TimelineEventEvidence,
)
from app.schemas.timeline import HealthEvent

logger = logging.getLogger(__name__)


class TrajectoryCompleteness(str, Enum):
    """Deterministic completeness signal for longitudinal comparison inquiries."""

    COMPLETE_WITHIN_EVALUATED_CANDIDATES = "COMPLETE_WITHIN_EVALUATED_CANDIDATES"
    BOUNDED_WITH_ADDITIONAL_QUALIFIED_CANDIDATES = (
        "BOUNDED_WITH_ADDITIONAL_QUALIFIED_CANDIDATES"
    )


BOUNDED_TRAJECTORY_QUALIFIER: str = (
    "Note: This summary highlights key milestone dates (Baseline, Intermediate, "
    "and Latest). Additional qualified dated candidates were identified in the "
    "evaluated evidence set and are not shown in this summary."
)

HUMAN_ATTRIBUTE_LABELS: dict[str, str] = {
    "physician_name": "physician name",
    "dosage": "dosage",
    "clinic": "clinic or facility name",
    "consultation_notes": "consultation notes or doctor recommendations",
    "contact_number": "contact phone number",
    "frequency": "medication frequency",
    "status": "status",
    "blood_group": "blood group",
    "systolic": "systolic",
    "diastolic": "diastolic",
    "pulse": "pulse",
    "ldl": "LDL",
    "hdl": "HDL",
    "iron": "Iron",
    "ferritin": "Ferritin",
    "trigger": "trigger",
}


class EvidenceResult(BaseModel):
    """Clean internal result representation for response synthesis.

    M4 S6 extension: ``qualified_passages`` carries the exact passage
    instances that corroborated the clinical query.  The S6 orchestrator
    maps these directly into ``context.passages`` without re-running
    ``_keyword_present``.
    """

    status: EvidenceStatus
    matched_records: list[Any] = []
    matched_fields: list[str] = []
    missing_fields: list[str] = []
    temporal_interpretation: str = "all"
    evidence_directive: str = ""
    # M4 S6: authoritative S5 → S6 qualified-passage handoff.
    # Populated by evaluate_passage_evidence; empty for INSUFFICIENT evidence
    # or structured-domain evaluation paths.
    qualified_passages: list[RetrievedPassage] = Field(default_factory=list)
    # S4 extension: deterministic completeness signal for longitudinal comparisons
    trajectory_completeness: Optional[TrajectoryCompleteness] = None


def _parse_event_date(date_str: str) -> Optional[date]:
    """Parse an event or document date string into a canonical date object.

    Date Precision Contract (Authoritative Option A - Parent Lock Sec 7.3 Item 3):
    - Standard ISO 'YYYY-MM-DD' -> date(YYYY, MM, DD)
    - ISO timestamp 'YYYY-MM-DDTHH:MM:SS...' -> parses leading YYYY-MM-DD date
    - Partial dates ('YYYY-MM', 'YYYY') lack day precision and return None (undated)
      to prevent fabricating synthetic day-1 timestamps (e.g. YYYY-MM-01).
    - Invalid or unrecognized formats -> returns None (undated)
    """
    if not date_str or not isinstance(date_str, str):
        return None
    raw = date_str.strip()
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            pass
    return None


def extract_canonical_clinical_date(candidate: Any) -> Optional[date]:
    """Extract verified canonical clinical date from an arbitrary candidate object.

    Type Safety & Date Precision Invariants:
    - isinstance(val, datetime) MUST precede isinstance(val, date) because
      datetime is a subclass of date. A datetime object returns val.date().
    - isinstance(val, date) returns val directly.
    - String representations parsed via _parse_event_date supporting full ISO
      (YYYY-MM-DD) format; partial dates (YYYY-MM, YYYY) return None under
      authoritative Option A.
    - Timeline event with event_type == "DOCUMENT_UPLOADED" returns None.
    - Administrative timestamps (created_at, updated_at, recorded_at,
      uploaded_at) are NEVER used.
    - Undated records return None.
    """
    if candidate is None:
        return None

    if isinstance(candidate, datetime):
        return candidate.date()
    if isinstance(candidate, date):
        return candidate
    if isinstance(candidate, str):
        return _parse_event_date(candidate)

    # 1. Timeline event
    if hasattr(candidate, "event_type") and hasattr(candidate, "event_date"):
        if candidate.event_type == "DOCUMENT_UPLOADED":
            return None
        ev_date = candidate.event_date
        if isinstance(ev_date, datetime):
            return ev_date.date()
        if isinstance(ev_date, date):
            return ev_date
        if isinstance(ev_date, str):
            return _parse_event_date(ev_date)
        return None

    # 2. Document passage or context
    if hasattr(candidate, "document_date"):
        doc_date = getattr(candidate, "document_date")
        if isinstance(doc_date, datetime):
            return doc_date.date()
        if isinstance(doc_date, date):
            return doc_date
        if isinstance(doc_date, str):
            return _parse_event_date(doc_date)
        return None

    # 3. Structured record (Condition, Medication, Symptom, LabResult)
    if hasattr(candidate, "started_at"):
        started_at = getattr(candidate, "started_at")
        if isinstance(started_at, datetime):
            return started_at.date()
        if isinstance(started_at, date):
            return started_at
        if isinstance(started_at, str):
            return _parse_event_date(started_at)
        return None

    if hasattr(candidate, "performed_at"):
        performed_at = getattr(candidate, "performed_at")
        if isinstance(performed_at, datetime):
            return performed_at.date()
        if isinstance(performed_at, date):
            return performed_at
        if isinstance(performed_at, str):
            return _parse_event_date(performed_at)
        return None

    return None


def get_provenance_class(candidate: Any) -> int:
    """Returns provenance tie-break class:
    0 = STRUCTURED (relational records and TimelineEventEvidence)
    1 = DOCUMENT (RetrievedPassage and document excerpts)
    """
    if isinstance(candidate, RetrievedPassage) or hasattr(candidate, "chunk_index"):
        return 1
    return 0


def get_candidate_sort_key(candidate: Any) -> tuple[int, str, int]:
    """Extracts a typed deterministic tie-break tuple:
    (provenance_class, primary_id_str, chunk_index_int)

    - STRUCTURED (relational):
        (0, str(candidate.id), 0)
    - TIMELINE (TimelineEventEvidence):
        (0, str(candidate.id), 0)
    - DOCUMENT (RetrievedPassage):
        (1, str(candidate.document_id), int(candidate.chunk_index))

    Numeric ordering for chunk_index ensures chunk 2 strictly precedes chunk 10.
    """
    if isinstance(candidate, RetrievedPassage) or hasattr(candidate, "chunk_index"):
        doc_id = str(getattr(candidate, "document_id", ""))
        chunk_idx = int(getattr(candidate, "chunk_index", 0))
        return (1, doc_id, chunk_idx)

    # Authoritative repository field for TimelineEventEvidence is id;
    # fallback to event_id retained only for fixture compatibility.
    if hasattr(candidate, "id"):
        return (0, str(candidate.id), 0)
    if hasattr(candidate, "event_id"):
        return (0, str(candidate.event_id), 0)
    return (0, "", 0)


def get_candidate_tie_key(candidate: Any) -> tuple[int, str, int]:
    """Typed tuple alias for get_candidate_sort_key."""
    return get_candidate_sort_key(candidate)


def _candidate_is_relevant(candidate: Any, target: InquiryTarget) -> bool:
    """Check if candidate belongs to the requested entity or domain.
    Unrelated candidates are disqualified and cannot contribute dates to Q_dates.
    Entity-relevant candidates remain temporally eligible even with incomplete
    attributes.
    """
    if not target.target_entity:
        return True
    entity_lower = target.target_entity.lower().strip()
    if isinstance(candidate, RetrievedPassage) or hasattr(candidate, "chunk_text"):
        return _keyword_present(entity_lower, candidate.chunk_text.lower())
    if hasattr(candidate, "event_type") and (
        hasattr(candidate, "description") or hasattr(candidate, "title")
    ):
        desc = getattr(candidate, "description", "") or ""
        title = getattr(candidate, "title", "") or ""
        return _keyword_present(entity_lower, desc.lower()) or _keyword_present(
            entity_lower, title.lower()
        )
    name = (
        getattr(candidate, "name", None)
        or getattr(candidate, "condition_name", None)
        or getattr(candidate, "medication_name", None)
        or getattr(candidate, "symptom_name", None)
        or getattr(candidate, "allergen", None)
        or getattr(candidate, "test_name", None)
        or ""
    )
    return _keyword_present(entity_lower, str(name).lower())


def _candidate_attribute_presence(candidate: Any, attr: str) -> bool:
    """Type-aware attribute presence check:
    - Relational structured record: hasattr/getattr check
    - TimelineEventEvidence: S3 lexicon on event.description / title
    - RetrievedPassage: M5 lexicon on chunk_text
    """
    if isinstance(candidate, RetrievedPassage) or hasattr(candidate, "chunk_text"):
        return _evaluate_attribute_lexicon(attr, candidate.chunk_text)
    if hasattr(candidate, "event_type") and (
        hasattr(candidate, "description") or hasattr(candidate, "title")
    ):
        desc = getattr(candidate, "description", "") or ""
        title = getattr(candidate, "title", "") or ""
        combined = f"{title} {desc}".strip()
        return _evaluate_attribute_lexicon(attr, combined) or _keyword_present(
            attr.lower(), combined.lower()
        )
    if hasattr(candidate, attr) and getattr(candidate, attr) is not None:
        return True
    attr_lower = attr.lower()
    for field_name in (
        f"{attr_lower}_name",
        f"clinical_{attr_lower}",
        f"is_{attr_lower}",
    ):
        if (
            hasattr(candidate, field_name)
            and getattr(candidate, field_name) is not None
        ):
            return True
    return False


def collect_relevant_candidates(
    candidates: list[Any],
    target: InquiryTarget,
) -> list[Any]:
    return [c for c in candidates if _candidate_is_relevant(c, target)]


def _qualifies_for_superlative(candidate: Any, target: InquiryTarget) -> bool:
    """Superlative semantic qualification helper (Parent Architecture Lock Sec 7.3)."""
    if not _candidate_is_relevant(candidate, target):
        return False
    if not target.requested_attributes:
        return True
    return any(
        _candidate_attribute_presence(candidate, attr)
        for attr in target.requested_attributes
    )


def collect_superlative_candidates(
    candidates: list[Any],
    target: InquiryTarget,
) -> list[Any]:
    return [c for c in candidates if _qualifies_for_superlative(c, target)]


def allocate_attribute_aware_milestone_passages(
    milestone_dates: list[date],
    passages_or_by_date: dict[date, list[RetrievedPassage]] | list[RetrievedPassage],
    requested_attributes_or_target: list[str] | InquiryTarget = (),
    budget: int = 4,
) -> list[RetrievedPassage]:
    """Deterministic attribute-aware passage allocation enforcing budget K <= 4.

    Fixed milestone quotas:
    - 3 milestone dates: Baseline 1, Intermediate 1, Latest up to 2 (K <= 4)
    - 2 milestone dates: Baseline up to 2, Latest up to 2 (K <= 4)
    - 1 milestone date: up to 4 (K <= 4)

    Within each milestone bucket, candidates are prioritized by:
    1. Prefer passages that cover requested attributes not yet covered by
       previously selected passages.
    2. Passages with equivalent marginal attribute coverage are tie-broken
       deterministically by typed sort key:
       (str(p.document_id) ASC, int(p.chunk_index) ASC).

    Unallocated passages beyond the milestone quota are strictly excluded.
    """
    if isinstance(requested_attributes_or_target, InquiryTarget):
        requested_attributes = requested_attributes_or_target.requested_attributes
    else:
        requested_attributes = list(requested_attributes_or_target)

    if isinstance(passages_or_by_date, list):
        passages_by_date: dict[date, list[RetrievedPassage]] = {}
        for p in passages_or_by_date:
            p_date = extract_canonical_clinical_date(p)
            if p_date and p_date in milestone_dates:
                passages_by_date.setdefault(p_date, []).append(p)
    else:
        passages_by_date = passages_or_by_date

    allocated: list[RetrievedPassage] = []

    def _allocate_bucket(bucket_date: date, quota: int) -> list[RetrievedPassage]:
        candidates = list(passages_by_date.get(bucket_date, []))
        if not candidates or quota <= 0:
            return []

        selected: list[RetrievedPassage] = []
        uncovered = set(requested_attributes)

        while len(selected) < quota and candidates:
            scored = []
            for p in candidates:
                gain = len(
                    {a for a in uncovered if _candidate_attribute_presence(p, a)}
                )
                total = len(
                    {
                        a
                        for a in requested_attributes
                        if _candidate_attribute_presence(p, a)
                    }
                )
                scored.append((gain, total, p))

            scored.sort(
                key=lambda x: (
                    -x[0],
                    -x[1],
                    str(x[2].document_id),
                    int(x[2].chunk_index),
                )
            )
            best_p = scored[0][2]
            selected.append(best_p)
            candidates.remove(best_p)
            for a in list(uncovered):
                if _candidate_attribute_presence(best_p, a):
                    uncovered.remove(a)

        return selected

    if len(milestone_dates) == 3:
        allocated.extend(_allocate_bucket(milestone_dates[0], 1))
        allocated.extend(_allocate_bucket(milestone_dates[1], 1))
        allocated.extend(_allocate_bucket(milestone_dates[2], 2))
    elif len(milestone_dates) == 2:
        allocated.extend(_allocate_bucket(milestone_dates[0], 2))
        allocated.extend(_allocate_bucket(milestone_dates[1], 2))
    elif len(milestone_dates) == 1:
        allocated.extend(_allocate_bucket(milestone_dates[0], min(4, budget)))

    return allocated


def allocate_superlative_document_passages(
    winning_date: Optional[date],
    passages: list[RetrievedPassage],
    superlative: SuperlativeType | int = SuperlativeType.LATEST,
    budget: int = 4,
) -> list[RetrievedPassage]:
    """Shared winner-preserving document passage allocator (Budget K <= 4).
    Enforces parent architecture lock Section 7.3 and Zero Silent Supersession.

    Partitions candidates into 3 mutually exclusive buckets:
    1. docs_on_win: passages dated winning_date
    2. dated_docs_other: passages with a valid clinical date != winning_date
    3. undated_docs: passages with no verifiable clinical date
    """
    if isinstance(superlative, int):
        budget = superlative
        superlative = SuperlativeType.LATEST

    if not passages:
        return []
    if winning_date is None:
        sorted_undated = sorted(passages, key=get_candidate_sort_key)
        return sorted_undated[:budget]

    docs_on_win = [
        p for p in passages if extract_canonical_clinical_date(p) == winning_date
    ]
    dated_docs_other = [
        p
        for p in passages
        if extract_canonical_clinical_date(p) is not None
        and extract_canonical_clinical_date(p) != winning_date
    ]
    undated_docs = [p for p in passages if extract_canonical_clinical_date(p) is None]

    docs_on_win.sort(key=get_candidate_sort_key)
    dated_docs_other.sort(
        key=lambda c: (extract_canonical_clinical_date(c), *get_candidate_sort_key(c))
    )
    undated_docs.sort(key=get_candidate_sort_key)

    allocated: list[RetrievedPassage] = []
    if docs_on_win:
        win_quota = min(2 if dated_docs_other else budget, budget)
        allocated.extend(docs_on_win[:win_quota])

    rem = budget - len(allocated)
    if rem > 0 and dated_docs_other:
        if superlative == SuperlativeType.LATEST:
            allocated.extend(dated_docs_other[-rem:])
        else:
            allocated.extend(dated_docs_other[:rem])

    rem = budget - len(allocated)
    if rem > 0 and undated_docs:
        allocated.extend(undated_docs[:rem])

    allocated.sort(
        key=lambda c: (
            extract_canonical_clinical_date(c) or date.min,
            *get_candidate_sort_key(c),
        )
    )
    return allocated


def resolve_superlative_attribute_status(
    *args: Any,
    full_win_evidence: Optional[list[Any]] = None,
    serialized_win_evidence: Optional[list[Any]] = None,
    full_winning_date_attributes: Optional[Any] = None,
    serialized_winning_date_attributes: Optional[Any] = None,
    target: Optional[InquiryTarget] = None,
    base_directive: Optional[str] = None,
    winning_date: Optional[date] = None,
) -> tuple[EvidenceStatus, list[str], list[str], str]:
    """Authoritative shared helper for winning-date attribute evaluation.
    Consumed identically by evaluate_passage_evidence and fuse_cross_domain_evidence.
    """
    if len(args) >= 1:
        if isinstance(args[0], InquiryTarget):
            target = args[0]
            if len(args) > 1:
                base_directive = args[1]
            if len(args) > 2:
                winning_date = args[2]
            if len(args) > 3:
                full_winning_date_attributes = args[3]
            if len(args) > 4:
                serialized_winning_date_attributes = args[4]
        else:
            full_win_evidence = args[0]
            if len(args) > 1:
                serialized_win_evidence = args[1]
            if len(args) > 2:
                target = args[2]
            if len(args) > 3:
                base_directive = args[3]
            if len(args) > 4:
                winning_date = args[4]

    if target is None:
        raise ValueError("target is required in resolve_superlative_attribute_status")
    if base_directive is None:
        base_directive = ""

    has_attrs = bool(target.requested_attributes)
    if not has_attrs:
        return (EvidenceStatus.SUFFICIENT, [], [], base_directive)

    winning_date_str = winning_date.isoformat() if winning_date else ""

    if full_winning_date_attributes is not None:
        if isinstance(full_winning_date_attributes, (set, list, tuple)):
            items = list(full_winning_date_attributes)
            if items and isinstance(items[0], str):
                full_attrs_set = set(items)
            else:
                full_attrs_set = {
                    a
                    for a in target.requested_attributes
                    if any(_candidate_attribute_presence(c, a) for c in items)
                }
        else:
            full_attrs_set = set()
    elif full_win_evidence is not None:
        items = list(full_win_evidence)
        if items and isinstance(items[0], str):
            full_attrs_set = set(items)
        else:
            full_attrs_set = {
                a
                for a in target.requested_attributes
                if any(_candidate_attribute_presence(c, a) for c in items)
            }
    else:
        full_attrs_set = set()

    if serialized_winning_date_attributes is not None:
        if isinstance(serialized_winning_date_attributes, (set, list, tuple)):
            items = list(serialized_winning_date_attributes)
            if items and isinstance(items[0], str):
                serialized_attrs_set = set(items)
            else:
                serialized_attrs_set = {
                    a
                    for a in target.requested_attributes
                    if any(_candidate_attribute_presence(c, a) for c in items)
                }
        else:
            serialized_attrs_set = set()
    elif serialized_win_evidence is not None:
        items = list(serialized_win_evidence)
        if items and isinstance(items[0], str):
            serialized_attrs_set = set(items)
        else:
            serialized_attrs_set = {
                a
                for a in target.requested_attributes
                if any(_candidate_attribute_presence(c, a) for c in items)
            }
    else:
        serialized_attrs_set = set()

    genuinely_missing = [
        a for a in target.requested_attributes if a not in full_attrs_set
    ]
    budget_omitted = [
        a
        for a in target.requested_attributes
        if a in full_attrs_set and a not in serialized_attrs_set
    ]
    fully_covered = [
        a
        for a in target.requested_attributes
        if a in full_attrs_set and a in serialized_attrs_set
    ]

    matched_fields = fully_covered + budget_omitted
    missing_fields = genuinely_missing

    human_missing_str = ", ".join(
        HUMAN_ATTRIBUTE_LABELS.get(a, a) for a in genuinely_missing
    )
    human_omitted_str = ", ".join(
        HUMAN_ATTRIBUTE_LABELS.get(a, a) for a in budget_omitted
    )

    if genuinely_missing and budget_omitted:
        status = EvidenceStatus.PARTIALLY_SUFFICIENT
        directive = (
            f"{base_directive} Not recorded on {winning_date_str}: "
            f"{human_missing_str}. Additional information for '{human_omitted_str}' "
            f"on {winning_date_str} could not be displayed due to summary space limits."
        )
    elif genuinely_missing:
        status = (
            EvidenceStatus.PARTIALLY_SUFFICIENT
            if matched_fields
            else EvidenceStatus.INSUFFICIENT
        )
        directive = (
            f"{base_directive} Not recorded on {winning_date_str}: {human_missing_str}."
        )
    elif budget_omitted:
        status = EvidenceStatus.PARTIALLY_SUFFICIENT
        directive = (
            f"{base_directive} Additional information for '{human_omitted_str}' "
            f"on {winning_date_str} could not be displayed due to summary space limits."
        )
    else:
        status = EvidenceStatus.SUFFICIENT
        directive = base_directive

    return (status, matched_fields, missing_fields, directive)


def select_longitudinal_milestones(distinct_dates: list[date]) -> list[date]:
    """Enforces the locked Longitudinal Trajectory Policy (Section 7.1):
    N <= 3 milestone dates: Baseline, Intermediate (when applicable), Latest.
    """
    if not distinct_dates:
        return []
    sorted_dates = sorted(set(distinct_dates))
    if len(sorted_dates) <= 2:
        return sorted_dates
    return [sorted_dates[0], sorted_dates[-2], sorted_dates[-1]]


def evaluate_longitudinal_trajectory(
    structured_candidates: Optional[list[Any]],
    document_candidates: Optional[list[RetrievedPassage]],
    target: InquiryTarget,
) -> EvidenceResult:
    """Unified deterministic trajectory policy helper for COMPARISON inquiries."""
    struct_cands = structured_candidates or []
    doc_cands = document_candidates or []

    # 1. Candidate-level relevance filter
    rel_struct = [r for r in struct_cands if _candidate_is_relevant(r, target)]
    rel_docs = [p for p in doc_cands if _candidate_is_relevant(p, target)]

    # 2. Canonical clinical date extraction on relevant candidates
    struct_by_date: dict[date, list[Any]] = {}
    for r in rel_struct:
        r_date = extract_canonical_clinical_date(r)
        if r_date is not None:
            struct_by_date.setdefault(r_date, []).append(r)

    doc_by_date: dict[date, list[RetrievedPassage]] = {}
    for p in rel_docs:
        p_date = extract_canonical_clinical_date(p)
        if p_date is not None:
            doc_by_date.setdefault(p_date, []).append(p)

    # 3. Deterministic candidate sorting within each date bucket
    for d in struct_by_date:
        struct_by_date[d].sort(key=get_candidate_sort_key)
    for d in doc_by_date:
        doc_by_date[d].sort(key=get_candidate_sort_key)

    all_dates = set(struct_by_date.keys()).union(set(doc_by_date.keys()))
    q_dates = sorted(all_dates)

    has_attrs = bool(target.requested_attributes)
    has_entity = bool(target.target_entity)

    # Case 0: 0 distinct clinical dates
    if len(q_dates) == 0:
        return EvidenceResult(
            status=EvidenceStatus.INSUFFICIENT,
            matched_records=[],
            qualified_passages=[],
            matched_fields=[],
            missing_fields=list(target.requested_attributes) if has_attrs else [],
            temporal_interpretation="comparison",
            evidence_directive=(
                "No clinically dated records were found to compare changes over time."
            ),
            trajectory_completeness=None,
        )

    # Case 1: Exactly 1 distinct clinical date
    if len(q_dates) == 1:
        single_date = q_dates[0]
        single_date_str = single_date.isoformat()
        milestone_struct = list(struct_by_date.get(single_date, []))
        milestone_docs = list(doc_by_date.get(single_date, []))
        allocated_docs = allocate_attribute_aware_milestone_passages(
            [single_date], {single_date: milestone_docs}, target.requested_attributes
        )
        milestone_struct.sort(
            key=lambda c: (
                extract_canonical_clinical_date(c) or date.min,
                *get_candidate_sort_key(c),
            )
        )
        allocated_docs.sort(
            key=lambda c: (
                extract_canonical_clinical_date(c) or date.min,
                *get_candidate_sort_key(c),
            )
        )

        all_single_candidates = milestone_struct + milestone_docs
        matched_fields = [
            a
            for a in target.requested_attributes
            if any(_candidate_attribute_presence(c, a) for c in all_single_candidates)
        ]
        missing_fields = [
            a for a in target.requested_attributes if a not in matched_fields
        ]
        human_missing = [HUMAN_ATTRIBUTE_LABELS.get(a, a) for a in missing_fields]
        human_missing_str = ", ".join(human_missing)

        directive = (
            f"Only a single record on {single_date_str} was found; "
            f"at least two recorded dates are required to compare changes over time."
        )
        if missing_fields:
            directive += f" Not recorded: {human_missing_str}."

        return EvidenceResult(
            status=EvidenceStatus.PARTIALLY_SUFFICIENT,
            matched_records=milestone_struct,
            qualified_passages=allocated_docs,
            matched_fields=matched_fields,
            missing_fields=missing_fields,
            temporal_interpretation="comparison",
            evidence_directive=directive,
            trajectory_completeness=TrajectoryCompleteness.COMPLETE_WITHIN_EVALUATED_CANDIDATES,
        )

    # Case 2: >= 2 distinct clinical dates
    milestone_dates = select_longitudinal_milestones(q_dates)
    milestone_set = set(milestone_dates)

    is_bounded = set(q_dates) != milestone_set
    completeness = (
        TrajectoryCompleteness.BOUNDED_WITH_ADDITIONAL_QUALIFIED_CANDIDATES
        if is_bounded
        else TrajectoryCompleteness.COMPLETE_WITHIN_EVALUATED_CANDIDATES
    )

    scoped_struct: list[Any] = []
    for d in milestone_dates:
        scoped_struct.extend(struct_by_date.get(d, []))
    scoped_struct.sort(
        key=lambda c: (
            extract_canonical_clinical_date(c) or date.min,
            *get_candidate_sort_key(c),
        )
    )

    passages_for_milestones = {
        d: list(doc_by_date.get(d, [])) for d in milestone_dates if d in doc_by_date
    }

    all_milestone_universe = scoped_struct + [
        p for p_list in passages_for_milestones.values() for p in p_list
    ]
    full_attribute_dates: dict[str, set[date]] = {
        a: set() for a in target.requested_attributes
    }
    for c in all_milestone_universe:
        c_date = extract_canonical_clinical_date(c)
        if c_date and c_date in milestone_set:
            for a in target.requested_attributes:
                if _candidate_attribute_presence(c, a):
                    full_attribute_dates[a].add(c_date)

    all_evaluated_candidates = rel_struct + rel_docs
    universe_attribute_presence: dict[str, bool] = {
        a: any(_candidate_attribute_presence(c, a) for c in all_evaluated_candidates)
        for a in target.requested_attributes
    }

    matched_fields = [
        a for a in target.requested_attributes if len(full_attribute_dates[a]) >= 1
    ]
    missing_fields = [
        a for a in target.requested_attributes if len(full_attribute_dates[a]) == 0
    ]
    genuinely_missing = [
        a for a in missing_fields if not universe_attribute_presence[a]
    ]
    outside_milestone_attrs = [
        a for a in missing_fields if universe_attribute_presence[a]
    ]
    single_date_attributes = [
        a for a in target.requested_attributes if len(full_attribute_dates[a]) == 1
    ]

    allocated_passages = allocate_attribute_aware_milestone_passages(
        milestone_dates, passages_for_milestones, target.requested_attributes
    )
    allocated_passages.sort(
        key=lambda c: (
            extract_canonical_clinical_date(c) or date.min,
            *get_candidate_sort_key(c),
        )
    )

    serialized_evidence = scoped_struct + allocated_passages
    serialized_attribute_dates: dict[str, set[date]] = {
        a: set() for a in target.requested_attributes
    }
    for c in serialized_evidence:
        c_date = extract_canonical_clinical_date(c)
        if c_date and c_date in milestone_set:
            for a in target.requested_attributes:
                if _candidate_attribute_presence(c, a):
                    serialized_attribute_dates[a].add(c_date)

    budget_omitted_comparison_attrs = [
        a
        for a in target.requested_attributes
        if len(full_attribute_dates[a]) >= 2 and len(serialized_attribute_dates[a]) < 2
    ]

    has_limitations = bool(
        genuinely_missing
        or outside_milestone_attrs
        or single_date_attributes
        or budget_omitted_comparison_attrs
    )

    if has_attrs:
        if not has_limitations:
            status = EvidenceStatus.SUFFICIENT
            directive = "All requested information is recorded across comparison dates."
        else:
            if (
                outside_milestone_attrs
                or single_date_attributes
                or budget_omitted_comparison_attrs
                or matched_fields
                or has_entity
            ):
                status = EvidenceStatus.PARTIALLY_SUFFICIENT
            else:
                status = EvidenceStatus.INSUFFICIENT

            base_statement = (
                f"{target.target_entity} is recorded."
                if has_entity
                else "Information partially available."
            )
            fragments: list[str] = []

            if genuinely_missing:
                human_missing_str = ", ".join(
                    HUMAN_ATTRIBUTE_LABELS.get(a, a) for a in genuinely_missing
                )
                fragments.append(f"Not found in records: {human_missing_str}.")

            if outside_milestone_attrs:
                human_outside_str = ", ".join(
                    HUMAN_ATTRIBUTE_LABELS.get(a, a) for a in outside_milestone_attrs
                )
                fragments.append(
                    "Not recorded on the selected comparison milestone dates: "
                    f"{human_outside_str}."
                )

            if single_date_attributes:
                single_attr_labels = [
                    HUMAN_ATTRIBUTE_LABELS.get(a, a) for a in single_date_attributes
                ]
                single_joined = ", ".join(single_attr_labels)
                fragments.append(
                    f"Attribute '{single_joined}' was recorded on only one "
                    "milestone date and cannot be compared across time."
                )

            if budget_omitted_comparison_attrs:
                omitted_labels = [
                    HUMAN_ATTRIBUTE_LABELS.get(a, a)
                    for a in budget_omitted_comparison_attrs
                ]
                omitted_joined = ", ".join(omitted_labels)
                fragments.append(
                    f"Additional comparison dates for '{omitted_joined}' "
                    "could not be displayed due to summary space limits."
                )

            directive = f"{base_statement} {' '.join(fragments)}".strip()
    else:
        status = EvidenceStatus.SUFFICIENT
        directive = "Relevant records found across comparison dates."

    if is_bounded and BOUNDED_TRAJECTORY_QUALIFIER not in directive:
        directive = f"{directive.rstrip()} {BOUNDED_TRAJECTORY_QUALIFIER}".strip()

    return EvidenceResult(
        status=status,
        matched_records=scoped_struct,
        qualified_passages=allocated_passages,
        matched_fields=matched_fields,
        missing_fields=missing_fields,
        temporal_interpretation="comparison",
        evidence_directive=directive,
        trajectory_completeness=completeness,
    )


def _timeline_empty_directive(target: InquiryTarget) -> EvidenceResult:
    """Safe directive when recent_timeline_events is empty."""
    if target.target_entity:
        return EvidenceResult(
            status=EvidenceStatus.INSUFFICIENT,
            evidence_directive=(
                f"No timeline events were recorded matching: {target.target_entity}."
            ),
        )
    return EvidenceResult(
        status=EvidenceStatus.INSUFFICIENT,
        evidence_directive="Timeline events are not recorded.",
    )


def _timeline_temporal_empty_directive(target: InquiryTarget) -> EvidenceResult:
    """Safe directive when timeline events exist but none survive temporal filtering."""
    if target.temporal_scope in ("interval", TemporalScope.INTERVAL):
        time_phrase = (
            target.temporal_constraint.raw_expression
            if target.temporal_constraint
            else None
        ) or "the requested time period"
        return EvidenceResult(
            status=EvidenceStatus.INSUFFICIENT,
            evidence_directive=f"No timeline events found for {time_phrase}.",
        )
    elif target.temporal_scope in ("current", TemporalScope.CURRENT):
        return EvidenceResult(
            status=EvidenceStatus.INSUFFICIENT,
            evidence_directive="Current timeline events are not recorded.",
        )
    elif target.temporal_scope in ("historical", TemporalScope.HISTORICAL):
        return EvidenceResult(
            status=EvidenceStatus.INSUFFICIENT,
            evidence_directive="Historical timeline events are not recorded.",
        )
    return EvidenceResult(
        status=EvidenceStatus.INSUFFICIENT,
        evidence_directive="Timeline events are not recorded.",
    )


def _filter_timeline_temporal(
    target: InquiryTarget,
    events: list[HealthEvent],
) -> list[HealthEvent]:
    """Filter timeline events by categorical or interval temporal constraint."""
    scope = target.temporal_scope
    if scope in ("interval", TemporalScope.INTERVAL):
        constraint = target.temporal_constraint
        if constraint and constraint.start_date and constraint.end_date:
            filtered = []
            for e in events:
                ed = _parse_event_date(e.event_date)
                if ed and constraint.start_date <= ed <= constraint.end_date:
                    filtered.append(e)
            return filtered
        return list(events)
    elif scope in ("current", TemporalScope.CURRENT):
        return [e for e in events if e.event_state == "current"]
    elif scope in ("historical", TemporalScope.HISTORICAL):
        return [e for e in events if e.event_state == "historical"]
    return list(events)


def _resolve_timeline_superlatives(
    target: InquiryTarget,
    records: list[TimelineEventEvidence],
) -> list[TimelineEventEvidence] | EvidenceResult:
    """Resolves LATEST / FIRST clinical superlatives over timeline events.

    Disqualifies DOCUMENT_UPLOADED and clinically undated events.
    Orders tied events on the winning date deterministically by record.id ASC.
    Returns EvidenceResult with PARTIALLY_SUFFICIENT for undated superlative evidence.
    """
    if not (
        target.temporal_constraint
        and target.temporal_constraint.superlative
        in (SuperlativeType.LATEST, SuperlativeType.FIRST)
    ):
        return records

    superlative = target.temporal_constraint.superlative
    superlative_value = superlative.value

    # Filter out DOCUMENT_UPLOADED and clinically undated events
    dated_records: list[tuple[date, TimelineEventEvidence]] = []
    for r in records:
        if r.event_type == "DOCUMENT_UPLOADED":
            continue
        parsed_d = _parse_event_date(r.event_date)
        if parsed_d is not None:
            dated_records.append((parsed_d, r))

    if not dated_records:
        if target.target_entity:
            directive = (
                f"Records for {target.target_entity} were found, but lack "
                f"documented clinical dates to verify which is the "
                f"{superlative_value}."
            )
        else:
            directive = (
                f"Timeline events were found, but lack documented clinical dates "
                f"to verify which is the {superlative_value}."
            )
        return EvidenceResult(
            status=EvidenceStatus.PARTIALLY_SUFFICIENT,
            matched_records=records,
            temporal_interpretation=target.temporal_scope,
            evidence_directive=directive,
        )

    # Determine winning date
    if superlative == SuperlativeType.LATEST:
        winning_date = max(d for d, _ in dated_records)
    else:  # FIRST
        winning_date = min(d for d, _ in dated_records)

    # Retain all events on winning date and sort deterministically by record.id ASC
    winning_records = [r for d, r in dated_records if d == winning_date]
    winning_records.sort(key=lambda r: r.id)
    return winning_records


def evaluate_timeline_evidence(
    target: InquiryTarget,
    context: Any,
) -> EvidenceResult:
    """Deterministic evaluation of timeline events against an InquiryTarget.

    Adheres strictly to the M5 7-case truth table and M6 superlative contracts.
    """
    if isinstance(context, (list, tuple)):
        events = list(context)
    else:
        events = getattr(context, "recent_timeline_events", [])
    if not events:
        return _timeline_empty_directive(target)

    if target.question_intent == "COMPARISON":
        relevant_events = [
            TimelineEventEvidence(**e.model_dump())
            if not isinstance(e, TimelineEventEvidence)
            else e
            for e in events
            if getattr(e, "event_type", None) != "DOCUMENT_UPLOADED"
            and _candidate_is_relevant(e, target)
        ]
        return evaluate_longitudinal_trajectory(
            structured_candidates=relevant_events,
            document_candidates=[],
            target=target,
        )

    # 1. Entity Qualification
    entity_lower = (
        target.target_entity.lower().strip() if target.target_entity else None
    )
    qualified_events: list[HealthEvent] = []
    if entity_lower:
        for e in events:
            title_match = entity_lower in e.title.lower()
            desc_match = bool(e.description and entity_lower in e.description.lower())
            if title_match or desc_match:
                qualified_events.append(e)

        if not qualified_events:
            return EvidenceResult(
                status=EvidenceStatus.INSUFFICIENT,
                evidence_directive=(
                    f"No timeline events were recorded matching: "
                    f"{target.target_entity}."
                ),
            )
    else:
        qualified_events = list(events)

    # 2. Temporal Filtering (INTERVAL, CURRENT, HISTORICAL, ALL)
    surviving_events = _filter_timeline_temporal(target, qualified_events)
    if not surviving_events:
        return _timeline_temporal_empty_directive(target)

    # 3. Convert surviving HealthEvent instances to TimelineEventEvidence
    wrapped_records = [
        TimelineEventEvidence(**e.model_dump()) for e in surviving_events
    ]

    # 4. Superlative Extremity Resolution (LATEST / FIRST)
    resolved_records = _resolve_timeline_superlatives(target, wrapped_records)
    if isinstance(resolved_records, EvidenceResult):
        return resolved_records

    # 5. Attribute Verification
    if target.requested_attributes:
        matched_fields = []
        missing_fields = []
        for attr in target.requested_attributes:
            attr_found = False
            for r in resolved_records:
                search_texts = [t for t in (r.title, r.description) if t]
                for text in search_texts:
                    if _evaluate_attribute_lexicon(attr, text) or _keyword_present(
                        attr.lower(), text.lower()
                    ):
                        attr_found = True
                        break
                if attr_found:
                    break
            if attr_found:
                matched_fields.append(attr)
            else:
                missing_fields.append(attr)

        human_missing = [HUMAN_ATTRIBUTE_LABELS.get(a, a) for a in missing_fields]
        human_missing_str = ", ".join(human_missing)

        if entity_lower:
            if missing_fields:
                return EvidenceResult(
                    status=EvidenceStatus.PARTIALLY_SUFFICIENT,
                    matched_records=resolved_records,
                    matched_fields=matched_fields,
                    missing_fields=missing_fields,
                    temporal_interpretation=target.temporal_scope,
                    evidence_directive=(
                        f"{target.target_entity} is recorded on your timeline, "
                        f"but not found: {human_missing_str}."
                    ),
                )
            return EvidenceResult(
                status=EvidenceStatus.SUFFICIENT,
                matched_records=resolved_records,
                matched_fields=matched_fields,
                missing_fields=[],
                temporal_interpretation=target.temporal_scope,
                evidence_directive=(
                    "All requested information is recorded on your timeline."
                ),
            )
        else:
            # Attribute-only query
            if not matched_fields:
                return EvidenceResult(
                    status=EvidenceStatus.INSUFFICIENT,
                    missing_fields=missing_fields,
                    temporal_interpretation=target.temporal_scope,
                    evidence_directive=(
                        f"No timeline events contain a record of: {human_missing_str}."
                    ),
                )
            elif missing_fields:
                return EvidenceResult(
                    status=EvidenceStatus.PARTIALLY_SUFFICIENT,
                    matched_records=resolved_records,
                    matched_fields=matched_fields,
                    missing_fields=missing_fields,
                    temporal_interpretation=target.temporal_scope,
                    evidence_directive=(
                        "Information partially found on your timeline. "
                        f"Not found: {human_missing_str}."
                    ),
                )
            return EvidenceResult(
                status=EvidenceStatus.SUFFICIENT,
                matched_records=resolved_records,
                matched_fields=matched_fields,
                temporal_interpretation=target.temporal_scope,
                evidence_directive=(
                    "All requested information is recorded on your timeline."
                ),
            )

    # 6. Entity-only or Generic query
    if entity_lower:
        return EvidenceResult(
            status=EvidenceStatus.SUFFICIENT,
            matched_records=resolved_records,
            temporal_interpretation=target.temporal_scope,
            evidence_directive="Relevant records found on your timeline.",
        )

    # Generic timeline query (no entity, no attributes)
    return EvidenceResult(
        status=EvidenceStatus.SUFFICIENT,
        matched_records=resolved_records,
        temporal_interpretation=target.temporal_scope,
        evidence_directive="Timeline events are available.",
    )


def _evaluate_single_structured_domain(
    domain: str,
    target: InquiryTarget,
    context: StructuredHealthContext,
) -> EvidenceResult:
    """Evaluates query against a single structured relational domain.

    Preserves exact M1-M5 baseline evaluation behavior.
    """
    if not domain or not hasattr(context, domain):
        return EvidenceResult(
            status=EvidenceStatus.INSUFFICIENT,
            evidence_directive="Domain not recorded in health context.",
        )

    records_data = getattr(context, domain)

    if target.question_intent == "COMPARISON":
        records = (
            records_data
            if isinstance(records_data, list)
            else ([records_data] if records_data else [])
        )
        relevant_records = [r for r in records if _candidate_is_relevant(r, target)]
        return evaluate_longitudinal_trajectory(
            structured_candidates=relevant_records,
            document_candidates=[],
            target=target,
        )

    if isinstance(records_data, list):
        if not records_data:
            return EvidenceResult(
                status=EvidenceStatus.INSUFFICIENT,
                evidence_directive=f"{domain} are not recorded.",
            )

        # 1. Entity Matching
        records = records_data
        if target.target_entity:
            matched = []
            entity_lower = target.target_entity.lower()
            for r in records:
                name_val = getattr(
                    r, "name", getattr(r, "allergen", getattr(r, "description", ""))
                )
                if name_val and entity_lower in name_val.lower():
                    matched.append(r)
            records = matched
            if not records:
                return EvidenceResult(
                    status=EvidenceStatus.INSUFFICIENT,
                    evidence_directive=(
                        f"{target.target_entity} is not recorded in {domain}."
                    ),
                )

        # 2. Temporal Filtering
        if target.temporal_scope == "current":
            filtered = []
            for r in records:
                if domain == "allergies":
                    filtered.append(r)
                elif hasattr(r, "status") and getattr(r, "status") in (
                    "active",
                    "current",
                ):
                    filtered.append(r)
                elif hasattr(r, "ended_at") and not getattr(r, "ended_at"):
                    filtered.append(r)
            records = filtered
            if not records:
                return EvidenceResult(
                    status=EvidenceStatus.INSUFFICIENT,
                    evidence_directive=(
                        "Current records for this entity are not recorded."
                    ),
                )
        elif target.temporal_scope == "historical":
            filtered = []
            for r in records:
                if domain == "allergies":
                    filtered.append(r)
                elif hasattr(r, "status") and getattr(r, "status") not in (
                    "active",
                    "current",
                ):
                    filtered.append(r)
                elif hasattr(r, "ended_at") and getattr(r, "ended_at"):
                    filtered.append(r)
            records = filtered
            if not records:
                return EvidenceResult(
                    status=EvidenceStatus.INSUFFICIENT,
                    evidence_directive=(
                        "Historical records for this entity are not recorded."
                    ),
                )
        elif target.temporal_scope == "interval" and target.temporal_constraint:
            constraint = target.temporal_constraint
            if constraint.start_date and constraint.end_date:
                filtered = []
                for r in records:
                    if domain == "allergies":
                        time_phrase = (
                            constraint.raw_expression or "the requested time period"
                        )
                        entity_name = target.target_entity or "this substance"
                        return EvidenceResult(
                            status=EvidenceStatus.INSUFFICIENT,
                            evidence_directive=(
                                f"An allergy to {entity_name} is on record, "
                                f"but its presence during {time_phrase} is unverified."
                            ),
                        )

                    started_at = getattr(r, "started_at", None)
                    if not started_at:
                        continue

                    if isinstance(started_at, datetime):
                        started_at = started_at.date()

                    ended_at = getattr(r, "ended_at", None)
                    if isinstance(ended_at, datetime):
                        ended_at = ended_at.date()

                    if started_at <= constraint.end_date:
                        if ended_at and ended_at >= constraint.start_date:
                            filtered.append(r)
                        elif ended_at is None:
                            if domain == "symptoms":
                                filtered.append(r)
                            else:
                                status = getattr(r, "status", None)
                                if status in ("active", "current"):
                                    filtered.append(r)

                records = filtered
                if not records:
                    time_phrase = (
                        constraint.raw_expression or "the requested time period"
                    )
                    return EvidenceResult(
                        status=EvidenceStatus.INSUFFICIENT,
                        evidence_directive=(f"No records found for {time_phrase}."),
                    )
    else:
        # Single record (e.g., profile)
        if not records_data:
            return EvidenceResult(
                status=EvidenceStatus.INSUFFICIENT,
                evidence_directive="Profile data is not recorded.",
            )
        records = [records_data]

    # 3. Attribute Presence Check
    missing_fields = []
    matched_fields = []
    if target.requested_attributes:
        for attr in target.requested_attributes:
            attr_found = False
            for r in records:
                if hasattr(r, attr) and getattr(r, attr) is not None:
                    attr_found = True
                    break
            if attr_found:
                matched_fields.append(attr)
            else:
                missing_fields.append(attr)

        if missing_fields:
            return EvidenceResult(
                status=EvidenceStatus.PARTIALLY_SUFFICIENT,
                matched_records=records,
                matched_fields=matched_fields,
                missing_fields=missing_fields,
                temporal_interpretation=target.temporal_scope,
                evidence_directive=(
                    f"Information partially available. Not recorded: "
                    f"{', '.join(missing_fields)}."
                ),
            )
        else:
            return EvidenceResult(
                status=EvidenceStatus.SUFFICIENT,
                matched_records=records,
                matched_fields=matched_fields,
                temporal_interpretation=target.temporal_scope,
                evidence_directive="All requested information is recorded.",
            )
    else:
        return EvidenceResult(
            status=EvidenceStatus.SUFFICIENT,
            matched_records=records,
            temporal_interpretation=target.temporal_scope,
            evidence_directive="Relevant records found.",
        )


def _pool_structured_evidence(
    target: InquiryTarget,
    domain_results: list[EvidenceResult],
) -> EvidenceResult:
    """Pools evidence results across candidate structured domains.

    Strictly adheres to the M5 truth table and Rule F caveat propagation.
    """
    # 1. Record Pooling:
    pooled_records = []
    for res in domain_results:
        if res.status != EvidenceStatus.INSUFFICIENT:
            pooled_records.extend(res.matched_records)

    # 2. Attribute Pooling:
    pooled_matched_set = set()
    for res in domain_results:
        if res.status != EvidenceStatus.INSUFFICIENT:
            pooled_matched_set.update(res.matched_fields)

    matched_fields_list = [
        a for a in target.requested_attributes if a in pooled_matched_set
    ]
    missing_fields_list = [
        a for a in target.requested_attributes if a not in pooled_matched_set
    ]

    entity_lower = (
        target.target_entity.lower().strip() if target.target_entity else None
    )

    # Compute standard M5 pooled status AND corresponding base_directive
    # across all reachable branches:
    if target.requested_attributes:
        human_missing = [HUMAN_ATTRIBUTE_LABELS.get(a, a) for a in missing_fields_list]
        human_missing_str = ", ".join(human_missing)
        if entity_lower:
            if not pooled_records:
                pooled_status = EvidenceStatus.INSUFFICIENT
                base_directive = f"No records found matching: {target.target_entity}."
            elif missing_fields_list:
                pooled_status = EvidenceStatus.PARTIALLY_SUFFICIENT
                base_directive = (
                    f"{target.target_entity} is recorded, but not found in records: "
                    f"{human_missing_str}."
                )
            else:
                pooled_status = EvidenceStatus.SUFFICIENT
                base_directive = (
                    "All requested information is recorded in your health context."
                )
        else:
            # Attribute-only query
            if not matched_fields_list:
                pooled_status = EvidenceStatus.INSUFFICIENT
                base_directive = f"No records contain: {human_missing_str}."
            elif missing_fields_list:
                pooled_status = EvidenceStatus.PARTIALLY_SUFFICIENT
                base_directive = (
                    f"Information partially found. Not found: {human_missing_str}."
                )
            else:
                pooled_status = EvidenceStatus.SUFFICIENT
                base_directive = (
                    "All requested information is recorded in your health context."
                )
    elif entity_lower:
        if pooled_records:
            pooled_status = EvidenceStatus.SUFFICIENT
            base_directive = f"Relevant records found for: {target.target_entity}."
        else:
            pooled_status = EvidenceStatus.INSUFFICIENT
            base_directive = f"No records found matching: {target.target_entity}."
    else:
        # Generic query
        if pooled_records:
            pooled_status = EvidenceStatus.SUFFICIENT
            base_directive = "Health records are available."
        else:
            pooled_status = EvidenceStatus.INSUFFICIENT
            base_directive = "No health records found in context."

    # Rule F: Non-Attribute Caveat Invariant:
    non_attr_caveats = [
        res
        for res in domain_results
        if res.status == EvidenceStatus.PARTIALLY_SUFFICIENT and not res.missing_fields
    ]

    if non_attr_caveats and pooled_status == EvidenceStatus.SUFFICIENT:
        pooled_status = EvidenceStatus.PARTIALLY_SUFFICIENT

    # Directives aggregation in deterministic candidate-domain order:
    directives: list[str] = []
    if missing_fields_list:
        human_missing = [HUMAN_ATTRIBUTE_LABELS.get(a, a) for a in missing_fields_list]
        human_missing_str = ", ".join(human_missing)
        if target.target_entity:
            directives.append(
                f"{target.target_entity} is recorded, but not found in records: "
                f"{human_missing_str}."
            )
        else:
            directives.append(
                f"Information partially found. Not found: {human_missing_str}."
            )

    for caveat in non_attr_caveats:
        if caveat.evidence_directive and caveat.evidence_directive not in directives:
            directives.append(caveat.evidence_directive)

    final_directive = " ".join(directives) if directives else base_directive

    return EvidenceResult(
        status=pooled_status,
        matched_records=pooled_records,
        matched_fields=matched_fields_list,
        missing_fields=missing_fields_list,
        temporal_interpretation=target.temporal_scope,
        evidence_directive=final_directive,
    )


def evaluate_evidence(
    target: InquiryTarget, context: StructuredHealthContext
) -> EvidenceResult:
    """Evaluates query against context across all candidate structured domains.

    Dispatches to evaluate_timeline_evidence when 'timeline' is present.
    Pools multi-domain evidence while strictly preserving the M5 truth table
    and Rule F.
    """
    candidate_domains = (
        target.candidate_structured_domains
        if target.candidate_structured_domains
        else ([target.target_domain] if target.target_domain else [])
    )

    if not candidate_domains:
        return EvidenceResult(
            status=EvidenceStatus.INSUFFICIENT,
            evidence_directive="Domain not recorded in health context.",
        )

    if target.question_intent == "COMPARISON":
        records = []
        for domain in candidate_domains:
            if domain == "timeline":
                evs = getattr(context, "recent_timeline_events", [])
                records.extend(
                    [
                        TimelineEventEvidence(**e.model_dump())
                        if not isinstance(e, TimelineEventEvidence)
                        else e
                        for e in evs
                        if getattr(e, "event_type", None) != "DOCUMENT_UPLOADED"
                        and _candidate_is_relevant(e, target)
                    ]
                )
            elif hasattr(context, domain):
                dom_recs = getattr(context, domain)
                if isinstance(dom_recs, list):
                    records.extend(
                        [r for r in dom_recs if _candidate_is_relevant(r, target)]
                    )
                elif dom_recs and _candidate_is_relevant(dom_recs, target):
                    records.append(dom_recs)
        return evaluate_longitudinal_trajectory(
            structured_candidates=records,
            document_candidates=[],
            target=target,
        )

    # 1. Single-domain execution (preserves exact M1-M5 baseline behavior)
    if len(candidate_domains) == 1:
        domain = candidate_domains[0]
        if domain == "timeline":
            return evaluate_timeline_evidence(target, context)
        return _evaluate_single_structured_domain(domain, target, context)

    # 2. Multi-domain structured execution (e.g. ["timeline", "conditions"])
    domain_results: list[EvidenceResult] = []
    for domain in candidate_domains:
        if domain == "timeline":
            res = evaluate_timeline_evidence(target, context)
            domain_results.append(res)
        elif hasattr(context, domain):
            res = _evaluate_single_structured_domain(domain, target, context)
            domain_results.append(res)

    if not domain_results:
        return EvidenceResult(
            status=EvidenceStatus.INSUFFICIENT,
            evidence_directive="No candidate domains recorded in health context.",
        )

    # Pool evidence preserving M5 sufficiency rules and Rule F
    return _pool_structured_evidence(target, domain_results)


# ---------------------------------------------------------------------------
# Document evidence evaluation (M3 Slice 4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DocumentExtractionEvidence:
    """A value-object carrying document extraction content for evidence evaluation.

    This is a pure data container; it does NOT reference the ORM model
    directly.  Callers are responsible for building this from the persisted
    DocumentExtraction row and the associated MedicalDocument patient_id.

    Fields
    ------
    document_id:
        Stable identity of the source MedicalDocument.  Never mutated here.
    patient_id:
        Tenant scope — must match the requesting patient_id passed to
        ``evaluate_document_evidence``.  Enforced inside the function.
    extraction_status:
        One of COMPLETED / FAILED / UNSUPPORTED (from Slice 1 contract).
    extracted_text:
        The normalised, sanitised document text (may be None for FAILED /
        UNSUPPORTED records).
    document_date:
        Optional date from the source MedicalDocument.  Used only for
        temporal labelling in the directive — no selection logic here.
    """

    document_id: uuid.UUID
    patient_id: uuid.UUID
    extraction_status: str  # "COMPLETED" | "FAILED" | "UNSUPPORTED"
    extracted_text: Optional[str]
    document_date: Optional[date] = None


def evaluate_document_evidence(
    target: InquiryTarget,
    evidence: DocumentExtractionEvidence,
    requesting_patient_id: uuid.UUID,
) -> EvidenceResult:
    """
    Deterministic evaluation of document extraction evidence against an
    InquiryTarget.

    Tenant isolation
    ----------------
    ``requesting_patient_id`` must match ``evidence.patient_id``.  A mismatch
    returns INSUFFICIENT without exposing any content — the directive does NOT
    reveal that the document exists, preserving privacy.

    Extraction state gates
    ----------------------
    FAILED and UNSUPPORTED extractions carry no usable text and always produce
    INSUFFICIENT.  No negative diagnostic claim is ever emitted.

    Evidence scoring
    ----------------
    COMPLETED extractions are evaluated by keyword-presence matching:

    * All requested attributes (``target.requested_attributes``) are searched
      for in the extracted text.  Missing attributes -> PARTIALLY_SUFFICIENT.
    * When no attributes are requested, the topical entity
      (``target.target_entity``) is searched.  A match -> SUFFICIENT.
    * No match at all -> INSUFFICIENT.

    Safe absence
    ------------
    Absence directives state that a fact was not found in the document.
    They do NOT assert that the patient lacks the condition/value, and they
    do NOT infer diagnostic significance.
    """
    # ------------------------------------------------------------------
    # 1. Tenant isolation gate — silent INSUFFICIENT on mismatch.
    # ------------------------------------------------------------------
    if evidence.patient_id != requesting_patient_id:
        return EvidenceResult(
            status=EvidenceStatus.INSUFFICIENT,
            evidence_directive="The requested document is not recorded.",
        )

    # ------------------------------------------------------------------
    # 2. Extraction-state gate.
    # ------------------------------------------------------------------
    if evidence.extraction_status != "COMPLETED" or not evidence.extracted_text:
        status_label = evidence.extraction_status.lower()  # failed / unsupported
        return EvidenceResult(
            status=EvidenceStatus.INSUFFICIENT,
            evidence_directive=(
                f"Document text could not be extracted ({status_label}); "
                "no content is available."
            ),
        )

    text_lower = evidence.extracted_text.lower()

    # ------------------------------------------------------------------
    # 3. Attribute-level matching.
    # ------------------------------------------------------------------
    if target.requested_attributes:
        matched: list[str] = []
        missing: list[str] = []
        for attr in target.requested_attributes:
            if _keyword_present(attr.lower(), text_lower):
                matched.append(attr)
            else:
                missing.append(attr)

        if missing and matched:
            return EvidenceResult(
                status=EvidenceStatus.PARTIALLY_SUFFICIENT,
                matched_fields=matched,
                missing_fields=missing,
                temporal_interpretation=target.temporal_scope,
                evidence_directive=(
                    f"Information partially found in the uploaded document. "
                    f"Not found in document: {', '.join(missing)}."
                ),
            )
        elif missing and not matched:
            # None of the requested attributes present.
            return EvidenceResult(
                status=EvidenceStatus.INSUFFICIENT,
                missing_fields=missing,
                temporal_interpretation=target.temporal_scope,
                evidence_directive=_absent_directive(missing, evidence.document_date),
            )
        else:
            return EvidenceResult(
                status=EvidenceStatus.SUFFICIENT,
                matched_fields=matched,
                temporal_interpretation=target.temporal_scope,
                evidence_directive=(
                    "All requested information was found in the uploaded document."
                ),
            )

    # ------------------------------------------------------------------
    # 4. Topical / entity-level matching (no explicit attributes).
    # ------------------------------------------------------------------
    topic = (target.target_entity or "").lower().strip()
    if topic and _keyword_present(topic, text_lower):
        return EvidenceResult(
            status=EvidenceStatus.SUFFICIENT,
            temporal_interpretation=target.temporal_scope,
            evidence_directive="Relevant content was found in the uploaded document.",
        )
    elif topic:
        return EvidenceResult(
            status=EvidenceStatus.INSUFFICIENT,
            temporal_interpretation=target.temporal_scope,
            evidence_directive=_absent_directive([topic], evidence.document_date),
        )
    else:
        # No attributes and no entity — generic document present.
        return EvidenceResult(
            status=EvidenceStatus.SUFFICIENT,
            temporal_interpretation=target.temporal_scope,
            evidence_directive="Document content is available.",
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _keyword_present(keyword: str, text_lower: str) -> bool:
    """Return True if ``keyword`` appears as a whole-word match in ``text_lower``.

    Word-boundary matching avoids false positives where a short token is a
    sub-string of a longer term (e.g. ``"pt"`` inside ``"patient"``).  For
    multi-word phrases the substring match is sufficient because word
    boundaries are implicitly maintained by surrounding whitespace.
    """
    if " " in keyword:
        # Multi-word phrase: simple substring is sufficient.
        return keyword in text_lower
    # Single token: require word boundary so "alt" doesn't match "default".
    pattern = r"\b" + re.escape(keyword) + r"\b"
    return bool(re.search(pattern, text_lower))


def _evaluate_attribute_lexicon(attr: str, text: str) -> bool:
    """Evaluate unstructured passage text against the S3 contextual lexicon."""
    text = text.lower()

    if attr == "physician_name":
        p1 = (
            r"\b(prescribing (?:doctor|physician)|attending (?:physician|doctor)|"
            r"prescribed by|ordered by|signed by|physician|provider|prescriber)\s*:\s*"
            r"(?:(?:dr\.?\s+|doctor\s+)[a-z]+(?:\s+[a-z]+){0,2}|"
            r"[a-z]+(?:\s+[a-z]+){0,2},\s*(?:m\.?d\.?|d\.?o\.?|n\.?p\.?|p\.?a\.?-c)|"
            r"(?!follow\s*up\b|patient\s*seen\b|recommended\b|advised\b|see\s*below\b|"
            r"none\b|n\/?a\b|pending\b|refill\b)[a-z]+(?:\s+[a-z]+){0,2}"
            r"(?:,\s*(?:m\.?d\.?|d\.?o\.?|n\.?p\.?|p\.?a\.?-c))?)\b"
        )
        p2 = (
            r"\b(?:dr\.?|doctor)\s+(?!advised\b|recommended\b|instructed\b|noted\b)"
            r"[a-z]+(?:\s+[a-z]+){0,2}\b"
        )
        p3 = (
            r"\b[a-z]+(?:\s+[a-z]+){1,2},\s*(?:m\.?d\.?|d\.?o\.?|n\.?p\.?|p\.?a\.?-c)\b"
        )
        return bool(re.search(p1, text) or re.search(p2, text) or re.search(p3, text))

    elif attr == "dosage":
        p1 = (
            r"\b(dose|dosage|strength)\s*:?\s*\d+(?:\.\d+)?\s*"
            r"(?:mg|mcg|micrograms?|milligrams?|g|grams?|ml|milliliters?|units?)"
            r"(?:\s+(?:once daily|twice daily|daily|bid|tid|qid|"
            r"at bedtime|every \d+ hours?|q\d+h))?\b"
        )
        p2 = (
            r"\btake\s+\d+(?:\.\d+)?\s*(?:tablet|tablets|capsule|capsules|pill|pills)?\s*"
            r"(?:\(\s*\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml)\s*\))?\s*(?:by mouth\s*)?"
            r"(?:once daily|twice daily|daily|bid|tid|qid|at bedtime|"
            r"every \d+ hours?|q\d+h)?\b"
        )
        p3 = (
            r"\b\d+(?:\.\d+)?\s*"
            r"(?:mg|mcg|micrograms?|milligrams?|g|grams?|ml|milliliters?|units?)\s+"
            r"(?:once daily|twice daily|three times (?:a|per) day|"
            r"four times (?:a|per) day|daily|bid|tid|qid|"
            r"at bedtime|in the morning|every other day|"
            r"every \d+ hours?|q\d+h|by mouth|orally|po|prn|as needed)\b"
        )
        p4 = (
            r"\b(?:tablet|tablets|capsule|capsules|pill|pills)\s*\(\s*\d+(?:\.\d+)?\s*"
            r"(?:mg|mcg|g|ml)\s*\)\b"
        )
        p5 = (
            r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml)\s+(?:tablet|tablets|capsule|capsules|pill|pills)\s+"
            r"(?:once daily|twice daily|daily|bid|tid|qid|at bedtime|by mouth|po)\b"
        )
        return bool(
            re.search(p1, text)
            or re.search(p2, text)
            or re.search(p3, text)
            or re.search(p4, text)
            or re.search(p5, text)
        )

    elif attr == "clinic":
        p1 = (
            r"\b(clinic|facility|hospital|location|practice)\s*:\s*"
            r"(?!none\b|n\/?a\b|see\s*below\b|pending\b)[a-z0-9]+(?:\s+[a-z0-9]+){0,4}\b"
        )
        p2 = (
            r"\b[a-z0-9]+(?:\s+[a-z0-9]+){0,2}\s+"
            r"(?!the\b|this\b|that\b|a\b|an\b|my\b|our\b|your\b|local\b|any\b|each\b"
            r"|another\b|at\b|to\b|in\b|from\b)"
            r"[a-z0-9]+\s+(?:medical center|health center|hospital|clinic|infirmary"
            r"|family practice|health system|institute)\b"
        )
        p3 = (
            r"\b(seen at|visited|admitted to|discharged from|treated at|referred to"
            r"|return to)\s+"
            r"(?!(?:the|this|that|a|an|our|your|local|another|each)\s+"
            r"(?:clinic|hospital|facility|practice|infirmary)\b)"
            r"(?:[a-z0-9]+(?:\s+[a-z0-9]+){0,3}\s+)?"
            r"(?:medical center|health center|hospital|clinic|infirmary"
            r"|family practice|health system|institute)\b"
        )
        return bool(re.search(p1, text) or re.search(p2, text) or re.search(p3, text))

    elif attr == "consultation_notes":
        p1 = (
            r"\b(assessment\s*(and|&)\s*plan|assessment|plan|impression|"
            r"recommendations?|discharge instructions?"
            r"|clinical advice|advice|doctor'?s? notes?|consultation notes?|"
            r"notes?|conclusion)\s*:"
        )
        p2 = (
            r"\b(doctor|physician|clinician)\s+(advised|recommended|instructed|noted)\b"
        )
        return bool(re.search(p1, text) or re.search(p2, text))

    elif attr == "contact_number":
        p1 = (
            r"\b(phone|tel|telephone|cell|mobile|office|clinic phone|contact|fax)\s*"
            r"(#|no\.?|number)?\s*:\s*"
            r"(?:\+?\d{1,4}[-.\s]*)?(?:\(?\d{1,5}\)?[-.\s]*)?\d{2,5}[-.\s]?\d{2,5}"
            r"(?:[-.\s]?\d{1,5})?\b"
        )
        p2 = (
            r"\b(call|contact|reach(?: out)?)(?:\s+us)?\s+at\s+"
            r"(?:\+?\d{1,4}[-.\s]*)?(?:\(?\d{1,5}\)?[-.\s]*)?\d{2,5}[-.\s]?\d{2,5}(?:[-.\s]?\d{1,5})?\b"
        )
        matches = list(re.finditer(p1, text)) + list(re.finditer(p2, text))
        for match in matches:
            matched_str = match.group(0)
            number_part = matched_str
            if ":" in matched_str:
                number_part = matched_str.split(":", 1)[1]
            elif " at " in matched_str:
                number_part = matched_str.split(" at ", 1)[1]
            digits = re.sub(r"[-.()\s+]", "", number_part)
            if 7 <= len(digits) <= 15:
                return True
        return False

    elif attr == "frequency":
        p1 = (
            r"\b(once(?: a| per)? day|twice(?: a| per)? day|three times (?:a|per) day|"
            r"four times (?:a|per) day|every \d+ hours?|q\d+h|bid|tid|qid|daily|"
            r"at bedtime|in the morning|every other day|as needed|prn)\b"
        )
        p2 = r"\b(frequency|schedule)\s*:\s*[a-z0-9]"
        return bool(re.search(p1, text) or re.search(p2, text))

    elif attr == "status":
        p1 = (
            r"\b(active medication|discontinued|condition(?: is)? resolved|inactive|"
            r"current medication|stopped taking|completed course)\b"
        )
        p2 = (
            r"\b(status|condition)\s*:\s*"
            r"(active|current|resolved|chronic|discontinued|inactive)\b"
        )
        return bool(re.search(p1, text) or re.search(p2, text))

    elif attr == "blood_group":
        p1 = (
            r"\b(blood (group|type)|abo\/?rh)\s*:\s*"
            r"(a|b|ab|o)\s*(\+|-|pos|neg|positive|negative)?\b"
        )
        p2 = r"\bblood (group|type)\s+(a|b|ab|o)\s*(positive|negative|pos|neg|\+|-)?\b"
        p3 = r"\btype\s+(a|b|ab|o)\s*(positive|negative|pos|neg|\+|-)\b"
        p4 = r"\b(a|b|ab|o)[\+\-](?!\w)"
        p5 = (
            r"(?<!\bgrade\s)(?<!\bhepatitis\s)\b(a|b|ab|o)\s+"
            r"(positive|negative|pos|neg)\b"
        )
        return bool(
            re.search(p1, text)
            or re.search(p2, text)
            or re.search(p3, text)
            or re.search(p4, text)
            or re.search(p5, text)
        )

    elif attr.lower() in ("systolic", "systolic blood pressure"):
        return bool(
            re.search(r"\b(systolic|sys)\b", text)
            or re.search(r"\b\d{2,3}\s*/\s*\d{2,3}\b", text)
        )

    elif attr.lower() in ("diastolic", "diastolic blood pressure"):
        return bool(
            re.search(r"\b(diastolic|dia)\b", text)
            or re.search(r"\b\d{2,3}\s*/\s*\d{2,3}\b", text)
        )

    elif attr.lower() == "pulse":
        return bool(re.search(r"\b(pulse|heart rate|bpm|hr)\b", text))

    elif attr.lower() == "hdl":
        return bool(re.search(r"\bhdl\b", text))

    elif attr.lower() == "ldl":
        return bool(re.search(r"\bldl\b", text))

    elif attr.lower() == "iron":
        return bool(re.search(r"\biron\b", text))

    elif attr.lower() == "ferritin":
        return bool(re.search(r"\bferritin\b", text))

    elif attr.lower() == "trigger":
        return bool(re.search(r"\b(trigger|triggers|triggered)\b", text))

    return _keyword_present(attr.lower(), text)


def _absent_directive(terms: list[str], document_date: Optional[date]) -> str:
    """Produce a safe-absence directive that describes what was NOT found in
    the document — without making any diagnostic inference.

    The directive explicitly says the fact was not FOUND IN THE DOCUMENT,
    which is categorically different from asserting that the patient lacks
    it.
    """
    date_part = f" (dated {document_date.isoformat()})" if document_date else ""
    term_list = ", ".join(terms)
    return (
        f"The uploaded document{date_part} does not contain a record of: {term_list}."
    )


# ---------------------------------------------------------------------------
# Passage-level evidence evaluation (M4 Slice 5)
# ---------------------------------------------------------------------------


def _absent_records_directive(terms: list[str]) -> str:
    """Produce a safe corpus-level absence directive for passage evidence.

    Used by ``evaluate_passage_evidence`` when queried facts are not found
    across all retrieved passages.  States that the patient's uploaded records
    were searched without a match — categorically different from asserting
    that the patient lacks the clinical fact.

    Unlike the M3 ``_absent_directive`` (scoped to a single named document),
    this function describes a corpus-level absence across all retrieved passages
    without referencing a specific document date.
    """
    term_list = ", ".join(terms)
    return (
        f"Your uploaded records were searched, but do not contain "
        f"a record of: {term_list}."
    )


def evaluate_passage_evidence(
    target: InquiryTarget,
    retrieval_result: Any,
    requesting_patient_id: Optional[uuid.UUID] = None,
) -> EvidenceResult:
    """Evaluate passage-level evidence against an InquiryTarget.

    This is the M4 S5 counterpart to ``evaluate_document_evidence`` (M3).
    It inspects whether candidate passages retrieved by
    ``HybridRetrievalEngine`` corroborate the clinical entities and
    attributes requested by the patient.

    Tenant isolation
    ----------------
    ``requesting_patient_id`` is verified against both
    ``retrieval_result.patient_id`` and every individual
    ``RetrievedPassage.patient_id``.  Any mismatch returns INSUFFICIENT
    without exposing content — the directive does NOT reveal whether
    foreign records exist.

    Evidence scoring
    ----------------
    Rule A — ``requested_attributes`` non-empty:
        Attributes are pooled across all candidate passages via whole-word
        boundary matching (``_keyword_present``).

        - SUFFICIENT: every requested attribute corroborated.
        - PARTIALLY_SUFFICIENT: some corroborated, some missing.
        - INSUFFICIENT: zero attributes corroborated.

    Rule B — ``target_entity`` only, no ``requested_attributes``:
        The topical entity is searched across all passages.

        - SUFFICIENT: entity found in at least one passage.
        - INSUFFICIENT: entity absent from all passages.

    Rule C — generic domain query, neither entity nor attributes:
        - SUFFICIENT if any passages were retrieved.
        - INSUFFICIENT if no passages exist.

    No semantic distance threshold is applied.  Qualification is determined
    exclusively by clinical entity and attribute keyword corroboration.

    Missing-fields ordering
    -----------------------
    ``missing_fields`` preserves the exact ordering of
    ``target.requested_attributes`` — not alphabetical or match order.
    """
    if isinstance(retrieval_result, (list, tuple)):
        pid = requesting_patient_id or (
            retrieval_result[0].patient_id if retrieval_result else uuid.uuid4()
        )
        retrieval_result = RetrievalResult(
            patient_id=pid,
            target_domains=(),
            query_text="",
            top_k=len(retrieval_result),
            passages=tuple(retrieval_result),
        )
        if requesting_patient_id is None:
            requesting_patient_id = pid

    # ------------------------------------------------------------------
    # 1. Tenant integrity gate — fail-closed on mismatch.
    # ------------------------------------------------------------------
    if retrieval_result.patient_id != requesting_patient_id:
        logger.warning(
            "Tenant mismatch in evaluate_passage_evidence: "
            "retrieval_result.patient_id != requesting_patient_id"
        )
        return EvidenceResult(
            status=EvidenceStatus.INSUFFICIENT,
            evidence_directive=(
                "Your uploaded records were searched, but do not contain "
                "a record of the requested information."
            ),
        )

    for p in retrieval_result.passages:
        if p.patient_id != requesting_patient_id:
            logger.warning(
                "Tenant mismatch on passage chunk_id=%s",
                str(p.chunk_id),
            )
            return EvidenceResult(
                status=EvidenceStatus.INSUFFICIENT,
                evidence_directive=(
                    "Your uploaded records were searched, but do not contain "
                    "a record of the requested information."
                ),
            )

    # ------------------------------------------------------------------
    # 2. Temporal defense-in-depth and Empty retrieval result gate.
    # ------------------------------------------------------------------
    passages_to_evaluate = []
    if (
        target.temporal_scope == "interval"
        and target.temporal_constraint
        and target.temporal_constraint.start_date
        and target.temporal_constraint.end_date
    ):
        start_date = target.temporal_constraint.start_date
        end_date = target.temporal_constraint.end_date
        for p in retrieval_result.passages:
            if p.document_date and start_date <= p.document_date <= end_date:
                passages_to_evaluate.append(p)
    else:
        passages_to_evaluate = list(retrieval_result.passages)

    if not passages_to_evaluate:
        if target.temporal_scope == "interval" and target.temporal_constraint:
            time_phrase = (
                target.temporal_constraint.raw_expression or "the requested time period"
            )
            directive = f"No document records are available for {time_phrase}."
            if target.requested_attributes:
                missing = list(target.requested_attributes)
                directive = _absent_records_directive(missing) + f" (for {time_phrase})"
            elif target.target_entity:
                directive = (
                    _absent_records_directive([target.target_entity])
                    + f" (for {time_phrase})"
                )
        else:
            if target.requested_attributes:
                missing = list(target.requested_attributes)
                directive = _absent_records_directive(missing)
            elif target.target_entity:
                directive = _absent_records_directive([target.target_entity])
            else:
                directive = "No document records are available for this domain."

        return EvidenceResult(
            status=EvidenceStatus.INSUFFICIENT,
            missing_fields=list(target.requested_attributes)
            if target.requested_attributes
            else [],
            evidence_directive=directive,
        )

    if target.question_intent == "COMPARISON":
        relevant_passages = [
            p for p in passages_to_evaluate if _candidate_is_relevant(p, target)
        ]
        return evaluate_longitudinal_trajectory(
            structured_candidates=[],
            document_candidates=relevant_passages,
            target=target,
        )

    if target.temporal_constraint and target.temporal_constraint.superlative in (
        SuperlativeType.LATEST,
        SuperlativeType.FIRST,
    ):
        superlative = target.temporal_constraint.superlative
        qual_docs = [
            p for p in passages_to_evaluate if _qualifies_for_superlative(p, target)
        ]
        if not qual_docs:
            human_missing = [
                HUMAN_ATTRIBUTE_LABELS.get(a, a) for a in target.requested_attributes
            ]
            directive = (
                _absent_records_directive(human_missing)
                if human_missing
                else _absent_records_directive([target.target_entity or "health"])
            )
            return EvidenceResult(
                status=EvidenceStatus.INSUFFICIENT,
                missing_fields=list(target.requested_attributes)
                if target.requested_attributes
                else [],
                temporal_interpretation="superlative",
                evidence_directive=directive,
            )

        doc_dates = {
            extract_canonical_clinical_date(p)
            for p in qual_docs
            if extract_canonical_clinical_date(p) is not None
        }

        if not doc_dates:
            retained_docs = allocate_superlative_document_passages(
                winning_date=None,
                passages=qual_docs,
                superlative=superlative,
            )
            return EvidenceResult(
                status=EvidenceStatus.PARTIALLY_SUFFICIENT,
                matched_records=[],
                qualified_passages=retained_docs,
                matched_fields=[],
                missing_fields=list(target.requested_attributes)
                if target.requested_attributes
                else [],
                temporal_interpretation="superlative",
                evidence_directive=(
                    f"Identified {target.target_entity or 'health'} records, but "
                    "no verifiable clinical dates were recorded to establish recency."
                ),
            )

        winning_date = (
            max(doc_dates) if superlative == SuperlativeType.LATEST else min(doc_dates)
        )
        retained_docs = allocate_superlative_document_passages(
            winning_date=winning_date,
            passages=qual_docs,
            superlative=superlative,
        )

        full_win_docs = [
            p for p in qual_docs if extract_canonical_clinical_date(p) == winning_date
        ]
        serialized_win_docs = [
            p
            for p in retained_docs
            if extract_canonical_clinical_date(p) == winning_date
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
                full_win_evidence=full_win_docs,
                serialized_win_evidence=serialized_win_docs,
                target=target,
                base_directive=base_directive,
                winning_date=winning_date,
            )
        )

        return EvidenceResult(
            status=status,
            matched_records=[],
            qualified_passages=retained_docs,
            matched_fields=matched_fields,
            missing_fields=missing_fields,
            temporal_interpretation="superlative",
            evidence_directive=directive,
        )

    # ------------------------------------------------------------------
    # Joint Entity + Attribute evaluation
    # ------------------------------------------------------------------
    entity_lower = target.target_entity.lower() if target.target_entity else None

    docs_with_entity = set()
    if entity_lower:
        for p in passages_to_evaluate:
            if _keyword_present(entity_lower, p.chunk_text.lower()):
                docs_with_entity.add(p.document_id)

        if not docs_with_entity:
            # Rule D: Entity absent from all passages
            return EvidenceResult(
                status=EvidenceStatus.INSUFFICIENT,
                evidence_directive=_absent_records_directive([target.target_entity]),
            )

    if target.requested_attributes:
        best_doc_matched_fields: set[str] = set()
        best_doc_qualifying_passages: list[RetrievedPassage] = []
        pooled_matched_fields: set[str] = set()
        pooled_qualifying_passages: list[RetrievedPassage] = []

        docs_passages = defaultdict(list)
        for p in passages_to_evaluate:
            docs_passages[p.document_id].append(p)

        for doc_id, passages in docs_passages.items():
            if entity_lower and doc_id not in docs_with_entity:
                continue

            doc_matched_fields = set()
            entity_passages = []
            if entity_lower:
                for p in passages:
                    if _keyword_present(entity_lower, p.chunk_text.lower()):
                        entity_passages.append(p)

            attr_passages = []
            for attr in target.requested_attributes:
                for p in passages:
                    if _evaluate_attribute_lexicon(attr, p.chunk_text):
                        doc_matched_fields.add(attr)
                        attr_passages.append(p)

            # For target_entity queries, we find the single best document
            is_better = len(doc_matched_fields) > len(best_doc_matched_fields)
            if not is_better and (
                len(doc_matched_fields) == len(best_doc_matched_fields)
            ):
                if not best_doc_qualifying_passages:
                    is_better = True

            if is_better:
                best_doc_matched_fields = doc_matched_fields
                unique_passages = {
                    p.chunk_id: p for p in (entity_passages + attr_passages)
                }
                best_doc_qualifying_passages = list(unique_passages.values())

            # For attribute-only queries, we pool across all documents
            if attr_passages or entity_passages:
                pooled_matched_fields.update(doc_matched_fields)
                unique_passages = {
                    p.chunk_id: p for p in (entity_passages + attr_passages)
                }
                pooled_qualifying_passages.extend(unique_passages.values())

        if entity_lower:
            matched_fields = best_doc_matched_fields
            qualifying_passages = best_doc_qualifying_passages
        else:
            matched_fields = pooled_matched_fields
            # Deduplicate qualifying_passages globally for pooled
            qualifying_passages = list(
                {p.chunk_id: p for p in pooled_qualifying_passages}.values()
            )

        missing_fields_list = [
            a for a in target.requested_attributes if a not in matched_fields
        ]
        matched_fields_list = [
            a for a in target.requested_attributes if a in matched_fields
        ]

        human_missing_fields = [
            HUMAN_ATTRIBUTE_LABELS.get(a, a) for a in missing_fields_list
        ]
        human_missing_str = ", ".join(human_missing_fields)

        if not matched_fields:
            if entity_lower:
                return EvidenceResult(
                    status=EvidenceStatus.PARTIALLY_SUFFICIENT,
                    missing_fields=missing_fields_list,
                    evidence_directive=(
                        f"{target.target_entity} is recorded, but not found "
                        f"in records: {human_missing_str}."
                    ),
                    qualified_passages=qualifying_passages,
                )
            return EvidenceResult(
                status=EvidenceStatus.INSUFFICIENT,
                missing_fields=missing_fields_list,
                evidence_directive=_absent_records_directive(human_missing_fields),
            )
        elif missing_fields_list:
            if entity_lower:
                directive = (
                    f"{target.target_entity} is recorded, but not found in records: "
                    f"{human_missing_str}."
                )
            else:
                directive = (
                    f"Information partially found in your uploaded records. "
                    f"Not found in records: {human_missing_str}."
                )

            return EvidenceResult(
                status=EvidenceStatus.PARTIALLY_SUFFICIENT,
                matched_fields=matched_fields_list,
                missing_fields=missing_fields_list,
                evidence_directive=directive,
                qualified_passages=qualifying_passages,
            )
        else:
            return EvidenceResult(
                status=EvidenceStatus.SUFFICIENT,
                matched_fields=matched_fields_list,
                evidence_directive=(
                    "All requested information was found in your uploaded records."
                ),
                qualified_passages=qualifying_passages,
            )

    # ------------------------------------------------------------------
    # Rule B: entity only — no requested attributes.
    # ------------------------------------------------------------------
    if target.target_entity:
        qualifying_passages = [
            p
            for p in passages_to_evaluate
            if _keyword_present(entity_lower, p.chunk_text.lower())
        ]
        if qualifying_passages:
            return EvidenceResult(
                status=EvidenceStatus.SUFFICIENT,
                evidence_directive=(
                    "All requested information was found in your uploaded records."
                ),
                qualified_passages=qualifying_passages,
            )
        return EvidenceResult(
            status=EvidenceStatus.INSUFFICIENT,
            evidence_directive=_absent_records_directive([target.target_entity]),
        )

    # ------------------------------------------------------------------
    # Rule C: generic domain query — no entity, no attributes.
    # All retrieved passages qualify.
    # ------------------------------------------------------------------
    return EvidenceResult(
        status=EvidenceStatus.SUFFICIENT,
        evidence_directive="Document content is available.",
        qualified_passages=passages_to_evaluate,
    )
