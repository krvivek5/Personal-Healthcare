import asyncio
import logging
import time
import uuid
from typing import Optional

from app.core.config import Settings
from app.core.config import settings as app_settings
from app.core.llm import LLMProvider, MockLLMProvider, SynthesisResult
from app.core.llm_adapters.openai import OpenAIProvider
from app.core.llm_exceptions import (
    LLMConfigurationError,
    LLMMalformedResponseError,
    LLMProvider5xxError,
    LLMProviderRefusalError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.core.llm_telemetry import FinishReason, GatewayTelemetry
from app.health.evidence_evaluator import EvidenceResult
from app.health.inquiry_context import StructuredHealthContext
from app.schemas.inquiry import (
    InquiryTarget,
    SafetyGuardrailState,
)

logger = logging.getLogger(__name__)


class LLMGateway(LLMProvider):
    """
    Provider-neutral gateway coordinating LLM response synthesis.

    Enforces:
    1. Defense-in-depth safety pre-flight: queries with triggered acute symptom
       patterns immediately return the standardized non-diagnostic advisory
       with no external LLM network call.
    2. Explicit provider dispatch:
       - LLM_PROVIDER=mock -> MockLLMProvider
       - LLM_PROVIDER=openai with valid configuration -> OpenAIProvider
       - LLM_PROVIDER=openai with missing/invalid configuration -> LLMConfigurationError
       - Unsupported LLM_PROVIDER -> LLMConfigurationError
    3. PHI-safe telemetry: emits operational metrics only; never logs raw health
       context, patient records, raw query text, or API keys.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        provider: Optional[LLMProvider] = None,
    ) -> None:
        self.settings = settings or app_settings
        if provider is not None:
            self.provider = provider
        else:
            self.provider = self._resolve_provider(self.settings)

    def _resolve_provider(self, cfg: Settings) -> LLMProvider:
        raw_provider = (cfg.LLM_PROVIDER or "").strip().lower()
        if not raw_provider:
            raise LLMConfigurationError("LLM_PROVIDER setting cannot be empty.")

        if raw_provider == "mock":
            return MockLLMProvider()

        if raw_provider == "openai":
            api_key = (cfg.LLM_API_KEY or "").strip()
            if not api_key:
                raise LLMConfigurationError(
                    "LLM_API_KEY is required when LLM_PROVIDER is 'openai'."
                )
            model = (cfg.LLM_MODEL or "").strip()
            if not model:
                raise LLMConfigurationError(
                    "LLM_MODEL is required when LLM_PROVIDER is 'openai'."
                )
            return OpenAIProvider(
                api_key=api_key,
                model=model,
                timeout_seconds=cfg.LLM_TIMEOUT_SECONDS,
                max_retries=cfg.LLM_MAX_RETRIES,
            )

        raise LLMConfigurationError(
            f"Unsupported LLM_PROVIDER '{cfg.LLM_PROVIDER}'. "
            "Supported providers are: 'mock', 'openai'."
        )

    def _provider_name(self) -> str:
        """Return a safe provider label for telemetry — never includes secrets."""
        if isinstance(self.provider, OpenAIProvider):
            return "openai"
        return "mock"

    def _model_version(self) -> str:
        """Return model identifier for telemetry; empty string for mock."""
        if isinstance(self.provider, OpenAIProvider):
            return self.provider.model
        return ""

    def _emit_telemetry(self, telemetry: GatewayTelemetry) -> None:
        """
        Emit PHI-safe structured operational telemetry.

        PHI BOUNDARY: Only non-PHI operational fields are logged here.
        Raw health context, patient records, queries, prompts, and API keys
        MUST NEVER appear in these log lines. Violations are a privacy incident.
        """
        logger.info(
            "llm_gateway_telemetry inquiry_id=%s provider=%s model=%s "
            "prompt_tokens=%d completion_tokens=%d total_tokens=%d "
            "latency_ms=%d finish_reason=%s fallback=%s "
            "citations_emitted=%d citations_verified=%d",
            telemetry.inquiry_id,
            telemetry.provider_used,
            telemetry.model_version,
            telemetry.prompt_tokens,
            telemetry.completion_tokens,
            telemetry.total_tokens,
            telemetry.external_latency_ms,
            telemetry.finish_reason.value,
            telemetry.fallback_triggered,
            telemetry.citations_emitted_count,
            telemetry.citations_verified_count,
        )

    async def synthesize_response(
        self,
        query: str,
        target: InquiryTarget,
        context: StructuredHealthContext,
        evidence: EvidenceResult,
        safety_state: SafetyGuardrailState,
    ) -> SynthesisResult:
        inquiry_id = uuid.uuid4()

        # Defense-in-depth safety pre-flight:
        # If an acute symptom pattern was triggered, intercept execution
        # immediately and return the standardized non-diagnostic advisory
        # with no external LLM network call.
        if safety_state.triggered:
            if not safety_state.advisory_message:
                raise ValueError("Safety state triggered but missing advisory message.")
            telemetry = GatewayTelemetry(
                inquiry_id=inquiry_id,
                provider_used=self._provider_name(),
                model_version=self._model_version(),
                finish_reason=FinishReason.SAFETY_PREFLIGHT,
                fallback_triggered=False,
            )
            self._emit_telemetry(telemetry)
            return SynthesisResult(
                answer_text=safety_state.advisory_message,
                cited_record_ids=[],
            )

        max_retries = 0
        if hasattr(self.provider, "max_retries"):
            max_retries = self.provider.max_retries

        attempt = 0
        finish_reason = FinishReason.STOP
        fallback_triggered = False

        while attempt <= max_retries:
            try:
                t0 = time.monotonic()
                result = await self.provider.synthesize_response(
                    query=query,
                    target=target,
                    context=context,
                    evidence=evidence,
                    safety_state=safety_state,
                )
                latency_ms = int((time.monotonic() - t0) * 1000)
                finish_reason = FinishReason.STOP

                telemetry = GatewayTelemetry(
                    inquiry_id=inquiry_id,
                    provider_used=self._provider_name(),
                    model_version=self._model_version(),
                    external_latency_ms=latency_ms,
                    finish_reason=finish_reason,
                    fallback_triggered=fallback_triggered,
                    citations_emitted_count=len(result.cited_record_ids),
                    citations_verified_count=len(result.cited_record_ids),
                )
                self._emit_telemetry(telemetry)
                return result

            except (LLMRateLimitError, LLMProvider5xxError) as e:
                attempt += 1
                if attempt > max_retries:
                    logger.warning(
                        "Exhausted retries for %s. Falling back.",
                        e.__class__.__name__,
                    )
                    finish_reason = FinishReason.ERROR
                    break

                import random

                sleep_time = min(30, (2**attempt) + random.uniform(0, 1))
                await asyncio.sleep(sleep_time)
            except LLMTimeoutError as e:
                logger.warning("Non-retryable %s. Falling back.", e.__class__.__name__)
                finish_reason = FinishReason.TIMEOUT
                break
            except (
                LLMMalformedResponseError,
                LLMProviderRefusalError,
            ) as e:
                logger.warning("Non-retryable %s. Falling back.", e.__class__.__name__)
                finish_reason = FinishReason.CONTENT_FILTER
                break
            except Exception as e:
                logger.error(
                    "Unexpected provider error %s. Falling back.",
                    e.__class__.__name__,
                    exc_info=True,
                )
                finish_reason = FinishReason.ERROR
                break

        # Deterministic fallback to M1 behavior
        fallback_triggered = True
        t0 = time.monotonic()
        mock_fallback = MockLLMProvider()
        result = await mock_fallback.synthesize_response(
            query=query,
            target=target,
            context=context,
            evidence=evidence,
            safety_state=safety_state,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        telemetry = GatewayTelemetry(
            inquiry_id=inquiry_id,
            provider_used=self._provider_name(),
            model_version=self._model_version(),
            external_latency_ms=latency_ms,
            finish_reason=FinishReason.FALLBACK,
            fallback_triggered=True,
            citations_emitted_count=len(result.cited_record_ids),
            citations_verified_count=len(result.cited_record_ids),
        )
        self._emit_telemetry(telemetry)
        return result


def get_llm_gateway() -> LLMGateway:
    """Dependency provider creating the active LLMGateway instance."""
    return LLMGateway()
