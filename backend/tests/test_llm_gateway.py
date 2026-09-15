import uuid
from datetime import datetime, timezone

import pytest

from app.api.health_inquiry import get_llm_provider
from app.core.config import Settings
from app.core.llm import LLMProvider, MockLLMProvider, SynthesisResult
from app.core.llm_adapters.openai import OpenAIProvider
from app.core.llm_gateway import LLMConfigurationError, LLMGateway, get_llm_gateway
from app.health.evidence_evaluator import EvidenceResult
from app.health.inquiry_context import StructuredHealthContext
from app.health.safety_guardrails import SAFETY_ADVISORY
from app.schemas.condition import ConditionResponse
from app.schemas.inquiry import (
    EvidenceStatus,
    InquiryTarget,
    SafetyGuardrailState,
)


@pytest.fixture
def dummy_context() -> StructuredHealthContext:
    now = datetime.now(timezone.utc)
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
        recent_timeline_events=[],
    )


@pytest.fixture
def dummy_target() -> InquiryTarget:
    return InquiryTarget(
        target_domain="conditions",
        target_entity="Asthma",
        requested_attributes=["name"],
    )


@pytest.fixture
def dummy_evidence(dummy_context: StructuredHealthContext) -> EvidenceResult:
    return EvidenceResult(
        status=EvidenceStatus.SUFFICIENT,
        matched_records=dummy_context.conditions,
        matched_fields=["name"],
        missing_fields=[],
        temporal_interpretation="all",
        evidence_directive="All requested information is recorded.",
    )


def test_gateway_default_configuration_resolves_mock():
    """Default settings (LLM_PROVIDER='mock') should resolve MockLLMProvider."""
    default_settings = Settings(LLM_PROVIDER="mock")
    gateway = LLMGateway(settings=default_settings)
    assert isinstance(gateway.provider, MockLLMProvider)


@pytest.mark.asyncio
async def test_gateway_explicit_mock_provider_synthesis(
    dummy_context: StructuredHealthContext,
    dummy_target: InquiryTarget,
    dummy_evidence: EvidenceResult,
):
    """Explicit LLM_PROVIDER='mock' executes deterministic synthesis correctly."""
    settings = Settings(LLM_PROVIDER="mock")
    gateway = LLMGateway(settings=settings)

    safety = SafetyGuardrailState(triggered=False)
    result = await gateway.synthesize_response(
        query="Do I have asthma?",
        target=dummy_target,
        context=dummy_context,
        evidence=dummy_evidence,
        safety_state=safety,
    )

    assert isinstance(result, SynthesisResult)
    assert "Records confirm Asthma" in result.answer_text
    assert len(result.cited_record_ids) == 1


def test_gateway_openai_valid_configuration():
    """LLM_PROVIDER='openai' with valid key and model resolves OpenAIProvider."""
    settings = Settings(
        LLM_PROVIDER="openai",
        LLM_API_KEY="sk-test-secret-key",
        LLM_MODEL="gpt-4o-mini",
        LLM_TIMEOUT_SECONDS=15.0,
        LLM_MAX_RETRIES=3,
    )
    gateway = LLMGateway(settings=settings)
    assert isinstance(gateway.provider, OpenAIProvider)
    assert gateway.provider.api_key == "sk-test-secret-key"
    assert gateway.provider.model == "gpt-4o-mini"
    assert gateway.provider.timeout_seconds == 15.0
    assert gateway.provider.max_retries == 3


def test_gateway_openai_missing_api_key_raises_error():
    """LLM_PROVIDER='openai' with missing API key must fail visibly with error."""
    settings = Settings(
        LLM_PROVIDER="openai",
        LLM_API_KEY="",
        LLM_MODEL="gpt-4o-mini",
    )
    with pytest.raises(LLMConfigurationError, match="LLM_API_KEY is required"):
        LLMGateway(settings=settings)


def test_gateway_openai_whitespace_api_key_raises_error():
    """LLM_PROVIDER='openai' with whitespace-only key must raise configuration error."""
    settings = Settings(
        LLM_PROVIDER="openai",
        LLM_API_KEY="   ",
        LLM_MODEL="gpt-4o-mini",
    )
    with pytest.raises(LLMConfigurationError, match="LLM_API_KEY is required"):
        LLMGateway(settings=settings)


def test_gateway_openai_missing_model_raises_error():
    """LLM_PROVIDER='openai' with empty model must raise configuration error."""
    settings = Settings(
        LLM_PROVIDER="openai",
        LLM_API_KEY="sk-test-valid-key",
        LLM_MODEL="",
    )
    with pytest.raises(LLMConfigurationError, match="LLM_MODEL is required"):
        LLMGateway(settings=settings)


def test_gateway_unsupported_provider_raises_error():
    """Unsupported provider names must fail visibly with clear error message."""
    for unsupported in ["anthropic", "gemini", "llama", "unknown"]:
        settings = Settings(LLM_PROVIDER=unsupported)
        with pytest.raises(
            LLMConfigurationError, match=f"Unsupported LLM_PROVIDER '{unsupported}'"
        ):
            LLMGateway(settings=settings)


def test_gateway_empty_provider_raises_error():
    """Empty LLM_PROVIDER setting must raise configuration error."""
    settings = Settings(LLM_PROVIDER="")
    with pytest.raises(LLMConfigurationError, match="cannot be empty"):
        LLMGateway(settings=settings)


@pytest.mark.asyncio
async def test_gateway_defense_in_depth_safety_preflight_short_circuit(
    dummy_context: StructuredHealthContext,
    dummy_target: InquiryTarget,
    dummy_evidence: EvidenceResult,
):
    """
    When safety is triggered, the gateway immediately returns the safety advisory
    with NO call to the underlying provider.
    """

    class ExplodingProvider(LLMProvider):
        """Provider that explodes if called to prove short-circuiting."""

        async def synthesize_response(
            self, query, target, context, evidence, safety_state
        ) -> SynthesisResult:
            raise RuntimeError(
                "Underlying provider was called when safety was triggered!"
            )

    gateway = LLMGateway(provider=ExplodingProvider())
    safety = SafetyGuardrailState(triggered=True, advisory_message=SAFETY_ADVISORY)

    # Must NOT raise RuntimeError from ExplodingProvider
    result = await gateway.synthesize_response(
        query="I have severe crushing chest pain",
        target=dummy_target,
        context=dummy_context,
        evidence=dummy_evidence,
        safety_state=safety,
    )

    assert isinstance(result, SynthesisResult)
    assert result.answer_text == SAFETY_ADVISORY
    assert result.cited_record_ids == []


@pytest.mark.asyncio
async def test_gateway_safety_preflight_with_openai_provider(
    dummy_context: StructuredHealthContext,
    dummy_target: InquiryTarget,
    dummy_evidence: EvidenceResult,
):
    """
    Verifies that when OpenAIProvider is configured (which raises NotImplementedError
    in Slice 1), a safety-triggered inquiry returns the advisory cleanly without
    raising NotImplementedError.
    """
    settings = Settings(
        LLM_PROVIDER="openai",
        LLM_API_KEY="sk-valid-test-key",
        LLM_MODEL="gpt-4o-mini",
    )
    gateway = LLMGateway(settings=settings)

    safety = SafetyGuardrailState(triggered=True, advisory_message=SAFETY_ADVISORY)
    result = await gateway.synthesize_response(
        query="I have sudden facial drooping and weakness",
        target=dummy_target,
        context=dummy_context,
        evidence=dummy_evidence,
        safety_state=safety,
    )

    assert result.answer_text == SAFETY_ADVISORY
    assert result.cited_record_ids == []


@pytest.mark.asyncio
async def test_gateway_safety_preflight_missing_advisory_raises_error(
    dummy_context: StructuredHealthContext,
    dummy_target: InquiryTarget,
    dummy_evidence: EvidenceResult,
):
    """Triggered safety state without an advisory message must raise ValueError."""
    settings = Settings(LLM_PROVIDER="mock")
    gateway = LLMGateway(settings=settings)

    invalid_safety = SafetyGuardrailState(triggered=True, advisory_message=None)
    with pytest.raises(ValueError, match="missing advisory message"):
        await gateway.synthesize_response(
            query="chest pain",
            target=dummy_target,
            context=dummy_context,
            evidence=dummy_evidence,
            safety_state=invalid_safety,
        )


def test_gateway_implements_llm_provider_protocol():
    """LLMGateway must satisfy the LLMProvider protocol signature."""
    import inspect

    gateway = LLMGateway()
    assert hasattr(gateway, "synthesize_response")
    gateway_sig = inspect.signature(gateway.synthesize_response)
    proto_sig = inspect.signature(LLMProvider.synthesize_response)

    proto_params = [p for p in proto_sig.parameters if p != "self"]
    for param in proto_params:
        assert param in gateway_sig.parameters
        assert (
            gateway_sig.parameters[param].annotation
            == proto_sig.parameters[param].annotation
        )


def test_get_llm_gateway_factory():
    """get_llm_gateway returns a valid LLMGateway instance."""
    gw = get_llm_gateway()
    assert isinstance(gw, LLMGateway)


def test_get_llm_provider_wiring():
    """get_llm_provider in health_inquiry API returns LLMGateway."""
    provider = get_llm_provider()
    assert isinstance(provider, LLMGateway)
