import json
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.core.llm_adapters.openai import OpenAIProvider
from app.core.llm_exceptions import (
    LLMMalformedResponseError,
    LLMProviderError,
    LLMTimeoutError,
)
from app.health.evidence_evaluator import EvidenceResult
from app.health.inquiry_context import StructuredHealthContext
from app.schemas.health_profile import HealthProfileResponse
from app.schemas.inquiry import (
    EvidenceStatus,
    InquiryTarget,
    SafetyGuardrailState,
)


@pytest.fixture
def base_context():
    patient_id = uuid.uuid4()
    profile_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    profile = HealthProfileResponse(
        id=profile_id,
        patient_id=patient_id,
        biological_sex="male",
        date_of_birth=date(1985, 10, 15),
        blood_group="O+",
        height_cm=180.0,
        notes="None",
        created_at=now,
        updated_at=now,
    )

    return StructuredHealthContext(profile=profile)


@pytest.fixture
def evidence_result():
    return EvidenceResult(
        status=EvidenceStatus.SUFFICIENT,
        evidence_directive="Focus on asthma records.",
        matched_records=[],
    )


def mock_openai_response(answer_text="Test answer", cited_references=None):
    if cited_references is None:
        cited_references = ["[REC-1]"]

    structured_content = json.dumps(
        {"answer_text": answer_text, "cited_references": cited_references}
    )

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": structured_content}}]
    }
    mock_resp.raise_for_status.return_value = None
    mock_resp.status_code = 200
    return mock_resp


@pytest.mark.asyncio
async def test_openai_adapter_payload_structure(base_context, evidence_result):
    """
    Verify exact request payload structure, sanitized context, and lack of
    prohibited IDs.
    """
    provider = OpenAIProvider(api_key="test-key")

    target = InquiryTarget(target_domain="profile")
    safety_state = SafetyGuardrailState(triggered=False)

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = mock_openai_response()

        await provider.synthesize_response(
            query="Tell me about my profile",
            target=target,
            context=base_context,
            evidence=evidence_result,
            safety_state=safety_state,
        )

        mock_post.assert_called_once()

        # Check payload
        _, kwargs = mock_post.call_args
        payload = kwargs["json"]
        headers = kwargs["headers"]

        assert headers["Authorization"] == "Bearer test-key"
        assert payload["model"] == "gpt-4o-mini"
        assert "response_format" in payload
        assert payload["response_format"]["type"] == "json_schema"

        messages = payload["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "Tell me about my profile"

        system_content = messages[0]["content"]

        # Verify sanitized context appears
        assert "[REC-1]" in system_content
        assert "biological_sex: male" in system_content

        # Verify prohibited identifiers cannot appear
        assert str(base_context.profile.id) not in system_content
        assert str(base_context.profile.patient_id) not in system_content
        assert base_context.profile.date_of_birth.isoformat() not in system_content


@pytest.mark.asyncio
async def test_openai_adapter_structured_parsing_and_reconciliation(
    base_context, evidence_result
):
    """
    Verify structured response parsing and [REC-N] -> UUID reconciliation.
    """
    provider = OpenAIProvider(api_key="test-key")
    target = InquiryTarget(target_domain="profile")
    safety_state = SafetyGuardrailState(triggered=False)

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = mock_openai_response(
            answer_text="You are a male.", cited_references=["[REC-1]"]
        )

        result = await provider.synthesize_response(
            query="What is my sex?",
            target=target,
            context=base_context,
            evidence=evidence_result,
            safety_state=safety_state,
        )

        assert result.answer_text == "You are a male."
        # REC-1 should map to the profile UUID
        assert len(result.cited_record_ids) == 1
        assert result.cited_record_ids[0] == base_context.profile.id


@pytest.mark.asyncio
async def test_openai_adapter_foreign_tokens_discarded(base_context, evidence_result):
    """
    Verify unknown/foreign reference tokens are discarded.
    """
    provider = OpenAIProvider(api_key="test-key")
    target = InquiryTarget(target_domain="profile")
    safety_state = SafetyGuardrailState(triggered=False)

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = mock_openai_response(
            cited_references=["[REC-1]", "[REC-999]", "UNKNOWN"]
        )

        result = await provider.synthesize_response(
            query="What is my sex?",
            target=target,
            context=base_context,
            evidence=evidence_result,
            safety_state=safety_state,
        )

        # Only REC-1 is valid
        assert len(result.cited_record_ids) == 1
        assert result.cited_record_ids[0] == base_context.profile.id


@pytest.mark.asyncio
async def test_openai_adapter_malformed_response_fails(base_context, evidence_result):
    """
    Verify malformed provider responses fail safely.
    """
    provider = OpenAIProvider(api_key="test-key")
    target = InquiryTarget(target_domain="profile")
    safety_state = SafetyGuardrailState(triggered=False)

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Not JSON"}}]
        }
        mock_resp.raise_for_status.return_value = None
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        with pytest.raises(LLMMalformedResponseError):
            await provider.synthesize_response(
                query="What is my sex?",
                target=target,
                context=base_context,
                evidence=evidence_result,
                safety_state=safety_state,
            )


@pytest.mark.asyncio
async def test_openai_adapter_timeout_behavior(base_context, evidence_result):
    """
    Verify timeout behavior at the adapter boundary.
    """
    provider = OpenAIProvider(api_key="test-key", timeout_seconds=0.1)
    target = InquiryTarget(target_domain="profile")
    safety_state = SafetyGuardrailState(triggered=False)

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = httpx.TimeoutException("Timeout")

        with pytest.raises(LLMTimeoutError):
            await provider.synthesize_response(
                query="What is my sex?",
                target=target,
                context=base_context,
                evidence=evidence_result,
                safety_state=safety_state,
            )


@pytest.mark.asyncio
async def test_openai_adapter_generic_request_error(base_context, evidence_result):
    """
    Verify generic request errors are normalized to LLMProviderError.
    """
    provider = OpenAIProvider(api_key="test-key")
    target = InquiryTarget(target_domain="profile")
    safety_state = SafetyGuardrailState(triggered=False)

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.side_effect = httpx.RequestError(
            "Connection failed", request=MagicMock()
        )

        with pytest.raises(LLMProviderError) as exc_info:
            await provider.synthesize_response(
                query="What is my sex?",
                target=target,
                context=base_context,
                evidence=evidence_result,
                safety_state=safety_state,
            )
        assert "Provider network error" in str(exc_info.value)


def mock_http_status_error(status_code: int, json_data: dict = None):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data or {}

    def raise_for_status():
        raise httpx.HTTPStatusError(
            "HTTP Error", request=MagicMock(), response=mock_resp
        )

    mock_resp.raise_for_status.side_effect = raise_for_status
    return mock_resp


@pytest.mark.asyncio
async def test_openai_adapter_400_explicit_refusal(base_context, evidence_result):
    """400 + explicit refusal code should raise LLMProviderRefusalError."""
    from app.core.llm_exceptions import LLMProviderRefusalError

    provider = OpenAIProvider(api_key="test-key")
    target = InquiryTarget(target_domain="profile")
    safety_state = SafetyGuardrailState(triggered=False)

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = mock_http_status_error(
            400, {"error": {"code": "content_filter"}}
        )

        with pytest.raises(LLMProviderRefusalError):
            await provider.synthesize_response(
                query="What is my sex?",
                target=target,
                context=base_context,
                evidence=evidence_result,
                safety_state=safety_state,
            )


@pytest.mark.asyncio
async def test_openai_adapter_400_generic_error(base_context, evidence_result):
    """400 without explicit refusal code should raise generic LLMProviderError."""
    provider = OpenAIProvider(api_key="test-key")
    target = InquiryTarget(target_domain="profile")
    safety_state = SafetyGuardrailState(triggered=False)

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = mock_http_status_error(
            400, {"error": {"code": "invalid_request"}}
        )

        with pytest.raises(LLMProviderError) as exc_info:
            await provider.synthesize_response(
                query="What is my sex?",
                target=target,
                context=base_context,
                evidence=evidence_result,
                safety_state=safety_state,
            )
        # Should not be a refusal error
        from app.core.llm_exceptions import LLMProviderRefusalError

        assert not isinstance(exc_info.value, LLMProviderRefusalError)


@pytest.mark.asyncio
async def test_openai_adapter_401_configuration_error(base_context, evidence_result):
    """401 should raise LLMConfigurationError."""
    from app.core.llm_exceptions import LLMConfigurationError

    provider = OpenAIProvider(api_key="test-key")
    target = InquiryTarget(target_domain="profile")
    safety_state = SafetyGuardrailState(triggered=False)

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = mock_http_status_error(401)

        with pytest.raises(LLMConfigurationError):
            await provider.synthesize_response(
                query="What is my sex?",
                target=target,
                context=base_context,
                evidence=evidence_result,
                safety_state=safety_state,
            )


@pytest.mark.asyncio
async def test_openai_adapter_429_rate_limit(base_context, evidence_result):
    """429 should raise LLMRateLimitError."""
    from app.core.llm_exceptions import LLMRateLimitError

    provider = OpenAIProvider(api_key="test-key")
    target = InquiryTarget(target_domain="profile")
    safety_state = SafetyGuardrailState(triggered=False)

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = mock_http_status_error(429)

        with pytest.raises(LLMRateLimitError):
            await provider.synthesize_response(
                query="What is my sex?",
                target=target,
                context=base_context,
                evidence=evidence_result,
                safety_state=safety_state,
            )


@pytest.mark.asyncio
async def test_openai_adapter_500_provider_error(base_context, evidence_result):
    """500 should raise LLMProvider5xxError."""
    from app.core.llm_exceptions import LLMProvider5xxError

    provider = OpenAIProvider(api_key="test-key")
    target = InquiryTarget(target_domain="profile")
    safety_state = SafetyGuardrailState(triggered=False)

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = mock_http_status_error(500)

        with pytest.raises(LLMProvider5xxError):
            await provider.synthesize_response(
                query="What is my sex?",
                target=target,
                context=base_context,
                evidence=evidence_result,
                safety_state=safety_state,
            )
