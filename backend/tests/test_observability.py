"""
Slice 5: PHI-safe Observability Unit Tests

Verifies:
- Telemetry fields are populated correctly for each synthesis path.
- PHI never enters telemetry log lines.
- Fallback events are distinguishable from normal mock mode.
- Safety-preflight path emits correct finish_reason.
- No raw query text, health context, or API keys appear in log output.
"""

import logging
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import Settings
from app.core.llm import MockLLMProvider, SynthesisResult
from app.core.llm_exceptions import LLMRateLimitError, LLMTimeoutError
from app.core.llm_gateway import LLMGateway
from app.core.llm_telemetry import FinishReason, GatewayTelemetry
from app.health.evidence_evaluator import EvidenceResult
from app.health.inquiry_context import StructuredHealthContext
from app.health.safety_guardrails import SAFETY_ADVISORY
from app.schemas.condition import ConditionResponse
from app.schemas.inquiry import (
    EvidenceStatus,
    InquiryTarget,
    SafetyGuardrailState,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def dummy_condition() -> ConditionResponse:
    return ConditionResponse(
        id=uuid.uuid4(),
        patient_id=uuid.uuid4(),
        name="Asthma",
        status="active",
        is_chronic=False,
        recorded_at=_now(),
        source_type="PATIENT_REPORTED",
        source_id=None,
        verification_state="UNVERIFIED",
        created_at=_now(),
        updated_at=_now(),
    )


@pytest.fixture
def dummy_context(dummy_condition: ConditionResponse) -> StructuredHealthContext:
    return StructuredHealthContext(
        profile=None,
        conditions=[dummy_condition],
        medications=[],
        allergies=[],
        symptoms=[],
        goals=[],
        recent_timeline_events=[],
    )


@pytest.fixture
def dummy_target() -> InquiryTarget:
    return InquiryTarget(target_domain="conditions", target_entity="Asthma")


@pytest.fixture
def dummy_evidence(dummy_condition: ConditionResponse) -> EvidenceResult:
    return EvidenceResult(
        status=EvidenceStatus.SUFFICIENT,
        matched_records=[dummy_condition],
        matched_fields=["name"],
        evidence_directive="All requested information is recorded.",
    )


@pytest.fixture
def empty_evidence() -> EvidenceResult:
    return EvidenceResult(
        status=EvidenceStatus.INSUFFICIENT,
        matched_records=[],
        evidence_directive="conditions are not recorded.",
    )


def _no_safety() -> SafetyGuardrailState:
    return SafetyGuardrailState(triggered=False)


# ---------------------------------------------------------------------------
# Helper: capture log output
# ---------------------------------------------------------------------------


class LogCapture(logging.Handler):
    """Simple in-memory log handler for test verification."""

    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)
        self.messages.append(self.format(record))


# ---------------------------------------------------------------------------
# Telemetry dataclass tests
# ---------------------------------------------------------------------------


def test_telemetry_default_inquiry_id_is_unique():
    """Each GatewayTelemetry instance should get a unique inquiry_id."""
    t1 = GatewayTelemetry()
    t2 = GatewayTelemetry()
    assert t1.inquiry_id != t2.inquiry_id
    assert isinstance(t1.inquiry_id, uuid.UUID)


def test_telemetry_finish_reason_enum_values():
    """All FinishReason values must be strings suitable for log emission."""
    for reason in FinishReason:
        assert isinstance(reason.value, str)
        assert len(reason.value) > 0


def test_telemetry_no_phi_fields():
    """
    GatewayTelemetry must NOT contain fields for:
    query, health_context, patient_id, api_key, prompt_text, answer_text.
    """
    t = GatewayTelemetry()
    phi_field_names = {
        "query",
        "health_context",
        "patient_id",
        "api_key",
        "prompt_text",
        "answer_text",
        "patient_name",
        "date_of_birth",
    }
    telemetry_fields = {f.name for f in t.__dataclass_fields__.values()}
    for phi_field in phi_field_names:
        assert phi_field not in telemetry_fields, (
            f"PHI field '{phi_field}' must not exist in GatewayTelemetry"
        )


# ---------------------------------------------------------------------------
# Gateway telemetry emission tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_telemetry_emitted_on_mock_success(
    dummy_context: StructuredHealthContext,
    dummy_target: InquiryTarget,
    dummy_evidence: EvidenceResult,
):
    """Successful mock synthesis must emit a telemetry log line."""
    handler = LogCapture()
    handler.setFormatter(logging.Formatter("%(message)s"))
    gw_logger = logging.getLogger("app.core.llm_gateway")
    gw_logger.addHandler(handler)
    gw_logger.setLevel(logging.DEBUG)

    try:
        gateway = LLMGateway(provider=MockLLMProvider())
        await gateway.synthesize_response(
            query="Do I have asthma?",
            target=dummy_target,
            context=dummy_context,
            evidence=dummy_evidence,
            safety_state=_no_safety(),
        )
    finally:
        gw_logger.removeHandler(handler)

    telemetry_lines = [m for m in handler.messages if "llm_gateway_telemetry" in m]
    assert len(telemetry_lines) == 1

    line = telemetry_lines[0]
    assert "provider=mock" in line
    assert "finish_reason=stop" in line
    assert "fallback=False" in line


@pytest.mark.asyncio
async def test_telemetry_log_does_not_contain_phi(
    dummy_context: StructuredHealthContext,
    dummy_target: InquiryTarget,
    dummy_evidence: EvidenceResult,
):
    """
    PHI boundary verification: raw query text, patient condition names, and
    health context MUST NOT appear in telemetry log output.
    """
    handler = LogCapture()
    handler.setFormatter(logging.Formatter("%(message)s"))
    gw_logger = logging.getLogger("app.core.llm_gateway")
    gw_logger.addHandler(handler)
    gw_logger.setLevel(logging.DEBUG)

    raw_query = "Do I have Asthma condition right now?"
    try:
        gateway = LLMGateway(provider=MockLLMProvider())
        await gateway.synthesize_response(
            query=raw_query,
            target=dummy_target,
            context=dummy_context,
            evidence=dummy_evidence,
            safety_state=_no_safety(),
        )
    finally:
        gw_logger.removeHandler(handler)

    telemetry_lines = [m for m in handler.messages if "llm_gateway_telemetry" in m]
    assert len(telemetry_lines) == 1

    line = telemetry_lines[0]
    # Raw query text must NOT appear in telemetry
    assert raw_query not in line
    # Raw condition name from records must NOT appear in telemetry
    assert "Asthma condition right now" not in line
    # No API key patterns
    assert "sk-" not in line


@pytest.mark.asyncio
async def test_telemetry_safety_preflight_finish_reason(
    dummy_context: StructuredHealthContext,
    dummy_target: InquiryTarget,
    dummy_evidence: EvidenceResult,
):
    """Safety-preflight path must emit finish_reason=safety_preflight."""
    handler = LogCapture()
    handler.setFormatter(logging.Formatter("%(message)s"))
    gw_logger = logging.getLogger("app.core.llm_gateway")
    gw_logger.addHandler(handler)
    gw_logger.setLevel(logging.DEBUG)

    try:
        gateway = LLMGateway(provider=MockLLMProvider())
        safety = SafetyGuardrailState(triggered=True, advisory_message=SAFETY_ADVISORY)
        await gateway.synthesize_response(
            query="I have severe crushing chest pain",
            target=dummy_target,
            context=dummy_context,
            evidence=dummy_evidence,
            safety_state=safety,
        )
    finally:
        gw_logger.removeHandler(handler)

    telemetry_lines = [m for m in handler.messages if "llm_gateway_telemetry" in m]
    assert len(telemetry_lines) == 1
    assert "finish_reason=safety_preflight" in telemetry_lines[0]
    assert "fallback=False" in telemetry_lines[0]


@pytest.mark.asyncio
async def test_telemetry_fallback_is_distinguishable_from_normal_mock(
    dummy_context: StructuredHealthContext,
    dummy_target: InquiryTarget,
    dummy_evidence: EvidenceResult,
):
    """
    When a provider failure triggers the deterministic fallback, the telemetry
    must mark fallback=True. This distinguishes provider-failure fallback from
    intentional LLM_PROVIDER=mock mode (where fallback=False).
    """
    from app.core.llm import LLMProvider

    class AlwaysFailingProvider(LLMProvider):
        async def synthesize_response(
            self, query, target, context, evidence, safety_state
        ) -> SynthesisResult:
            raise LLMTimeoutError("simulated timeout")

    handler = LogCapture()
    handler.setFormatter(logging.Formatter("%(message)s"))
    gw_logger = logging.getLogger("app.core.llm_gateway")
    gw_logger.addHandler(handler)
    gw_logger.setLevel(logging.DEBUG)

    try:
        gateway = LLMGateway(provider=AlwaysFailingProvider())
        await gateway.synthesize_response(
            query="test query",
            target=dummy_target,
            context=dummy_context,
            evidence=dummy_evidence,
            safety_state=_no_safety(),
        )
    finally:
        gw_logger.removeHandler(handler)

    telemetry_lines = [m for m in handler.messages if "llm_gateway_telemetry" in m]
    assert len(telemetry_lines) == 1
    # Fallback must be explicitly flagged as True
    assert "fallback=True" in telemetry_lines[0]
    assert "finish_reason=fallback" in telemetry_lines[0]


@pytest.mark.asyncio
async def test_telemetry_retry_then_fallback_emits_single_telemetry(
    dummy_context: StructuredHealthContext,
    dummy_target: InquiryTarget,
    dummy_evidence: EvidenceResult,
):
    """
    When retryable errors exhaust all attempts, exactly ONE telemetry record
    must be emitted (for the final fallback outcome), not one per retry attempt.
    """
    from app.core.llm import LLMProvider

    class RateLimitProvider(LLMProvider):
        async def synthesize_response(
            self, query, target, context, evidence, safety_state
        ) -> SynthesisResult:
            raise LLMRateLimitError("simulated 429")

    handler = LogCapture()
    handler.setFormatter(logging.Formatter("%(message)s"))
    gw_logger = logging.getLogger("app.core.llm_gateway")
    gw_logger.addHandler(handler)
    gw_logger.setLevel(logging.DEBUG)

    try:
        settings = Settings(LLM_PROVIDER="mock")
        gateway = LLMGateway(settings=settings, provider=RateLimitProvider())
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await gateway.synthesize_response(
                query="test query",
                target=dummy_target,
                context=dummy_context,
                evidence=dummy_evidence,
                safety_state=_no_safety(),
            )
    finally:
        gw_logger.removeHandler(handler)

    telemetry_lines = [m for m in handler.messages if "llm_gateway_telemetry" in m]
    # Exactly one final telemetry record, not one-per-retry
    assert len(telemetry_lines) == 1
    assert "fallback=True" in telemetry_lines[0]


@pytest.mark.asyncio
async def test_telemetry_api_key_never_logged():
    """
    Paranoia test: configure a real-looking API key and assert it never
    appears in any log output from the gateway.
    """
    fake_api_key = "sk-test-supersecret-key-1234567890"
    settings = Settings(
        LLM_PROVIDER="openai",
        LLM_API_KEY=fake_api_key,
        LLM_MODEL="gpt-4o-mini",
    )

    handler = LogCapture()
    handler.setFormatter(logging.Formatter("%(message)s"))
    gw_logger = logging.getLogger("app.core.llm_gateway")
    gw_logger.addHandler(handler)
    gw_logger.setLevel(logging.DEBUG)

    try:
        gateway = LLMGateway(settings=settings)
        # Mock the OpenAI provider to avoid real network call
        gateway.provider.synthesize_response = AsyncMock(
            return_value=SynthesisResult(answer_text="ok", cited_record_ids=[])
        )
        context = StructuredHealthContext(
            profile=None,
            conditions=[],
            medications=[],
            allergies=[],
            symptoms=[],
            goals=[],
            recent_timeline_events=[],
        )
        await gateway.synthesize_response(
            query="test",
            target=InquiryTarget(target_domain="conditions"),
            context=context,
            evidence=EvidenceResult(
                status=EvidenceStatus.INSUFFICIENT,
                matched_records=[],
                evidence_directive="nothing recorded.",
            ),
            safety_state=_no_safety(),
        )
    finally:
        gw_logger.removeHandler(handler)

    # API key must NEVER appear in any log line
    for msg in handler.messages:
        assert fake_api_key not in msg, (
            "API key leaked into gateway log output — privacy violation"
        )
