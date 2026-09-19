import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from pydantic import BaseModel

from app.health.inquiry_context import StructuredHealthContext
from app.health.retrieval import RetrievalResult
from app.schemas.inquiry import EvidenceStatus, InquiryTarget

logger = logging.getLogger(__name__)


class EvidenceResult(BaseModel):
    """Clean internal result representation for response synthesis."""

    status: EvidenceStatus
    matched_records: list[Any] = []
    matched_fields: list[str] = []
    missing_fields: list[str] = []
    temporal_interpretation: str = "all"
    evidence_directive: str = ""


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
    # 2. Empty retrieval result gate.
    # ------------------------------------------------------------------
    if retrieval_result.is_empty:
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
    # Rule A: requested_attributes non-empty — pool across all passages.
    # ------------------------------------------------------------------
    if target.requested_attributes:
        matched_fields: set[str] = set()

        for p in retrieval_result.passages:
            for attr in target.requested_attributes:
                if _keyword_present(attr.lower(), p.chunk_text.lower()):
                    matched_fields.add(attr)

        # Deterministic ordering: preserve target.requested_attributes order.
        missing_fields_list = [
            a for a in target.requested_attributes if a not in matched_fields
        ]
        matched_fields_list = [
            a for a in target.requested_attributes if a in matched_fields
        ]

        if not matched_fields:
            # Zero attributes corroborated across all passages.
            return EvidenceResult(
                status=EvidenceStatus.INSUFFICIENT,
                missing_fields=list(target.requested_attributes),
                evidence_directive=_absent_records_directive(
                    list(target.requested_attributes)
                ),
            )
        elif missing_fields_list:
            # Some corroborated, some missing.
            return EvidenceResult(
                status=EvidenceStatus.PARTIALLY_SUFFICIENT,
                matched_fields=matched_fields_list,
                missing_fields=missing_fields_list,
                evidence_directive=(
                    f"Information partially found in your uploaded records. "
                    f"Not found in records: {', '.join(missing_fields_list)}."
                ),
            )
        else:
            # All requested attributes corroborated.
            return EvidenceResult(
                status=EvidenceStatus.SUFFICIENT,
                matched_fields=matched_fields_list,
                evidence_directive=(
                    "All requested information was found in your uploaded records."
                ),
            )

    # ------------------------------------------------------------------
    # Rule B: entity only — no requested attributes.
    # ------------------------------------------------------------------
    if target.target_entity:
        entity_lower = target.target_entity.lower()
        entity_found = any(
            _keyword_present(entity_lower, p.chunk_text.lower())
            for p in retrieval_result.passages
        )
        if entity_found:
            return EvidenceResult(
                status=EvidenceStatus.SUFFICIENT,
                evidence_directive=(
                    "All requested information was found in your uploaded records."
                ),
            )
        return EvidenceResult(
            status=EvidenceStatus.INSUFFICIENT,
            evidence_directive=_absent_records_directive([target.target_entity]),
        )

    # ------------------------------------------------------------------
    # Rule C: generic domain query — no entity, no attributes.
    # ------------------------------------------------------------------
    return EvidenceResult(
        status=EvidenceStatus.SUFFICIENT,
        evidence_directive="Document content is available.",
    )
