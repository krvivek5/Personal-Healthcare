import json
import uuid

import httpx

from app.core.llm import LLMProvider, SynthesisResult, _build_system_prompt
from app.core.llm_exceptions import (
    LLMConfigurationError,
    LLMMalformedResponseError,
    LLMProvider5xxError,
    LLMProviderError,
    LLMProviderRefusalError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.health.evidence_evaluator import EvidenceResult
from app.health.inquiry_context import StructuredHealthContext
from app.health.sanitized_context import (
    build_sanitized_context,
)
from app.schemas.inquiry import (
    InquiryTarget,
    SafetyGuardrailState,
)


class OpenAIProvider(LLMProvider):
    """
    OpenAI LLM provider adapter using httpx.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        timeout_seconds: float = 10.0,
        max_retries: int = 2,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.api_url = "https://api.openai.com/v1/chat/completions"

    async def synthesize_response(
        self,
        query: str,
        target: InquiryTarget,
        context: StructuredHealthContext,
        evidence: EvidenceResult,
        safety_state: SafetyGuardrailState,
    ) -> SynthesisResult:

        # 1. Safety pre-flight is assumed to be handled by LLMGateway.
        # Per requirements: "Safety-triggered requests must be handled by the
        # existing gateway pre-flight and must not reach the OpenAI adapter."

        # 2. Build sanitized context
        sanitized = build_sanitized_context(context, target)

        # 3. Construct system boundary and constraints
        system_base = _build_system_prompt()
        evidence_directive = evidence.evidence_directive
        temporal_scope = target.temporal_scope

        system_content = (
            f"{system_base}\n\n"
            f"EVIDENCE DIRECTIVE:\n{evidence_directive}\n\n"
            f"TEMPORAL SCOPE:\n{temporal_scope}\n\n"
            f"SANITIZED HEALTH CONTEXT:\n{sanitized.to_prompt_text()}"
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": query},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "health_synthesis_response",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "answer_text": {"type": "string"},
                            "cited_references": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["answer_text", "cited_references"],
                        "additionalProperties": False,
                    },
                },
            },
            "temperature": 0.0,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    self.api_url, headers=headers, json=payload
                )

                if response.status_code == 429:
                    raise LLMRateLimitError("Provider rate limit exceeded")
                if 500 <= response.status_code < 600:
                    raise LLMProvider5xxError(
                        f"Provider server error: {response.status_code}"
                    )

                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as e:
            raise LLMTimeoutError("Provider request timed out") from e
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403, 404):
                raise LLMConfigurationError(
                    f"Provider configuration error: {e.response.status_code}"
                ) from e
            if e.response.status_code == 400:
                # 400 Bad Request: check for explicit content-filter signal;
                # a bare 400 without that signal is a generic provider error.
                is_refusal = False
                try:
                    error_data = e.response.json().get("error", {})
                    if error_data.get("code") == "content_filter":
                        is_refusal = True
                except Exception:
                    pass
                if is_refusal:
                    raise LLMProviderRefusalError(
                        "Provider refused request due to content filter"
                    ) from e
                # Otherwise, it's a generic request error
                raise LLMProviderError(
                    f"Provider HTTP error: {e.response.status_code}"
                ) from e
            raise LLMProviderError(
                f"Provider HTTP error: {e.response.status_code}"
            ) from e
        except httpx.RequestError as e:
            raise LLMProviderError(f"Provider network error: {str(e)}") from e

        try:
            # OpenAI structured outputs return JSON string in the message content
            content_str = data["choices"][0]["message"]["content"]

            # Detect OpenAI content filter refusal (has 'refusal' key)
            if data["choices"][0]["message"].get("refusal"):
                raise LLMProviderRefusalError(
                    "Provider refused to answer due to safety filters."
                )

            parsed_content = json.loads(content_str)

            answer_text = parsed_content["answer_text"]
            cited_refs = parsed_content["cited_references"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
            raise LLMMalformedResponseError("Failed to parse structured output") from e

        # Reconcile references using the server-side map from Slice 2
        # Only map references to records that exist in the sanitized reference map.
        # Keep the resolved (token, uuid) pairs aligned so cited_tokens is
        # deterministically parallel to cited_record_ids.
        resolved_pairs: list[tuple[str, uuid.UUID]] = []
        seen: set[uuid.UUID] = set()
        for raw_token in cited_refs:
            token = raw_token.strip()
            matched_uuid = sanitized.reference_map.get(token)
            if not matched_uuid:
                clean = token.strip("[]")
                matched_uuid = sanitized.reference_map.get(
                    f"[{clean}]"
                ) or sanitized.reference_map.get(clean)
            if matched_uuid and matched_uuid not in seen:
                resolved_pairs.append((token, matched_uuid))
                seen.add(matched_uuid)

        resolved_tokens = [t for t, _ in resolved_pairs]
        resolved_uuids = [u for _, u in resolved_pairs]

        return SynthesisResult(
            answer_text=answer_text,
            cited_record_ids=resolved_uuids,
            cited_tokens=resolved_tokens,
        )
