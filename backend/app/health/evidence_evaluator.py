from typing import Any

from pydantic import BaseModel

from app.health.inquiry_context import StructuredHealthContext
from app.schemas.inquiry import EvidenceStatus, InquiryTarget


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
