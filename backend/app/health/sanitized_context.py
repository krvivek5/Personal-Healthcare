import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.health.evidence_evaluator import (
    extract_canonical_clinical_date,
    get_candidate_sort_key,
)
from app.health.inquiry_context import StructuredHealthContext
from app.health.retrieval import RetrievedPassage
from app.schemas.inquiry import InquiryTarget

UUID_REGEX = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)

# ---------------------------------------------------------------------------
# M4 S5 passage serialization limits
# ---------------------------------------------------------------------------

#: Per-passage hard character cap.  Prevents prompt bloat from abnormal
#: chunk boundary snapping.  5 passages × 1200 = 6000 chars maximum.
MAX_PASSAGE_CHARS: int = 1200

#: Maximum passages serialized into the retrieved-passage block.
#: Mirrors S4 RETRIEVAL_MAX_TOP_K so the full K result can always be rendered.
MAX_RETRIEVED_PASSAGES: int = 5

# Standard sequence of domains for deterministic ordering
DOMAIN_ORDER = [
    "profile",
    "conditions",
    "medications",
    "allergies",
    "symptoms",
    "goals",
    "recent_timeline_events",
]


class SanitizedRecord(BaseModel):
    """
    A clinical record stripped of database keys and assigned a reference token.
    Contains only clinically relevant attributes needed for plain-language synthesis.
    """

    token: str  # e.g. "[REC-1]"
    entity_type: str  # "profile", "condition", "medication", etc.
    attributes: dict[str, Any]


class PassageProvenance(BaseModel):
    """Complete provenance metadata for a single qualified retrieved passage.

    Stored server-side in ``SanitizedHealthContext.passage_map``.  Used by
    S6 to enrich ``InquiryCitation`` with chunk-level attribution data.

    No patient-identifiable information is stored here except for the
    canonical ``document_id`` needed to resolve back to a ``MedicalDocument``
    row for citation linkage.  This ID is never serialized into prompt text.
    """

    token: str  # e.g. "[DOC-1]"
    document_id: uuid.UUID  # Canonical MedicalDocument.id for citation
    chunk_id: uuid.UUID  # Specific DocumentChunk.id for attribution
    page_number: Optional[int] = None
    chunk_index: int
    passage_text: str  # Verbatim chunk text (uncapped; cap applied in prompt)
    display_name: str  # MedicalDocument.display_name
    document_type: str  # MedicalDocument.document_type
    document_date: Optional[date] = None


class SanitizedHealthContext(BaseModel):
    """
    Sanitized context safe for external LLM payload transmission.

    Guarantees:
    1. Contains NO database UUIDs, patient_id, user_id, or storage keys.
    2. Reference tokens [REC-N] are assigned deterministically.
    3. Maintains a server-side mapping from token to authoritative database UUID.
    4. Query-scoped minimization excludes irrelevant sensitive health domains.
    5. (M4 S5) passage_map provides chunk-level provenance for S6 citation
       enrichment. passage_map values are server-side only and never serialized
       into prompt text as raw UUIDs.
    """

    profile: Optional[dict[str, Any]] = None
    records: list[SanitizedRecord] = Field(default_factory=list)
    reference_map: dict[str, uuid.UUID] = Field(default_factory=dict)
    included_domains: list[str] = Field(default_factory=list)
    # M4 S5: dual-resolution passage provenance map.
    # Keys: both "[DOC-N]" and "DOC-N" for backward-compatible reconciliation.
    # Values: PassageProvenance with chunk-level attribution for S6 citations.
    passage_map: dict[str, PassageProvenance] = Field(default_factory=dict)
    # S4 extension: chronologically ordered trajectory statements
    chronological_trajectory: list[str] = Field(default_factory=list)

    def to_llm_payload(self) -> dict[str, Any]:
        """
        Returns a JSON-serializable dictionary safe for LLM payload transmission.
        All database UUIDs, user/patient IDs, and audit timestamps are strictly omitted.
        """
        payload: dict[str, Any] = {
            "included_domains": self.included_domains,
            "records": [
                {
                    "reference_token": r.token,
                    "entity_type": r.entity_type,
                    "attributes": r.attributes,
                }
                for r in self.records
            ],
            "chronological_trajectory": self.chronological_trajectory,
        }
        if self.profile:
            payload["profile"] = self.profile
        return payload

    def to_prompt_text(self) -> str:
        """
        Returns a formatted, plain-text string representation of records with [REC-N]
        tokens suitable for prompt injection.

        If ``passage_map`` is non-empty (SUFFICIENT / PARTIALLY_SUFFICIENT evidence),
        appends a ``=== RETRIEVED PASSAGES ===`` block with sanitized passage text
        (capped at ``MAX_PASSAGE_CHARS`` per passage).  The block is completely
        omitted when evidence is INSUFFICIENT (empty ``passage_map``).
        """
        lines: list[str] = []
        if self.profile:
            lines.append("Patient Profile:")
            for k in sorted(self.profile.keys()):
                v = self.profile[k]
                lines.append(f"  {k}: {v if v is not None else 'not recorded'}")

        health_records = [r for r in self.records if r.entity_type != "document"]
        doc_records = [r for r in self.records if r.entity_type == "document"]

        if health_records:
            lines.append("Patient Health Records:")
            for r in health_records:
                attr_parts = []
                for k in sorted(r.attributes.keys()):
                    v = r.attributes[k]
                    val_str = v if v is not None else "not recorded"
                    attr_parts.append(f"{k}: {val_str}")
                lines.append(
                    f"  {r.token} [{r.entity_type.upper()}] {', '.join(attr_parts)}"
                )

        if doc_records:
            lines.append("=== DOCUMENT EVIDENCE ===")
            for r in doc_records:
                display_name = r.attributes.get("display_name") or "Document"
                doc_date = r.attributes.get("document_date") or "not recorded"
                doc_type = (r.attributes.get("document_type") or "DOCUMENT").upper()
                excerpt = r.attributes.get("extracted_excerpt") or ""
                lines.append(
                    f"{r.token} Document: {display_name} | "
                    f"Date: {doc_date} | Type: {doc_type}"
                )
                lines.append("Content:")
                lines.append(excerpt)

        # M4 S5: Retrieved passage context block.
        # Serialize only when passage_map is non-empty (SUFFICIENT or
        # PARTIALLY_SUFFICIENT evidence).  Completely omitted for INSUFFICIENT
        # evidence (caller leaves context.passages empty, so passage_map == {}).
        bracketed_passage_tokens = [
            k for k in self.passage_map if k.startswith("[DOC-")
        ]
        if bracketed_passage_tokens:
            passage_blocks: list[str] = []
            for token in bracketed_passage_tokens:
                prov = self.passage_map[token]
                display_name = prov.display_name or "Document"
                date_str = (
                    prov.document_date.isoformat()
                    if prov.document_date
                    else "not recorded"
                )
                page_str = (
                    str(prov.page_number)
                    if prov.page_number is not None
                    else "not recorded"
                )
                doc_type = (prov.document_type or "DOCUMENT").upper()
                # Apply per-passage character cap at serialization time.
                # passage_map retains full text for S6 citation purposes.
                passage_text = prov.passage_text
                if len(passage_text) > MAX_PASSAGE_CHARS:
                    passage_text = passage_text[:MAX_PASSAGE_CHARS]
                header = (
                    f"{token} Document: {display_name} | "
                    f"Date: {date_str} | "
                    f"Page: {page_str} | "
                    f"Type: {doc_type}"
                )
                block = f"{header}\nPassage:\n{passage_text}"
                passage_blocks.append(block)
            # Header on its own line, then blocks separated by a blank line.
            lines.append("=== RETRIEVED PASSAGES ===\n" + "\n\n".join(passage_blocks))

        # S4: Append chronological trajectory block if non-empty
        if self.chronological_trajectory:
            lines.append(
                "=== CHRONOLOGICAL TRAJECTORY ===\n"
                + "\n".join(self.chronological_trajectory)
            )

        return "\n".join(lines)


def _format_value(val: Any) -> Any:
    """Formats dates, datetimes, and decimals into standard JSON-serializable types."""
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    return val


def reconcile_reference_tokens(
    cited_tokens: list[str],
    reference_map: dict[str, uuid.UUID],
    valid_patient_record_ids: Optional[set[uuid.UUID]] = None,
) -> list[uuid.UUID]:
    """
    Deterministically translates cited reference tokens (e.g. '[REC-1]' or 'REC-1')
    back to authoritative patient record UUIDs using the server-side reference_map.

    If valid_patient_record_ids is provided, verifies that each resolved UUID
    belongs to the authenticated patient's actual record set. Unmapped or foreign
    tokens are strictly discarded.
    """
    resolved_ids: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()

    for raw_token in cited_tokens:
        token = raw_token.strip()
        # Look up directly or normalized (with or without brackets)
        matched_uuid = reference_map.get(token)
        if not matched_uuid:
            clean_token = token.strip("[]")
            bracketed_token = f"[{clean_token}]"
            matched_uuid = reference_map.get(bracketed_token) or reference_map.get(
                clean_token
            )

        if matched_uuid and matched_uuid not in seen:
            if (
                valid_patient_record_ids is None
                or matched_uuid in valid_patient_record_ids
            ):
                resolved_ids.append(matched_uuid)
                seen.add(matched_uuid)

    return resolved_ids


def _sanitize_trajectory_text(text: str) -> str:
    """
    Sanitize text for trajectory summary line:
    - Replaces newlines, carriage returns, and tabs with single spaces.
    - Strips prompt delimiters and control markers
      (===, ---, ###, System:, Human:, Instruction:).
    - Collapses consecutive whitespace and strips ends.
    - Neutralizes structural prompt delimiters and control markers, preventing
      candidate text from creating fake prompt sections or spoofing tokens.
      (Generic natural-language prompt injection is not claimed to be completely
      eliminated by this structural sanitizer alone).
    """
    if not text:
        return ""
    clean = re.sub(r"[=\-#]{3,}", " ", str(text))
    clean = re.sub(r"(?i)\b(system|human|assistant|instruction):", " ", clean)
    clean = re.sub(r"\[(REC|DOC)-\d+\]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def format_trajectory_item_description(candidate: Any) -> str:
    """
    Generates a compact human-readable trajectory description per provenance class.
    Zero internal database UUIDs or patient IDs.

    Primary mapping uses authoritative repository fields from
    backend/app/db/models.py, with safe fallback chains for fixture compatibility:
    1. DOCUMENT (RetrievedPassage):
       - Primary: display name or title or "Clinical Document"
       - Chunk index: passage.chunk_index
       - Full text remains exclusively in === RETRIEVED PASSAGES ===
    2. TIMELINE (TimelineEventEvidence):
       - Sanitized event description: _sanitize_trajectory_text(event.description)
    3. STRUCTURED (relational Condition, Medication, Symptom, and LabResult):
       - LabResult: f"{test_name}: {value} {unit}".strip()
       - Medication: f"{med.name} {med.dosage or ''}".strip()
       - Symptom: f"{symp.name} (Severity: {symp.severity or 'Not specified'})"
       - Condition: f"{cond.name} (Status: {cond.status or 'Active'})"
    """
    if isinstance(candidate, RetrievedPassage) or hasattr(candidate, "chunk_index"):
        title = (
            getattr(candidate, "document_display_name", None)
            or getattr(candidate, "document_title", None)
            or getattr(candidate, "display_name", None)
            or "Clinical Document"
        )
        chunk_idx = getattr(candidate, "chunk_index", 0)
        return _sanitize_trajectory_text(f"{title} - Chunk {chunk_idx}")

    if hasattr(candidate, "event_type") and hasattr(candidate, "description"):
        return _sanitize_trajectory_text(candidate.description)

    # Evaluator/fixture LabResult compatibility (test_name, value, unit)
    if hasattr(candidate, "test_name"):
        val = getattr(candidate, "value", "")
        unit = getattr(candidate, "unit", "")
        val_str = f"{val} {unit}".strip() if unit else str(val).strip()
        return _sanitize_trajectory_text(f"{candidate.test_name}: {val_str}".strip())

    # Medication (authoritative fields: name, dosage; fixture fallback: medication_name)
    if hasattr(candidate, "dosage") or hasattr(candidate, "medication_name"):
        med_name = getattr(candidate, "name", None) or getattr(
            candidate, "medication_name", "Medication"
        )
        dosage = getattr(candidate, "dosage", "") or ""
        return _sanitize_trajectory_text(f"{med_name} {dosage}".strip())

    # Symptom (authoritative fields: name, severity; fixture fallback: symptom_name)
    if hasattr(candidate, "severity") or hasattr(candidate, "symptom_name"):
        symp_name = getattr(candidate, "name", None) or getattr(
            candidate, "symptom_name", "Symptom"
        )
        sev = getattr(candidate, "severity", "Not specified") or "Not specified"
        return _sanitize_trajectory_text(f"{symp_name} (Severity: {sev})")

    # Condition (authoritative fields: name, status; fixture fallbacks)
    if (
        hasattr(candidate, "status")
        or hasattr(candidate, "condition_name")
        or hasattr(candidate, "clinical_status")
    ):
        cond_name = getattr(candidate, "name", None) or getattr(
            candidate, "condition_name", "Condition"
        )
        status_val = (
            getattr(candidate, "status", None)
            or getattr(candidate, "clinical_status", "Active")
            or "Active"
        )
        return _sanitize_trajectory_text(f"{cond_name} (Status: {status_val})")

    name = getattr(candidate, "name", "Record")
    return _sanitize_trajectory_text(str(name))


def _get_domain_tag(candidate: Any) -> str:
    if isinstance(candidate, RetrievedPassage) or hasattr(candidate, "chunk_index"):
        doc_type = getattr(candidate, "document_type", None) or "DOCUMENT"
        return f"DOCUMENT: {doc_type.upper()}"

    if hasattr(candidate, "event_type") and hasattr(candidate, "description"):
        source_type = getattr(candidate, "source_type", None) or getattr(
            candidate, "event_type", "EVENT"
        )
        return f"TIMELINE: {str(source_type).upper()}"

    if hasattr(candidate, "test_name"):
        return "STRUCTURED: LAB"
    if hasattr(candidate, "dosage") or hasattr(candidate, "medication_name"):
        return "STRUCTURED: MEDICATION"
    if hasattr(candidate, "severity") or hasattr(candidate, "symptom_name"):
        return "STRUCTURED: SYMPTOM"
    if hasattr(candidate, "allergen"):
        return "STRUCTURED: ALLERGY"
    if (
        hasattr(candidate, "status")
        or hasattr(candidate, "condition_name")
        or hasattr(candidate, "clinical_status")
    ):
        return "STRUCTURED: CONDITION"
    if hasattr(candidate, "entity_type"):
        return f"STRUCTURED: {str(candidate.entity_type).upper()}"
    return "STRUCTURED: RECORD"


def build_sanitized_context(
    context: StructuredHealthContext,
    target: Optional[InquiryTarget] = None,
    evidence: Optional[Any] = None,
) -> SanitizedHealthContext:
    """
    Serializes a StructuredHealthContext into a sanitized, tokenized representation.

    1. Applies query-scoped minimization: if target.target_domain is specified,
       includes only the requested domain plus general profile context, omitting
       unrelated sensitive domains.
    2. Strips all database primary keys, tenant IDs, source IDs, and audit timestamps.
    3. Deterministically assigns sequential reference tokens [REC-1], [REC-2]...
    4. Populates the server-side reference_map translating tokens back to genuine UUIDs.
    """
    # 1. Determine included domains based on query target
    valid_domains = set(DOMAIN_ORDER)
    target_domain = (
        target.target_domain.lower() if (target and target.target_domain) else None
    )

    if target and target.candidate_structured_domains:
        if any(d.lower() == "all" for d in target.candidate_structured_domains):
            included_domains = list(DOMAIN_ORDER)
        else:
            included_domains = ["profile"]
            for domain in target.candidate_structured_domains:
                domain_lower = domain.lower()
                if (
                    domain_lower in valid_domains
                    and domain_lower not in included_domains
                ):
                    included_domains.append(domain_lower)
    elif target_domain and target_domain in valid_domains:
        if target_domain == "profile":
            included_domains = ["profile"]
        else:
            # Include profile as general baseline demographics plus requested domain
            included_domains = ["profile", target_domain]
    else:
        # Inquiry target is unconstrained or cross-domain; include all domains
        included_domains = list(DOMAIN_ORDER)

    records: list[SanitizedRecord] = []
    reference_map: dict[str, uuid.UUID] = {}
    counter = 1

    # 2. Profile Sanitization
    sanitized_profile: Optional[dict[str, Any]] = None
    if "profile" in included_domains and context.profile:
        p = context.profile
        sanitized_profile = {
            "biological_sex": p.biological_sex,
        }

        if p.date_of_birth:
            # Derive age_years server-side and never expose exact DOB
            today = date.today()
            age_years = (
                today.year
                - p.date_of_birth.year
                - (
                    (today.month, today.day)
                    < (p.date_of_birth.month, p.date_of_birth.day)
                )
            )
            sanitized_profile["age_years"] = age_years

        # Make profile exposure query-scoped: broader context only for
        # holistic/profile inquiries
        if target_domain == "profile" or target_domain is None:
            sanitized_profile["height_cm"] = _format_value(p.height_cm)
            sanitized_profile["blood_group"] = p.blood_group
            sanitized_profile["notes"] = p.notes

        if p.id:
            token = f"[REC-{counter}]"
            token_clean = f"REC-{counter}"
            reference_map[token] = p.id
            reference_map[token_clean] = p.id
            records.append(
                SanitizedRecord(
                    token=token,
                    entity_type="profile",
                    attributes=sanitized_profile,
                )
            )
            counter += 1

    # 3. Conditions Sanitization
    if "conditions" in included_domains and context.conditions:
        # Sort deterministically by UUID hex
        sorted_conditions = sorted(context.conditions, key=lambda c: c.id.hex)
        for c in sorted_conditions:
            token = f"[REC-{counter}]"
            token_clean = f"REC-{counter}"
            reference_map[token] = c.id
            reference_map[token_clean] = c.id
            attrs = {
                "name": c.name,
                "status": c.status,
                "is_chronic": c.is_chronic,
                "started_at": _format_value(c.started_at),
                "ended_at": _format_value(c.ended_at),
                "notes": c.notes,
                "verification_state": getattr(c, "verification_state", "UNVERIFIED"),
            }
            records.append(
                SanitizedRecord(
                    token=token,
                    entity_type="condition",
                    attributes=attrs,
                )
            )
            counter += 1

    # 4. Medications Sanitization
    if "medications" in included_domains and context.medications:
        sorted_medications = sorted(context.medications, key=lambda m: m.id.hex)
        for m in sorted_medications:
            token = f"[REC-{counter}]"
            token_clean = f"REC-{counter}"
            reference_map[token] = m.id
            reference_map[token_clean] = m.id
            attrs = {
                "name": m.name,
                "dosage": m.dosage,
                "frequency": m.frequency,
                "status": m.status,
                "as_needed": m.as_needed,
                "started_at": _format_value(m.started_at),
                "ended_at": _format_value(m.ended_at),
                "notes": m.notes,
                "verification_state": getattr(m, "verification_state", "UNVERIFIED"),
            }
            records.append(
                SanitizedRecord(
                    token=token,
                    entity_type="medication",
                    attributes=attrs,
                )
            )
            counter += 1

    # 5. Allergies Sanitization
    if "allergies" in included_domains and context.allergies:
        sorted_allergies = sorted(context.allergies, key=lambda a: a.id.hex)
        for a in sorted_allergies:
            token = f"[REC-{counter}]"
            token_clean = f"REC-{counter}"
            reference_map[token] = a.id
            reference_map[token_clean] = a.id
            attrs = {
                "allergen": a.allergen,
                "reaction": a.reaction,
                "severity": a.severity,
                "recorded_at": _format_value(a.recorded_at),
                "notes": a.notes,
                "verification_state": getattr(a, "verification_state", "UNVERIFIED"),
            }
            records.append(
                SanitizedRecord(
                    token=token,
                    entity_type="allergy",
                    attributes=attrs,
                )
            )
            counter += 1

    # 6. Symptoms Sanitization
    if "symptoms" in included_domains and context.symptoms:
        sorted_symptoms = sorted(context.symptoms, key=lambda s: s.id.hex)
        for s in sorted_symptoms:
            token = f"[REC-{counter}]"
            token_clean = f"REC-{counter}"
            reference_map[token] = s.id
            reference_map[token_clean] = s.id
            attrs = {
                "name": s.name,
                "severity": s.severity,
                "started_at": _format_value(s.started_at),
                "ended_at": _format_value(s.ended_at),
                "notes": s.notes,
                "verification_state": getattr(s, "verification_state", "UNVERIFIED"),
            }
            records.append(
                SanitizedRecord(
                    token=token,
                    entity_type="symptom",
                    attributes=attrs,
                )
            )
            counter += 1

    # 7. Goals Sanitization
    if "goals" in included_domains and context.goals:
        sorted_goals = sorted(context.goals, key=lambda g: g.id.hex)
        for g in sorted_goals:
            token = f"[REC-{counter}]"
            token_clean = f"REC-{counter}"
            reference_map[token] = g.id
            reference_map[token_clean] = g.id
            attrs = {
                "title": getattr(g, "title", getattr(g, "description", "")),
                "description": getattr(g, "description", getattr(g, "title", "")),
                "status": g.status,
                "target_date": _format_value(g.target_date),
                "notes": g.notes,
                "verification_state": getattr(g, "verification_state", "UNVERIFIED"),
            }
            records.append(
                SanitizedRecord(
                    token=token,
                    entity_type="goal",
                    attributes=attrs,
                )
            )
            counter += 1

    # 8. Timeline Events Sanitization
    if "recent_timeline_events" in included_domains and context.recent_timeline_events:
        for t in context.recent_timeline_events:
            attrs = {
                "event_type": t.event_type,
                "event_date": _format_value(t.event_date),
                "event_state": t.event_state,
                "title": t.title,
                "description": getattr(t, "description", None),
                "source_type": t.source_type,
            }
            # If the timeline event references a source record ID, map it to a token
            if t.source_id and isinstance(t.source_id, uuid.UUID):
                token = f"[REC-{counter}]"
                token_clean = f"REC-{counter}"
                reference_map[token] = t.source_id
                reference_map[token_clean] = t.source_id
                records.append(
                    SanitizedRecord(
                        token=token,
                        entity_type="timeline",
                        attributes=attrs,
                    )
                )
                counter += 1

    # 9. Document Evidence Sanitization (M3 Slice 5)
    # A conservative character approximation for ~1500 tokens.
    MAX_DOCUMENT_EXCERPT_CHARS = 6000

    doc_counter = 1
    if context.documents:
        # We sort deterministically by document_id hex string to ensure
        # stable numbering, but they are already ordered correctly by
        # document_selection. We should respect the ordered selection but
        # ensure we assign tokens deterministically in that order.
        for doc in context.documents:
            token = f"[DOC-{doc_counter}]"
            token_clean = f"DOC-{doc_counter}"
            reference_map[token] = doc.document_id
            reference_map[token_clean] = doc.document_id

            # Budgeting Strategy: Enforce deterministic hard character cap
            excerpt = doc.extracted_excerpt
            if excerpt and len(excerpt) > MAX_DOCUMENT_EXCERPT_CHARS:
                excerpt = excerpt[:MAX_DOCUMENT_EXCERPT_CHARS]

            attrs = {
                "display_name": doc.display_name,
                "document_type": doc.document_type,
                "document_date": _format_value(doc.document_date),
                "extracted_excerpt": excerpt,
            }
            records.append(
                SanitizedRecord(
                    token=token,
                    entity_type="document",
                    attributes=attrs,
                )
            )
            doc_counter += 1

    # 10. Passage Evidence Sanitization (M4 Slice 5)
    # Processes context.passages populated by the orchestrator after
    # evaluate_passage_evidence determines SUFFICIENT / PARTIALLY_SUFFICIENT.
    # On INSUFFICIENT evidence the caller leaves context.passages empty,
    # so passage_map is empty and the serialized block is omitted.
    passage_map: dict[str, PassageProvenance] = {}
    passage_counter = 1

    if context.passages:
        for pec in context.passages[:MAX_RETRIEVED_PASSAGES]:
            token = f"[DOC-{passage_counter}]"
            token_clean = f"DOC-{passage_counter}"

            # reference_map: canonical MedicalDocument.id for backward-
            # compatible reconciliation via reconcile_reference_tokens.
            reference_map[token] = pec.document_id
            reference_map[token_clean] = pec.document_id

            # passage_map: full chunk-level provenance for S6 citation
            # enrichment.  Both [DOC-N] and DOC-N keys enable reconciliation
            # with or without bracket normalization.
            provenance = PassageProvenance(
                token=token,
                document_id=pec.document_id,
                chunk_id=pec.chunk_id,
                page_number=pec.page_number,
                chunk_index=pec.chunk_index,
                passage_text=pec.chunk_text,
                display_name=pec.display_name,
                document_type=pec.document_type,
                document_date=pec.document_date,
            )
            passage_map[token] = provenance
            passage_map[token_clean] = provenance

            passage_counter += 1

    # 11. Chronological Trajectory Serialization (M6 Slice 4)
    # Scoped strictly to milestone evidence: matched_records and qualified_passages.
    trajectory_lines: list[str] = []
    if evidence is not None and (
        getattr(evidence, "matched_records", None)
        or getattr(evidence, "qualified_passages", None)
    ):
        raw_struct = getattr(evidence, "matched_records", []) or []
        raw_docs = getattr(evidence, "qualified_passages", []) or []
        items = list(raw_struct) + list(raw_docs)
        items.sort(
            key=lambda c: (
                extract_canonical_clinical_date(c) or date.min,
                *get_candidate_sort_key(c),
            )
        )

        # Build reverse lookup maps for tokens
        rec_id_to_token: dict[Any, str] = {}
        for tok, r_id in reference_map.items():
            if tok.startswith("[REC-"):
                rec_id_to_token[r_id] = tok

        # Build passage provenance lookup: (document_id, chunk_index) -> token
        doc_prov_to_token: dict[tuple[Any, Any], str] = {}
        for tok, prov in passage_map.items():
            if tok.startswith("[DOC-"):
                doc_prov_to_token[(prov.document_id, prov.chunk_index)] = tok

        for item in items:
            canon_date = extract_canonical_clinical_date(item)
            date_str = canon_date.isoformat() if canon_date else "not recorded"
            domain_tag = _get_domain_tag(item)
            desc = format_trajectory_item_description(item)

            # Determine reference token
            token = None
            if hasattr(item, "token") and getattr(item, "token"):
                token = getattr(item, "token")
            elif isinstance(item, RetrievedPassage) or hasattr(item, "chunk_index"):
                doc_id = getattr(item, "document_id", None)
                chunk_idx = getattr(item, "chunk_index", None)
                token = doc_prov_to_token.get((doc_id, chunk_idx))
                if not token:
                    for tok, r_id in reference_map.items():
                        if tok.startswith("[DOC-") and r_id == doc_id:
                            token = tok
                            break
                if not token:
                    token = f"[DOC-{passage_counter}]"
                    passage_counter += 1
            else:
                item_id = getattr(item, "id", None)
                source_id = getattr(item, "source_id", None)
                token = rec_id_to_token.get(source_id) or rec_id_to_token.get(item_id)
                if not token:
                    token = f"[REC-{counter}]"
                    counter += 1

            clean_tok = token.strip("[]")
            bracketed_tok = f"[{clean_tok}]"
            trajectory_lines.append(
                f"- [{date_str}] [{domain_tag}] {desc} {bracketed_tok}"
            )

    return SanitizedHealthContext(
        profile=sanitized_profile,
        records=records,
        reference_map=reference_map,
        included_domains=included_domains,
        passage_map=passage_map,
        chronological_trajectory=trajectory_lines,
    )
