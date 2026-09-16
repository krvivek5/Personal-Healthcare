import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.health.inquiry_context import StructuredHealthContext
from app.schemas.inquiry import InquiryTarget

UUID_REGEX = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)

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


class SanitizedHealthContext(BaseModel):
    """
    Sanitized context safe for external LLM payload transmission.

    Guarantees:
    1. Contains NO database UUIDs, patient_id, user_id, or storage keys.
    2. Reference tokens [REC-N] are assigned deterministically.
    3. Maintains a server-side mapping from token to authoritative database UUID.
    4. Query-scoped minimization excludes irrelevant sensitive health domains.
    """

    profile: Optional[dict[str, Any]] = None
    records: list[SanitizedRecord] = Field(default_factory=list)
    reference_map: dict[str, uuid.UUID] = Field(default_factory=dict)
    included_domains: list[str] = Field(default_factory=list)

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
        }
        if self.profile:
            payload["profile"] = self.profile
        return payload

    def to_prompt_text(self) -> str:
        """
        Returns a formatted, plain-text string representation of records with [REC-N]
        tokens suitable for prompt injection.
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


def build_sanitized_context(
    context: StructuredHealthContext,
    target: Optional[InquiryTarget] = None,
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

    if target_domain and target_domain in valid_domains:
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

    return SanitizedHealthContext(
        profile=sanitized_profile,
        records=records,
        reference_map=reference_map,
        included_domains=included_domains,
    )
