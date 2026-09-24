import logging
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.health.inquiry_context import StructuredHealthContext
from app.health.retrieval import RetrievalResult, RetrievedPassage
from app.schemas.inquiry import EvidenceStatus, InquiryTarget

logger = logging.getLogger(__name__)

HUMAN_ATTRIBUTE_LABELS: dict[str, str] = {
    "physician_name": "physician name",
    "dosage": "dosage",
    "clinic": "clinic or facility name",
    "consultation_notes": "consultation notes or doctor recommendations",
    "contact_number": "contact phone number",
    "frequency": "medication frequency",
    "status": "status",
    "blood_group": "blood group",
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


def evaluate_evidence(
    target: InquiryTarget, context: StructuredHealthContext
) -> EvidenceResult:
    """
    Evaluates query against structured context to establish evidence truth.
    No LLM used. Enforces negative-absence protection ('not recorded').
    """
    domain = target.target_domain
    if not domain or not hasattr(context, domain):
        return EvidenceResult(
            status=EvidenceStatus.INSUFFICIENT,
            evidence_directive="Domain not recorded in health context.",
        )

    records_data = getattr(context, domain)

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
                # Naive deterministic matching. Real matching could be more robust.
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
                    # Allergies lack inferred active/resolved state
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
            r"\b(dose|dosage|strength)\s*:\s*\d+(?:\.\d+)?\s*"
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
    retrieval_result: RetrievalResult,
    requesting_patient_id: uuid.UUID,
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
