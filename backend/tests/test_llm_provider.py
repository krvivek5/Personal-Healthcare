import uuid
from datetime import datetime

import pytest

from app.core.llm import LLMProvider, MockLLMProvider, SynthesisResult
from app.health.evidence_evaluator import EvidenceResult
from app.health.inquiry_context import StructuredHealthContext
from app.schemas.condition import ConditionResponse
from app.schemas.inquiry import (
    EvidenceStatus,
    InquiryTarget,
    SafetyGuardrailState,
)


@pytest.fixture
def mock_provider() -> LLMProvider:
    # 1. Provider interface can be injected
    return MockLLMProvider()


@pytest.fixture
def dummy_context() -> StructuredHealthContext:
    now = datetime.utcnow()
    # Create dummy records matching the expected schema
    return StructuredHealthContext(
        profile=None,
        conditions=[
            ConditionResponse(
                id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
                patient_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
                name="Asthma",
                status="active",
                is_chronic=True,
                recorded_at=now,
                source_type="PATIENT_REPORTED",
                source_id=None,
                verification_state="UNVERIFIED",
                created_at=now,
                updated_at=now,
            )
        ],
        medications=[],
        allergies=[],
        symptoms=[],
        goals=[],
        timeline=[],
    )


@pytest.mark.asyncio
async def test_mock_provider_deterministic_sufficient(
    mock_provider: LLMProvider, dummy_context: StructuredHealthContext
):
    # 2. Mock provider produces deterministic output
    # 3. Patient facts are taken only from supplied context (Sufficient)
    # 5. Backend EvidenceStatus is preserved
    # 7. Citation references are returned in expected format (UUID)

    target = InquiryTarget(
        target_domain="conditions",
        target_entity="Asthma",
        requested_attributes=["name"],
    )

    evidence = EvidenceResult(
        status=EvidenceStatus.SUFFICIENT,
        matched_records=dummy_context.conditions,
        matched_fields=["name"],
        missing_fields=[],
        temporal_interpretation="all",
        evidence_directive="All requested information is recorded.",
    )

    safety = SafetyGuardrailState(triggered=False)

    # 10. No external network calls occur (runs immediately)
    result = await mock_provider.synthesize_response(
        query="Do I have asthma?",
        target=target,
        context=dummy_context,
        evidence=evidence,
        safety_state=safety,
    )

    assert isinstance(result, SynthesisResult)
    assert "Records confirm Asthma" in result.answer_text
    assert "name" in result.answer_text
    assert len(result.cited_record_ids) == 1
    assert result.cited_record_ids[0] == uuid.UUID(
        "11111111-1111-1111-1111-111111111111"
    )


@pytest.mark.asyncio
async def test_mock_provider_partially_sufficient(
    mock_provider: LLMProvider, dummy_context: StructuredHealthContext
):
    # 4. Missing fields remain missing
    target = InquiryTarget(
        target_domain="conditions",
        target_entity="Asthma",
        requested_attributes=["clinic"],
    )

    evidence = EvidenceResult(
        status=EvidenceStatus.PARTIALLY_SUFFICIENT,
        matched_records=dummy_context.conditions,
        matched_fields=[],
        missing_fields=["clinic"],
        temporal_interpretation="all",
        evidence_directive="Information partially available. Not recorded: clinic.",
    )

    safety = SafetyGuardrailState(triggered=False)

    result = await mock_provider.synthesize_response(
        query="What clinic diagnosed my asthma?",
        target=target,
        context=dummy_context,
        evidence=evidence,
        safety_state=safety,
    )

    assert (
        result.answer_text == "Information partially available. Not recorded: clinic."
    )
    assert len(result.cited_record_ids) == 1


@pytest.mark.asyncio
async def test_mock_provider_insufficient(
    mock_provider: LLMProvider, dummy_context: StructuredHealthContext
):
    # 6. Insufficient evidence produces record-absence wording
    target = InquiryTarget(
        target_domain="profile",
        target_entity="blood_group",
    )

    evidence = EvidenceResult(
        status=EvidenceStatus.INSUFFICIENT,
        matched_records=[],
        matched_fields=[],
        missing_fields=["blood_group"],
        temporal_interpretation="all",
        evidence_directive="The requested attributes blood_group are not recorded.",
    )

    safety = SafetyGuardrailState(triggered=False)

    result = await mock_provider.synthesize_response(
        query="What is my blood type?",
        target=target,
        context=dummy_context,
        evidence=evidence,
        safety_state=safety,
    )

    assert (
        result.answer_text == "The requested attributes blood_group are not recorded."
    )
    assert len(result.cited_record_ids) == 0


@pytest.mark.asyncio
async def test_mock_provider_safety_override(
    mock_provider: LLMProvider, dummy_context: StructuredHealthContext
):
    # 9. Safety-triggered synthesis preserves fixed advisory
    target = InquiryTarget(
        target_domain="symptoms",
        target_entity="chest pain",
    )

    evidence = EvidenceResult(
        status=EvidenceStatus.SUFFICIENT,
        matched_records=[],
        matched_fields=[],
        missing_fields=[],
        temporal_interpretation="all",
        evidence_directive="",
    )

    fixed_advisory = (
        "⚠️ Safety Notice: Your inquiry mentions symptoms that may require "
        "prompt medical evaluation. Please seek professional medical care."
    )
    safety = SafetyGuardrailState(triggered=True, advisory_message=fixed_advisory)

    result = await mock_provider.synthesize_response(
        query="I have severe chest pain",
        target=target,
        context=dummy_context,
        evidence=evidence,
        safety_state=safety,
    )

    assert result.answer_text == fixed_advisory
    assert len(result.cited_record_ids) == 0


@pytest.mark.asyncio
async def test_mock_provider_safety_override_missing_advisory(
    mock_provider: LLMProvider, dummy_context: StructuredHealthContext
):
    target = InquiryTarget(target_domain="symptoms", target_entity="chest pain")
    evidence = EvidenceResult(
        status=EvidenceStatus.SUFFICIENT,
        matched_records=[],
        matched_fields=[],
        missing_fields=[],
        temporal_interpretation="all",
        evidence_directive="",
    )

    # Invalid state: triggered but no message
    safety = SafetyGuardrailState(triggered=True, advisory_message=None)

    with pytest.raises(ValueError, match="missing advisory message"):
        await mock_provider.synthesize_response(
            query="I have severe chest pain",
            target=target,
            context=dummy_context,
            evidence=evidence,
            safety_state=safety,
        )


def test_system_prompt_boundaries():
    from app.core.llm import _build_system_prompt

    prompt = _build_system_prompt().lower()

    # Core architectural rule
    assert "backend owns evidence truth" in prompt
    assert "llm owns language synthesis" in prompt

    # Mandatory prohibitions
    assert "invent patient facts" in prompt
    assert "guess missing values" in prompt
    assert "fake citations" in prompt

    # Do not convert absence to negative claim
    assert "convert the absence of a record into a negative" in prompt
    assert "patient-health claim" in prompt

    # Clinical prohibitions
    assert "diagnosis" in prompt
    assert "triage" in prompt
    assert "severity assessment" in prompt
    assert "treatment/medication changes" in prompt


def test_interface_signature():
    # 8. Provider cannot access database/identity directly (enforced by signature)
    import inspect

    sig = inspect.signature(LLMProvider.synthesize_response)

    assert "db" not in sig.parameters
    assert "patient_id" not in sig.parameters
    assert "user_id" not in sig.parameters
    assert "context" in sig.parameters
    assert "evidence" in sig.parameters

    # Check typing
    assert sig.parameters["context"].annotation == StructuredHealthContext
    assert sig.parameters["evidence"].annotation == EvidenceResult
    assert sig.parameters["safety_state"].annotation == SafetyGuardrailState
