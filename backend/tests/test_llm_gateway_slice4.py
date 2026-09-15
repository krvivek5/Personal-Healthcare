from unittest.mock import AsyncMock, patch

import pytest

from app.core.llm import LLMProvider, SynthesisResult
from app.core.llm_exceptions import (
    LLMMalformedResponseError,
    LLMProvider5xxError,
    LLMProviderRefusalError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.core.llm_gateway import LLMGateway
from app.health.evidence_evaluator import EvidenceResult
from app.health.inquiry_context import StructuredHealthContext
from app.schemas.inquiry import EvidenceStatus, InquiryTarget, SafetyGuardrailState


class StubFailingProvider(LLMProvider):
    def __init__(self, exception_to_raise: Exception, max_retries: int = 2):
        self.exception_to_raise = exception_to_raise
        self.max_retries = max_retries
        self.call_count = 0

    async def synthesize_response(
        self, query, target, context, evidence, safety_state
    ) -> SynthesisResult:
        self.call_count += 1
        raise self.exception_to_raise


@pytest.fixture
def dummy_context() -> StructuredHealthContext:
    return StructuredHealthContext(
        profile=None,
        conditions=[],
        medications=[],
        allergies=[],
        symptoms=[],
        goals=[],
        recent_timeline_events=[],
    )


@pytest.fixture
def dummy_target() -> InquiryTarget:
    return InquiryTarget(target_domain="profile")


@pytest.fixture
def dummy_evidence() -> EvidenceResult:
    return EvidenceResult(
        status=EvidenceStatus.INSUFFICIENT,
        matched_records=[],
        evidence_directive="Fallback deterministic response",
    )


@pytest.mark.asyncio
async def test_gateway_timeout_fallback(dummy_context, dummy_target, dummy_evidence):
    """Timeout should NOT retry, but immediately fallback to deterministic synthesis."""
    provider = StubFailingProvider(LLMTimeoutError())
    gateway = LLMGateway(provider=provider)
    safety = SafetyGuardrailState(triggered=False)

    result = await gateway.synthesize_response(
        query="test",
        target=dummy_target,
        context=dummy_context,
        evidence=dummy_evidence,
        safety_state=safety,
    )

    assert provider.call_count == 1
    assert result.answer_text == dummy_evidence.evidence_directive


@pytest.mark.asyncio
async def test_gateway_429_retry_then_fallback(
    dummy_context, dummy_target, dummy_evidence
):
    """HTTP 429 Rate Limit should retry up to max_retries, then fallback."""
    provider = StubFailingProvider(LLMRateLimitError(), max_retries=2)
    gateway = LLMGateway(provider=provider)
    safety = SafetyGuardrailState(triggered=False)

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await gateway.synthesize_response(
            query="test",
            target=dummy_target,
            context=dummy_context,
            evidence=dummy_evidence,
            safety_state=safety,
        )

    # Call count should be max_retries + 1 (initial + 2 retries)
    assert provider.call_count == 3
    assert mock_sleep.call_count == 2
    assert result.answer_text == dummy_evidence.evidence_directive


@pytest.mark.asyncio
async def test_gateway_5xx_retry_then_fallback(
    dummy_context, dummy_target, dummy_evidence
):
    """HTTP 5xx should retry, then fallback."""
    provider = StubFailingProvider(LLMProvider5xxError(), max_retries=1)
    gateway = LLMGateway(provider=provider)
    safety = SafetyGuardrailState(triggered=False)

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await gateway.synthesize_response(
            query="test",
            target=dummy_target,
            context=dummy_context,
            evidence=dummy_evidence,
            safety_state=safety,
        )

    # Initial + 1 retry
    assert provider.call_count == 2
    assert mock_sleep.call_count == 1
    assert result.answer_text == dummy_evidence.evidence_directive


@pytest.mark.asyncio
async def test_gateway_malformed_response_fallback(
    dummy_context, dummy_target, dummy_evidence
):
    """Malformed response should NOT retry, but immediately fallback."""
    provider = StubFailingProvider(LLMMalformedResponseError())
    gateway = LLMGateway(provider=provider)
    safety = SafetyGuardrailState(triggered=False)

    result = await gateway.synthesize_response(
        query="test",
        target=dummy_target,
        context=dummy_context,
        evidence=dummy_evidence,
        safety_state=safety,
    )

    assert provider.call_count == 1
    assert result.answer_text == dummy_evidence.evidence_directive


@pytest.mark.asyncio
async def test_gateway_provider_refusal_fallback(
    dummy_context, dummy_target, dummy_evidence
):
    """Provider refusal should NOT retry, but immediately fallback."""
    provider = StubFailingProvider(LLMProviderRefusalError())
    gateway = LLMGateway(provider=provider)
    safety = SafetyGuardrailState(triggered=False)

    result = await gateway.synthesize_response(
        query="test",
        target=dummy_target,
        context=dummy_context,
        evidence=dummy_evidence,
        safety_state=safety,
    )

    assert provider.call_count == 1
    assert result.answer_text == dummy_evidence.evidence_directive
