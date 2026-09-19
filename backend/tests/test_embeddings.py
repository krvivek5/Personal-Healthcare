import pytest

from app.core.config import settings
from app.core.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingDimensionError,
    EmbeddingError,
    EmbeddingInputError,
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingRateLimitError,
    EmbeddingTimeoutError,
    MockEmbeddingProvider,
    get_embedding_provider,
)


def test_embedding_exception_hierarchy():
    assert issubclass(EmbeddingConfigurationError, EmbeddingError)
    assert issubclass(EmbeddingInputError, EmbeddingError)
    assert issubclass(EmbeddingDimensionError, EmbeddingError)
    assert issubclass(EmbeddingTimeoutError, EmbeddingError)
    assert issubclass(EmbeddingRateLimitError, EmbeddingError)
    assert issubclass(EmbeddingProviderError, EmbeddingError)


def test_mock_embedding_provider_protocol_conformance():
    provider = MockEmbeddingProvider(dimension=768)
    assert isinstance(provider, EmbeddingProvider)


def test_mock_embedding_provider_deterministic():
    provider = MockEmbeddingProvider(dimension=768)
    emb1 = provider._generate_vector("test passage")
    emb2 = provider._generate_vector("test passage")
    emb3 = provider._generate_vector("different passage")

    assert len(emb1) == 768
    assert emb1 == emb2
    assert emb1 != emb3

    # Check unit norm
    magnitude = sum(x * x for x in emb1) ** 0.5
    assert abs(magnitude - 1.0) < 1e-5


def test_mock_embedding_provider_dimension_rejection():
    with pytest.raises(ValueError, match="dimension == 768"):
        MockEmbeddingProvider(dimension=512)


@pytest.mark.asyncio
async def test_mock_embedding_provider_input_validation():
    provider = MockEmbeddingProvider(dimension=768)
    with pytest.raises(EmbeddingInputError, match="empty or whitespace-only"):
        await provider.embed_text("")

    with pytest.raises(EmbeddingInputError, match="empty or whitespace-only"):
        await provider.embed_text("   \n\t  ")

    with pytest.raises(EmbeddingInputError, match="empty or whitespace-only"):
        await provider.embed_batch(["valid", "   "])


@pytest.mark.asyncio
async def test_mock_embedding_provider_batch():
    provider = MockEmbeddingProvider(dimension=768)
    texts = ["one", "two", "three"]
    embs = await provider.embed_batch(texts)
    assert len(embs) == 3
    assert len(embs[0]) == 768

    empty_embs = await provider.embed_batch([])
    assert empty_embs == []


def test_factory_dimension_check(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_DIMENSION", 512)
    with pytest.raises(
        EmbeddingConfigurationError, match="locks embedding dimension to 768"
    ):
        get_embedding_provider()


def test_factory_mock_provider(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "mock")
    monkeypatch.setattr(settings, "EMBEDDING_DIMENSION", 768)
    provider = get_embedding_provider()
    assert isinstance(provider, EmbeddingProvider)
    assert isinstance(provider, MockEmbeddingProvider)
    assert provider.dimension == 768


def test_factory_gemini_allowed_in_dev_with_flag(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "ALLOW_DEV_SYNTHETIC_PROVIDERS", True)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "EMBEDDING_DIMENSION", 768)

    provider = get_embedding_provider()
    assert isinstance(provider, EmbeddingProvider)
    assert provider.__class__.__name__ == "GeminiEmbeddingProvider"
    assert getattr(provider, "api_key", None) == "test-key"
    assert provider.dimension == 768


def test_factory_gemini_allowed_in_test_with_flag(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "ALLOW_DEV_SYNTHETIC_PROVIDERS", True)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "EMBEDDING_DIMENSION", 768)

    provider = get_embedding_provider()
    assert isinstance(provider, EmbeddingProvider)


def test_factory_gemini_rejected_without_flag(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "ALLOW_DEV_SYNTHETIC_PROVIDERS", False)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "EMBEDDING_DIMENSION", 768)

    with pytest.raises(
        EmbeddingConfigurationError, match="prohibited in environment 'development'"
    ):
        get_embedding_provider()


def test_factory_gemini_rejected_in_test_without_flag(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "ALLOW_DEV_SYNTHETIC_PROVIDERS", False)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "EMBEDDING_DIMENSION", 768)

    with pytest.raises(
        EmbeddingConfigurationError, match="prohibited in environment 'test'"
    ):
        get_embedding_provider()


def test_factory_gemini_rejected_in_staging(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    monkeypatch.setattr(settings, "ALLOW_DEV_SYNTHETIC_PROVIDERS", True)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "EMBEDDING_DIMENSION", 768)

    with pytest.raises(
        EmbeddingConfigurationError, match="prohibited in environment 'staging'"
    ):
        get_embedding_provider()


def test_factory_gemini_rejected_in_production(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "ALLOW_DEV_SYNTHETIC_PROVIDERS", True)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "EMBEDDING_DIMENSION", 768)

    with pytest.raises(
        EmbeddingConfigurationError, match="prohibited in environment 'production'"
    ):
        get_embedding_provider()


def test_factory_gemini_missing_api_key(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "ALLOW_DEV_SYNTHETIC_PROVIDERS", True)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "EMBEDDING_DIMENSION", 768)

    with pytest.raises(EmbeddingConfigurationError, match="GEMINI_API_KEY is required"):
        get_embedding_provider()


def test_factory_unsupported_provider(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "unknown_provider")
    monkeypatch.setattr(settings, "EMBEDDING_DIMENSION", 768)

    with pytest.raises(
        EmbeddingConfigurationError, match="Unsupported EMBEDDING_PROVIDER"
    ):
        get_embedding_provider()
