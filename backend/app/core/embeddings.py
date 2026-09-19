from __future__ import annotations

import hashlib
import math
import random
from typing import Optional, Protocol, runtime_checkable

from app.core.config import Settings
from app.core.config import settings as app_settings


class EmbeddingError(Exception):
    """Base exception for all embedding operations."""


class EmbeddingConfigurationError(EmbeddingError):
    """Raised when provider configuration, environment, or dimension is invalid."""


class EmbeddingInputError(EmbeddingError):
    """Raised when text input fails validation (empty or whitespace-only)."""


class EmbeddingDimensionError(EmbeddingError):
    """Raised when provider returns a vector of unexpected dimension."""


class EmbeddingTimeoutError(EmbeddingError):
    """Raised when an embedding request times out."""


class EmbeddingRateLimitError(EmbeddingError):
    """Raised when upstream provider returns HTTP 429."""


class EmbeddingProviderError(EmbeddingError):
    """Raised on upstream 5xx or unparseable provider response."""


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Abstract protocol for vector embedding generation.

    All implementations must return float vectors strictly conforming
    to the configured dimension (exactly 768 for Milestone 4).
    """

    async def embed_text(self, text: str) -> list[float]:
        """Generate a 768-dimensional vector embedding for a single text passage."""
        ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate 768-dimensional vector embeddings for an ordered list of texts."""
        ...


class MockEmbeddingProvider:
    """Offline mock provider for deterministic unit vectors.

    MUST NOT be used for semantic retrieval quality evaluation.
    """

    def __init__(self, dimension: int = 768) -> None:
        if dimension != 768:
            raise ValueError("M4 architecture lock requires dimension == 768")
        self.dimension = dimension

    def _generate_vector(self, text: str) -> list[float]:
        cleaned = " ".join(text.split()).strip().lower()
        if not cleaned:
            raise EmbeddingInputError("Cannot embed empty or whitespace-only text")

        digest = hashlib.sha256(cleaned.encode("utf-8")).digest()
        seed = int.from_bytes(digest[:8], byteorder="big")
        rng = random.Random(seed)

        raw = [rng.uniform(-1.0, 1.0) for _ in range(self.dimension)]
        norm = math.sqrt(sum(x * x for x in raw))
        if norm == 0.0:
            raw[0] = 1.0
            return raw

        return [round(x / norm, 6) for x in raw]

    async def embed_text(self, text: str) -> list[float]:
        return self._generate_vector(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return [self._generate_vector(t) for t in texts]


def is_synthetic_dev_environment(cfg: Settings) -> bool:
    """Return True only if environment is synthetic/test and explicitly allowed."""
    env = (cfg.ENVIRONMENT or "").strip().lower()
    if env not in ("development", "test"):
        return False
    return bool(getattr(cfg, "ALLOW_DEV_SYNTHETIC_PROVIDERS", False))


def get_embedding_provider(
    settings: Optional[Settings] = None,
) -> EmbeddingProvider:
    """Resolve and instantiate the configured EmbeddingProvider."""
    cfg = settings or app_settings

    if cfg.EMBEDDING_DIMENSION != 768:
        raise EmbeddingConfigurationError(
            f"Milestone 4 strictly locks embedding dimension to 768. "
            f"Configured dimension is {cfg.EMBEDDING_DIMENSION}."
        )

    provider_name = (cfg.EMBEDDING_PROVIDER or "").strip().lower()

    if provider_name == "mock":
        return MockEmbeddingProvider(dimension=768)

    if provider_name == "gemini":
        if not is_synthetic_dev_environment(cfg):
            raise EmbeddingConfigurationError(
                f"Google Gemini free-tier embedding provider is prohibited in "
                f"environment '{cfg.ENVIRONMENT}' with "
                f"ALLOW_DEV_SYNTHETIC_PROVIDERS="
                f"{getattr(cfg, 'ALLOW_DEV_SYNTHETIC_PROVIDERS', False)}. "
                "Gemini free tier is strictly permitted only in explicitly designated "
                "synthetic/de-identified development or test environments with "
                "ALLOW_DEV_SYNTHETIC_PROVIDERS=True. "
                "Staging and production are unconditionally prohibited."
            )
        api_key = (cfg.GEMINI_API_KEY or "").strip()
        if not api_key:
            raise EmbeddingConfigurationError(
                "GEMINI_API_KEY is required when EMBEDDING_PROVIDER is 'gemini'."
            )
        from app.core.embedding_adapters.gemini import GeminiEmbeddingProvider

        return GeminiEmbeddingProvider(
            api_key=api_key,
            model=cfg.EMBEDDING_MODEL,
            dimension=768,
            timeout_seconds=cfg.EMBEDDING_TIMEOUT_SECONDS,
            max_retries=cfg.EMBEDDING_MAX_RETRIES,
            batch_size=cfg.EMBEDDING_BATCH_SIZE,
        )

    raise EmbeddingConfigurationError(
        f"Unsupported EMBEDDING_PROVIDER '{cfg.EMBEDDING_PROVIDER}'. "
        "Supported providers are: 'mock', 'gemini'."
    )
