import asyncio
import logging
import random

import httpx

from app.core.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingDimensionError,
    EmbeddingInputError,
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingRateLimitError,
    EmbeddingTimeoutError,
)

logger = logging.getLogger(__name__)


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Google Gemini embedding provider using official batchEmbedContents REST API.

    Strictly fail-closed: permitted only in designated synthetic development/test
    environments. Transmits only passage text payloads without patient/document
    identifiers or metadata.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "models/gemini-embedding-2",
        dimension: int = 768,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        batch_size: int = 50,
    ) -> None:
        if dimension != 768:
            raise ValueError("M4 architecture lock requires dimension == 768")
        self.api_key = api_key
        self.model = model
        self.dimension = dimension
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.batch_size = batch_size
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    async def embed_text(self, text: str) -> list[float]:
        results = await self.embed_batch([text])
        if not results:
            raise EmbeddingProviderError("No embedding returned.")
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        # Validate inputs prior to initiating any HTTP network request
        for text in texts:
            cleaned = text.strip()
            if not cleaned:
                raise EmbeddingInputError("Cannot embed empty or whitespace-only text")

        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            batch_embeddings = await self._embed_batch_slice(batch)
            all_embeddings.extend(batch_embeddings)

        return all_embeddings

    async def _embed_batch_slice(self, batch: list[str]) -> list[list[float]]:
        # Normalize model prefix
        model_name = self.model
        if not model_name.startswith("models/"):
            model_name = f"models/{model_name}"

        url = f"{self.base_url}/{model_name}:batchEmbedContents"
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        requests_payload = [
            {
                "model": model_name,
                "content": {"parts": [{"text": text}]},
                "embedContentConfig": {"outputDimensionality": self.dimension},
            }
            for text in batch
        ]
        payload = {"requests": requests_payload}

        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(url, headers=headers, json=payload)

                    if response.status_code == 429:
                        if attempt < self.max_retries:
                            backoff = min(30.0, (2**attempt) + random.uniform(0.0, 1.0))
                            await asyncio.sleep(backoff)
                            continue
                        raise EmbeddingRateLimitError("Gemini rate limit exceeded.")

                    if response.status_code in (500, 502, 503, 504):
                        if attempt < self.max_retries:
                            backoff = min(30.0, (2**attempt) + random.uniform(0.0, 1.0))
                            await asyncio.sleep(backoff)
                            continue
                        raise EmbeddingProviderError(
                            f"Gemini server error: {response.status_code}"
                        )

                    if response.status_code in (401, 403):
                        raise EmbeddingConfigurationError(
                            f"Gemini authentication failed ({response.status_code}): "
                            "missing or invalid GEMINI_API_KEY."
                        )

                    if response.status_code == 404:
                        raise EmbeddingConfigurationError(
                            f"Gemini model not found (404): '{self.model}'."
                        )

                    if response.status_code == 400:
                        raise EmbeddingProviderError(
                            f"Gemini bad request (400): {response.text}"
                        )

                    response.raise_for_status()
                    data = response.json()

                    embeddings = data.get("embeddings", [])
                    if len(embeddings) != len(batch):
                        raise EmbeddingProviderError(
                            f"Provider returned {len(embeddings)} embeddings "
                            f"for batch of size {len(batch)}."
                        )

                    result: list[list[float]] = []
                    for emb in embeddings:
                        values = emb.get("values", [])
                        if len(values) != self.dimension:
                            raise EmbeddingDimensionError(
                                f"Expected dimension {self.dimension}, "
                                f"got {len(values)}."
                            )
                        result.append(values)

                    return result

            except httpx.TimeoutException as e:
                raise EmbeddingTimeoutError(f"Gemini request timed out: {e}") from e
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (401, 403, 404):
                    raise EmbeddingConfigurationError(
                        f"Gemini configuration error ({e.response.status_code}): "
                        f"{e.response.text}"
                    ) from e
                logger.error(
                    "Gemini HTTP error: %s - %s",
                    e.response.status_code,
                    e.response.text,
                )
                raise EmbeddingProviderError(
                    f"HTTP Error {e.response.status_code}: {e.response.text}"
                ) from e
            except httpx.RequestError as e:
                if attempt < self.max_retries:
                    backoff = min(30.0, (2**attempt) + random.uniform(0.0, 1.0))
                    await asyncio.sleep(backoff)
                    continue
                logger.error("Gemini network error: %s", e)
                raise EmbeddingProviderError(f"Network error: {e}") from e

        raise EmbeddingProviderError("Exhausted retries.")
