import uuid
from typing import Protocol

from pydantic import BaseModel

from app.health.evidence_evaluator import EvidenceResult
from app.health.inquiry_context import StructuredHealthContext
from app.schemas.inquiry import (
    EvidenceStatus,
    InquiryTarget,
    SafetyGuardrailState,
)


class SynthesisResult(BaseModel):
    """The raw synthesis result from the LLM provider."""

    answer_text: str
    cited_record_ids: list[uuid.UUID]


class LLMProvider(Protocol):
    """Abstract interface for LLM synthesis."""

    async def synthesize_response(
        self,
        query: str,
        target: InquiryTarget,
        context: StructuredHealthContext,
        evidence: EvidenceResult,
        safety_state: SafetyGuardrailState,
    ) -> SynthesisResult: ...


def _build_system_prompt() -> str:
    """
    Constructs the boundary prompt explicitly isolating the LLM from
    medical decision-making, unverified claims, and negative diagnosis.
    """
    return (
        "The backend owns evidence truth; the LLM owns language synthesis. "
        "You are a medical data synthesis assistant. "
        "Your task is to answer user queries exclusively based on the "
        "provided structured health records. "
        "You must adhere strictly to the backend-provided evidence directives. "
        "Never invent patient facts, guess missing values, or generate fake citations. "
        "Never convert the absence of a record into a negative patient-health claim "
        "(e.g., do not say 'You do not have diabetes'). "
        "Instead, state that the records do not contain the requested information. "
        "Never recommend treatment/medication changes, clinical triage, "
        "severity assessment, or diagnosis. "
        "If a safety notice is provided, preserve it exactly and do not add "
        "your own medical advice."
    )


class MockLLMProvider:
    """
    Deterministic mock provider for testing evidence and prompt boundaries.
    Does not use network calls.
    """

    async def synthesize_response(
        self,
        query: str,
        target: InquiryTarget,
        context: StructuredHealthContext,
        evidence: EvidenceResult,
        safety_state: SafetyGuardrailState,
    ) -> SynthesisResult:

        # 1. Safety overrides
        if safety_state.triggered:
            if not safety_state.advisory_message:
                raise ValueError("Safety state triggered but missing advisory message.")
            return SynthesisResult(
                answer_text=safety_state.advisory_message,
                cited_record_ids=[],
            )

        # 2. Insufficient evidence
        if evidence.status == EvidenceStatus.INSUFFICIENT:
            return SynthesisResult(
                answer_text=evidence.evidence_directive,
                cited_record_ids=[],
            )

        # 3. Partially or Fully Sufficient Evidence
        citations: list[uuid.UUID] = []
        for r in evidence.matched_records:
            if hasattr(r, "id") and isinstance(r.id, uuid.UUID):
                citations.append(r.id)

        answer_text = ""
        if evidence.status == EvidenceStatus.PARTIALLY_SUFFICIENT:
            answer_text = evidence.evidence_directive
        else:
            # Generate deterministic mock answer
            if target.target_entity:
                answer_text = f"Records confirm {target.target_entity}."
            else:
                answer_text = "Records confirm requested information."

            if evidence.matched_fields:
                answer_text += (
                    f" Attributes {', '.join(evidence.matched_fields)} are present."
                )

        return SynthesisResult(
            answer_text=answer_text.strip(),
            cited_record_ids=citations,
        )
