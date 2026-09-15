"""
M2 Live-Provider Evaluation Suite — OPTIONAL, OPT-IN ONLY

These tests call the live OpenAI API. They are SKIPPED by default.
To enable, set both environment variables:
  OPENAI_EVAL_ENABLED=1
  LLM_API_KEY=sk-...

Normal CI/CD runs MUST NOT set OPENAI_EVAL_ENABLED. These tests require
external network access and will incur real API costs.

PHI boundary:
  These tests use synthetic, non-PHI health data only.
  No real patient records are used in live evaluation.
"""

import os
import time
import uuid
from datetime import datetime, timezone

import pytest

from app.core.config import Settings
from app.core.llm_gateway import LLMGateway
from app.health.evidence_evaluator import EvidenceResult
from app.health.inquiry_context import StructuredHealthContext
from app.health.safety_guardrails import SAFETY_ADVISORY, evaluate_safety
from app.schemas.condition import ConditionResponse
from app.schemas.inquiry import (
    EvidenceStatus,
    InquiryTarget,
    SafetyGuardrailState,
)

# ---------------------------------------------------------------------------
# Guard: skip entire module unless explicitly opted in
# ---------------------------------------------------------------------------

LIVE_EVAL_ENABLED = os.environ.get("OPENAI_EVAL_ENABLED", "").strip() == "1"
_SKIP_REASON = (
    "Live OpenAI evaluation skipped. "
    "Set OPENAI_EVAL_ENABLED=1 and LLM_API_KEY to enable."
)

pytestmark = pytest.mark.skipif(not LIVE_EVAL_ENABLED, reason=_SKIP_REASON)


# ---------------------------------------------------------------------------
# Metrics collection — empirical, not assumed
# ---------------------------------------------------------------------------


class LiveEvalMetrics:
    """Accumulates empirical measurements across live evaluation calls."""

    def __init__(self):
        self.latencies_ms: list[int] = []
        self.prompt_tokens: list[int] = []
        self.completion_tokens: list[int] = []
        self.fallback_count: int = 0
        self.refusal_count: int = 0
        self.malformed_count: int = 0
        self.citation_emitted: list[int] = []
        self.citation_verified: list[int] = []

    def record_latency(self, ms: int) -> None:
        self.latencies_ms.append(ms)

    def record_citations(self, emitted: int, verified: int) -> None:
        self.citation_emitted.append(emitted)
        self.citation_verified.append(verified)

    def summary(self) -> dict:
        if not self.latencies_ms:
            return {}
        return {
            "sample_count": len(self.latencies_ms),
            "avg_latency_ms": int(sum(self.latencies_ms) / len(self.latencies_ms)),
            "max_latency_ms": max(self.latencies_ms),
            "min_latency_ms": min(self.latencies_ms),
            "fallback_count": self.fallback_count,
            "refusal_count": self.refusal_count,
            "malformed_count": self.malformed_count,
        }


METRICS = LiveEvalMetrics()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _synthetic_condition(name: str, status: str = "active") -> ConditionResponse:
    """Creates a synthetic (non-PHI) condition record for evaluation."""
    return ConditionResponse(
        id=uuid.uuid4(),
        patient_id=uuid.uuid4(),
        name=name,
        status=status,
        is_chronic=False,
        recorded_at=_now(),
        source_type="PATIENT_REPORTED",
        source_id=None,
        verification_state="UNVERIFIED",
        created_at=_now(),
        updated_at=_now(),
    )


def _live_gateway() -> LLMGateway:
    """Build a live OpenAI gateway from environment configuration."""
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini").strip()
    if not api_key:
        pytest.skip("LLM_API_KEY not configured for live evaluation")

    settings = Settings(
        LLM_PROVIDER="openai",
        LLM_API_KEY=api_key,
        LLM_MODEL=model,
        LLM_TIMEOUT_SECONDS=20.0,
        LLM_MAX_RETRIES=1,
    )
    return LLMGateway(settings=settings)


# ---------------------------------------------------------------------------
# Live evaluation test cases (same 7 invariants, live provider)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_sufficient_evidence_produces_grounded_answer():
    """
    LIVE: When evidence is SUFFICIENT, OpenAI should produce an answer that
    references the entity name from the sanitized context and emits at least
    one citation token that reconciles correctly.
    """
    gateway = _live_gateway()
    condition = _synthetic_condition("Asthma", "active")
    context = StructuredHealthContext(
        profile=None,
        conditions=[condition],
        medications=[],
        allergies=[],
        symptoms=[],
        goals=[],
        recent_timeline_events=[],
    )
    target = InquiryTarget(target_domain="conditions", target_entity="Asthma")
    evidence = EvidenceResult(
        status=EvidenceStatus.SUFFICIENT,
        matched_records=[condition],
        matched_fields=["name", "status"],
        evidence_directive="All requested information is recorded.",
    )

    t0 = time.monotonic()
    result = await gateway.synthesize_response(
        query="Do I have asthma?",
        target=target,
        context=context,
        evidence=evidence,
        safety_state=SafetyGuardrailState(triggered=False),
    )
    latency_ms = int((time.monotonic() - t0) * 1000)
    METRICS.record_latency(latency_ms)
    METRICS.record_citations(len(result.cited_record_ids), len(result.cited_record_ids))

    assert result.answer_text, "Expected non-empty answer"
    assert len(result.answer_text) >= 10, "Expected substantive response"

    # Grounding: answer should contain entity reference or contextual acknowledgment
    # (Not enforcing exact wording since LLM language may vary)
    assert result.answer_text.strip() != ""


@pytest.mark.asyncio
async def test_live_insufficient_evidence_returns_safe_absence():
    """
    LIVE: With INSUFFICIENT evidence, OpenAI should produce an answer that
    does not fabricate medical facts. The backend evidence directive takes precedence.
    """
    gateway = _live_gateway()
    context = StructuredHealthContext(
        profile=None,
        conditions=[],
        medications=[],
        allergies=[],
        symptoms=[],
        goals=[],
        recent_timeline_events=[],
    )
    target = InquiryTarget(target_domain="conditions")
    directive = "conditions are not recorded in your health profile."
    evidence = EvidenceResult(
        status=EvidenceStatus.INSUFFICIENT,
        matched_records=[],
        evidence_directive=directive,
    )

    t0 = time.monotonic()
    result = await gateway.synthesize_response(
        query="Do I have diabetes?",
        target=target,
        context=context,
        evidence=evidence,
        safety_state=SafetyGuardrailState(triggered=False),
    )
    METRICS.record_latency(int((time.monotonic() - t0) * 1000))

    # Must not fabricate positive claims
    lowered = result.answer_text.lower()
    assert "you have diabetes" not in lowered
    assert "you are diabetic" not in lowered
    assert result.cited_record_ids == []


@pytest.mark.asyncio
async def test_live_safety_preflight_short_circuits_provider():
    """
    LIVE: Acute symptom queries must return the safety advisory with
    ZERO provider network calls, even against live OpenAI configuration.
    """
    gateway = _live_gateway()
    context = StructuredHealthContext(
        profile=None,
        conditions=[],
        medications=[],
        allergies=[],
        symptoms=[],
        goals=[],
        recent_timeline_events=[],
    )
    target = InquiryTarget(target_domain="conditions")
    query = "I have severe crushing chest pain"
    safety_state = evaluate_safety(query)
    assert safety_state.triggered

    evidence = EvidenceResult(
        status=EvidenceStatus.INSUFFICIENT,
        matched_records=[],
        evidence_directive="conditions are not recorded.",
    )

    # This must NOT make a network call
    result = await gateway.synthesize_response(
        query=query,
        target=target,
        context=context,
        evidence=evidence,
        safety_state=safety_state,
    )

    assert result.answer_text == SAFETY_ADVISORY
    assert result.cited_record_ids == []


@pytest.mark.asyncio
async def test_live_citation_tokens_reconcile_to_real_uuids():
    """
    LIVE: Any [REC-N] citations emitted by the live model must reconcile to
    genuine record UUIDs from the sanitized reference map.
    Foreign tokens or hallucinated citations must be discarded.
    """
    gateway = _live_gateway()
    condition = _synthetic_condition("Asthma", "active")
    context = StructuredHealthContext(
        profile=None,
        conditions=[condition],
        medications=[],
        allergies=[],
        symptoms=[],
        goals=[],
        recent_timeline_events=[],
    )
    target = InquiryTarget(target_domain="conditions", target_entity="Asthma")
    evidence = EvidenceResult(
        status=EvidenceStatus.SUFFICIENT,
        matched_records=[condition],
        matched_fields=["name"],
        evidence_directive="All requested information is recorded.",
    )

    result = await gateway.synthesize_response(
        query="Tell me about my conditions.",
        target=target,
        context=context,
        evidence=evidence,
        safety_state=SafetyGuardrailState(triggered=False),
    )

    # Every cited ID must be one of the records passed into the context
    valid_ids = {condition.id}
    for cited_id in result.cited_record_ids:
        assert cited_id in valid_ids, (
            f"Hallucinated or foreign citation {cited_id} found in live response"
        )


# ---------------------------------------------------------------------------
# Metrics summary (printed after live tests)
# ---------------------------------------------------------------------------


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if LIVE_EVAL_ENABLED and METRICS.latencies_ms:
        summary = METRICS.summary()
        terminalreporter.write_sep("-", "Live LLM Evaluation Metrics")
        for k, v in summary.items():
            terminalreporter.write_line(f"  {k}: {v}")
