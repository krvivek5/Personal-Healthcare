"""
PHI-safe gateway telemetry for LLM observability.

Records operational metadata only. Under NO circumstances may this module log
or store raw health context, patient records, user queries, prompts, or API keys.
"""

import uuid
from dataclasses import dataclass, field
from enum import Enum


class FinishReason(str, Enum):
    STOP = "stop"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    TIMEOUT = "timeout"
    ERROR = "error"
    SAFETY_PREFLIGHT = "safety_preflight"
    FALLBACK = "fallback"


@dataclass
class GatewayTelemetry:
    """
    Operational telemetry record for a single gateway synthesis call.

    PHI constraints:
    - inquiry_id is a transient correlation ID assigned per-request,
      never tied to a persistent patient identifier in this record.
    - provider_used, model_version, latency, tokens, and finish_reason
      are purely operational fields.
    - No field in this dataclass may contain: patient name, DOB, conditions,
      medications, raw query text, prompt text, or any health record content.
    """

    inquiry_id: uuid.UUID = field(default_factory=uuid.uuid4)
    provider_used: str = ""
    model_version: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    external_latency_ms: int = 0
    finish_reason: FinishReason = FinishReason.STOP
    fallback_triggered: bool = False
    citations_emitted_count: int = 0
    citations_verified_count: int = 0
