from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.embedding_adapters.gemini import GeminiEmbeddingProvider
from app.core.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingDimensionError,
    EmbeddingInputError,
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingRateLimitError,
    EmbeddingTimeoutError,
)


def test_gemini_provider_protocol_conformance():
    provider = GeminiEmbeddingProvider(api_key="test-key", dimension=768)
    assert isinstance(provider, EmbeddingProvider)


def test_gemini_provider_dimension_validation():
    with pytest.raises(ValueError, match="dimension == 768"):
        GeminiEmbeddingProvider(api_key="test-key", dimension=512)


@pytest.mark.asyncio
async def test_gemini_embed_text_success_payload_contract():
    provider = GeminiEmbeddingProvider(api_key="test-key", dimension=768)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"embeddings": [{"values": [0.1] * 768}]}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        result = await provider.embed_text("test passage text")
        assert len(result) == 768

        mock_post.assert_called_once()
        kwargs = mock_post.call_args.kwargs
        assert kwargs["headers"]["x-goog-api-key"] == "test-key"
        assert kwargs["headers"]["Content-Type"] == "application/json"

        payload = kwargs["json"]
        assert "requests" in payload
        assert len(payload["requests"]) == 1
        req = payload["requests"][0]
        assert req["model"] == "models/gemini-embedding-2"
        assert req["content"] == {"parts": [{"text": "test passage text"}]}
        assert req["embedContentConfig"] == {"outputDimensionality": 768}


@pytest.mark.asyncio
async def test_gemini_payload_strictly_non_phi():
    """Verify request payload contains strictly passage text without DB metadata."""
    provider = GeminiEmbeddingProvider(api_key="test-key", dimension=768)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"embeddings": [{"values": [0.05] * 768}]}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        await provider.embed_text("Clinical note excerpt")

        payload = mock_post.call_args.kwargs["json"]
        req = payload["requests"][0]
        # Only allowed keys in the request item
        assert set(req.keys()) == {"model", "content", "embedContentConfig"}
        assert set(req["content"].keys()) == {"parts"}
        assert req["content"]["parts"] == [{"text": "Clinical note excerpt"}]


@pytest.mark.asyncio
async def test_gemini_input_validation_empty_text():
    provider = GeminiEmbeddingProvider(api_key="test-key", dimension=768)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        with pytest.raises(EmbeddingInputError, match="empty or whitespace-only"):
            await provider.embed_text("   ")

        with pytest.raises(EmbeddingInputError, match="empty or whitespace-only"):
            await provider.embed_batch(["valid", ""])

        # Zero network calls should have been made
        mock_post.assert_not_called()


@pytest.mark.asyncio
async def test_gemini_embed_batch_slicing_and_order():
    provider = GeminiEmbeddingProvider(api_key="test-key", dimension=768, batch_size=2)

    mock_resp1 = MagicMock()
    mock_resp1.status_code = 200
    mock_resp1.json.return_value = {
        "embeddings": [{"values": [0.1] * 768}, {"values": [0.2] * 768}]
    }

    mock_resp2 = MagicMock()
    mock_resp2.status_code = 200
    mock_resp2.json.return_value = {"embeddings": [{"values": [0.3] * 768}]}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [mock_resp1, mock_resp2]

        results = await provider.embed_batch(["t1", "t2", "t3"])
        assert len(results) == 3
        assert results[0][0] == 0.1
        assert results[1][0] == 0.2
        assert results[2][0] == 0.3
        assert mock_post.call_count == 2


@pytest.mark.asyncio
async def test_gemini_rate_limit_retry_and_exhaustion(monkeypatch):
    provider = GeminiEmbeddingProvider(api_key="test-key", dimension=768, max_retries=1)

    async def mock_sleep(seconds):
        pass

    monkeypatch.setattr("asyncio.sleep", mock_sleep)

    mock_resp = MagicMock()
    mock_resp.status_code = 429

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        with pytest.raises(EmbeddingRateLimitError, match="rate limit exceeded"):
            await provider.embed_text("test")

        # Initial attempt + 1 retry = 2 calls
        assert mock_post.call_count == 2


@pytest.mark.asyncio
async def test_gemini_server_error_retry_and_exhaustion(monkeypatch):
    provider = GeminiEmbeddingProvider(api_key="test-key", dimension=768, max_retries=1)

    async def mock_sleep(seconds):
        pass

    monkeypatch.setattr("asyncio.sleep", mock_sleep)

    mock_resp = MagicMock()
    mock_resp.status_code = 503

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        with pytest.raises(EmbeddingProviderError, match="server error: 503"):
            await provider.embed_text("test")

        assert mock_post.call_count == 2


@pytest.mark.asyncio
async def test_gemini_auth_error_non_retryable():
    provider = GeminiEmbeddingProvider(api_key="bad-key", dimension=768, max_retries=2)

    mock_resp = MagicMock()
    mock_resp.status_code = 401

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        with pytest.raises(
            EmbeddingConfigurationError, match="missing or invalid GEMINI_API_KEY"
        ):
            await provider.embed_text("test")

        # Non-retryable: exactly 1 call
        assert mock_post.call_count == 1


@pytest.mark.asyncio
async def test_gemini_timeout_non_retryable():
    provider = GeminiEmbeddingProvider(api_key="test-key", dimension=768, max_retries=2)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.ReadTimeout("Read timed out")

        with pytest.raises(EmbeddingTimeoutError, match="timed out"):
            await provider.embed_text("test")

        assert mock_post.call_count == 1


@pytest.mark.asyncio
async def test_gemini_dimension_mismatch():
    provider = GeminiEmbeddingProvider(api_key="test-key", dimension=768)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"embeddings": [{"values": [0.1] * 512}]}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        with pytest.raises(
            EmbeddingDimensionError, match="Expected dimension 768, got 512"
        ):
            await provider.embed_text("test")
