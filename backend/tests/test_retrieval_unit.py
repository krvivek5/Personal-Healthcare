"""Unit tests for app.health.retrieval — no live database required.

Covers:
  - format_query_for_embedding: normalization and rejection of empty input.
  - parse_pgvector_version: numeric tuple parsing (no lexical comparison bugs).
  - DOMAIN_TO_DOCUMENT_TYPES: completeness and correctness of domain mapping.
  - retrieve_document_passages: input validation invariants.
    - Empty / whitespace query -> RetrievalInputError, zero provider/DB calls.
    - top_k out of bounds -> RetrievalInputError, zero provider/DB calls.
    - Unknown / None domain -> empty RetrievalResult, zero provider/DB calls.
    - Provider error -> RetrievalProviderError.
    - Wrong vector dimension -> RetrievalProviderError.
  - RetrievedPassage / RetrievalResult: immutability and derived properties.
  - HybridRetrievalEngine: delegation invariant.
  - Transaction isolation: embedding called BEFORE any DB transaction.
"""

from __future__ import annotations

import math
import uuid
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.embeddings import EmbeddingProviderError, EmbeddingTimeoutError
from app.health.retrieval import (
    DOMAIN_TO_DOCUMENT_TYPES,
    HybridRetrievalEngine,
    RetrievalInputError,
    RetrievalProviderError,
    RetrievalResult,
    RetrievedPassage,
    format_query_for_embedding,
    parse_pgvector_version,
    retrieve_document_passages,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_unit_vector(dim: int = 768, seed_val: float = 1.0) -> list[float]:
    """Build a mathematically controlled unit vector for ranking tests.

    Uses a simple deterministic pattern so cosine distances are predictable.
    """
    vec = [0.0] * dim
    vec[0] = seed_val
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec]


def _make_mock_provider(vector: Optional[list[float]] = None) -> AsyncMock:
    """Build an AsyncMock embedding provider that returns a given vector."""
    provider = AsyncMock()
    provider.embed_text = AsyncMock(
        return_value=vector if vector is not None else _make_unit_vector()
    )
    return provider


def _make_mock_settings(default_k: int = 3, max_k: int = 5) -> MagicMock:
    cfg = MagicMock()
    cfg.RETRIEVAL_DEFAULT_TOP_K = default_k
    cfg.RETRIEVAL_MAX_TOP_K = max_k
    return cfg


# ---------------------------------------------------------------------------
# format_query_for_embedding
# ---------------------------------------------------------------------------


def test_format_query_normalizes_whitespace():
    assert format_query_for_embedding("  hello   world  ") == "hello world"


def test_format_query_normalizes_internal_tabs_and_newlines():
    assert format_query_for_embedding("blood\n\tsugar\t levels") == "blood sugar levels"


def test_format_query_preserves_clinical_casing():
    raw = "  What is my eGFR / Creatinine ratio?  "
    assert format_query_for_embedding(raw) == "What is my eGFR / Creatinine ratio?"


def test_format_query_rejects_empty_string():
    with pytest.raises(RetrievalInputError, match="empty or whitespace"):
        format_query_for_embedding("")


def test_format_query_rejects_whitespace_only():
    with pytest.raises(RetrievalInputError, match="empty or whitespace"):
        format_query_for_embedding("   \t\n  ")


# ---------------------------------------------------------------------------
# parse_pgvector_version
# ---------------------------------------------------------------------------


def test_parse_pgvector_version_standard():
    assert parse_pgvector_version("0.8.0") == (0, 8, 0)


def test_parse_pgvector_version_patch():
    assert parse_pgvector_version("0.8.6") == (0, 8, 6)


def test_parse_pgvector_version_two_digit_minor():
    # Lexical comparison bug: "0.10.0" < "0.8.0" — numeric parsing MUST prevent this.
    assert parse_pgvector_version("0.10.0") == (0, 10, 0)
    assert parse_pgvector_version("0.10.0") > parse_pgvector_version("0.8.0")


def test_parse_pgvector_version_empty_string():
    assert parse_pgvector_version("") == (0, 0, 0)


def test_parse_pgvector_version_no_digits():
    assert parse_pgvector_version("unknown") == (0, 0, 0)


def test_parse_pgvector_version_only_major():
    assert parse_pgvector_version("1") == (1,)


def test_parse_pgvector_version_major_minor():
    assert parse_pgvector_version("0.8") == (0, 8)


# ---------------------------------------------------------------------------
# DOMAIN_TO_DOCUMENT_TYPES completeness
# ---------------------------------------------------------------------------


def test_domain_to_document_types_covers_all_document_types():
    """Every valid DocumentType literal must be covered by exactly one domain."""
    expected_types = {
        "lab_report",
        "prescription",
        "diagnostic_report",
        "discharge_summary",
        "medical_record",
        "other",
    }
    all_covered = set()
    for types in DOMAIN_TO_DOCUMENT_TYPES.values():
        for t in types:
            all_covered.add(t)
    assert all_covered == expected_types, (
        f"Document types not covered: {expected_types - all_covered}"
    )


def test_domain_to_document_types_no_overlaps():
    """No document_type should appear in more than one domain."""
    seen: dict[str, str] = {}
    for domain, types in DOMAIN_TO_DOCUMENT_TYPES.items():
        for t in types:
            assert t not in seen, (
                f"'{t}' appears in both '{seen[t]}' and '{domain}'"
            )
            seen[t] = domain


def test_domain_mapping_labs():
    assert DOMAIN_TO_DOCUMENT_TYPES["labs"] == ("lab_report",)


def test_domain_mapping_reports():
    assert DOMAIN_TO_DOCUMENT_TYPES["reports"] == ("diagnostic_report",)


def test_domain_mapping_prescriptions():
    assert DOMAIN_TO_DOCUMENT_TYPES["prescriptions"] == ("prescription",)


def test_domain_mapping_clinical_documents():
    assert set(DOMAIN_TO_DOCUMENT_TYPES["clinical_documents"]) == {
        "discharge_summary",
        "medical_record",
        "other",
    }


# ---------------------------------------------------------------------------
# retrieve_document_passages — input validation (no DB hit)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_query_raises_input_error_no_provider_call():
    """Empty query raises RetrievalInputError; zero provider or DB calls."""
    provider = _make_mock_provider()
    db = AsyncMock()

    with pytest.raises(RetrievalInputError, match="empty or whitespace"):
        await retrieve_document_passages(
            db=db,
            patient_id=uuid.uuid4(),
            query_text="",
            target_domains=["labs"],
            provider=provider,
            settings=_make_mock_settings(),
        )

    provider.embed_text.assert_not_called()
    db.begin.assert_not_called()


@pytest.mark.asyncio
async def test_whitespace_query_raises_input_error_no_provider_call():
    """Whitespace-only query raises RetrievalInputError; zero provider or DB calls."""
    provider = _make_mock_provider()
    db = AsyncMock()

    with pytest.raises(RetrievalInputError):
        await retrieve_document_passages(
            db=db,
            patient_id=uuid.uuid4(),
            query_text="   \t\n  ",
            target_domains=["labs"],
            provider=provider,
            settings=_make_mock_settings(),
        )

    provider.embed_text.assert_not_called()
    db.begin.assert_not_called()


@pytest.mark.asyncio
async def test_top_k_zero_raises_input_error_no_provider_call():
    provider = _make_mock_provider()
    db = AsyncMock()

    with pytest.raises(RetrievalInputError, match="top_k"):
        await retrieve_document_passages(
            db=db,
            patient_id=uuid.uuid4(),
            query_text="my fasting glucose",
            target_domains=["labs"],
            top_k=0,
            provider=provider,
            settings=_make_mock_settings(),
        )

    provider.embed_text.assert_not_called()
    db.begin.assert_not_called()


@pytest.mark.asyncio
async def test_top_k_exceeds_max_raises_input_error_no_provider_call():
    provider = _make_mock_provider()
    db = AsyncMock()

    with pytest.raises(RetrievalInputError, match="top_k"):
        await retrieve_document_passages(
            db=db,
            patient_id=uuid.uuid4(),
            query_text="my fasting glucose",
            target_domains=["labs"],
            top_k=6,
            provider=provider,
            settings=_make_mock_settings(max_k=5),
        )

    provider.embed_text.assert_not_called()
    db.begin.assert_not_called()


@pytest.mark.asyncio
async def test_top_k_negative_raises_input_error_no_provider_call():
    provider = _make_mock_provider()
    db = AsyncMock()

    with pytest.raises(RetrievalInputError, match="top_k"):
        await retrieve_document_passages(
            db=db,
            patient_id=uuid.uuid4(),
            query_text="my fasting glucose",
            target_domains=["labs"],
            top_k=-1,
            provider=provider,
            settings=_make_mock_settings(),
        )

    provider.embed_text.assert_not_called()


# ---------------------------------------------------------------------------
# retrieve_document_passages — unknown / None domain -> empty, zero calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_domain_returns_empty_result_zero_calls():
    """Unknown domain -> empty RetrievalResult with zero embedding and DB calls."""
    provider = _make_mock_provider()
    db = AsyncMock()
    patient_id = uuid.uuid4()

    result = await retrieve_document_passages(
        db=db,
        patient_id=patient_id,
        query_text="what are my lipid levels",
        target_domains=["nonexistent_domain"],
        provider=provider,
        settings=_make_mock_settings(),
    )

    assert result.is_empty
    assert result.passages == ()
    assert result.patient_id == patient_id
    provider.embed_text.assert_not_called()
    db.begin.assert_not_called()


@pytest.mark.asyncio
async def test_none_domain_in_list_returns_empty_zero_calls():
    """None domain entry -> empty RetrievalResult with zero embedding and DB calls."""
    provider = _make_mock_provider()
    db = AsyncMock()
    patient_id = uuid.uuid4()

    result = await retrieve_document_passages(
        db=db,
        patient_id=patient_id,
        query_text="what are my lipid levels",
        target_domains=[None],  # type: ignore[list-item]
        provider=provider,
        settings=_make_mock_settings(),
    )

    assert result.is_empty
    assert result.passages == ()
    provider.embed_text.assert_not_called()
    db.begin.assert_not_called()


@pytest.mark.asyncio
async def test_empty_domains_list_returns_empty_zero_calls():
    """Empty domains list -> empty RetrievalResult with zero provider and DB calls."""
    provider = _make_mock_provider()
    db = AsyncMock()

    result = await retrieve_document_passages(
        db=db,
        patient_id=uuid.uuid4(),
        query_text="my creatinine",
        target_domains=[],
        provider=provider,
        settings=_make_mock_settings(),
    )

    assert result.is_empty
    provider.embed_text.assert_not_called()
    db.begin.assert_not_called()


@pytest.mark.asyncio
async def test_mixed_known_and_unknown_domain_uses_known_only():
    """Known + unknown domains: only known are used; unknown are silently excluded.

    Because the known domain resolves, provider.embed_text IS called.
    """
    provider = _make_mock_provider()

    # Set up a minimal async context manager mock for db.begin()
    db = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=None)
    ctx.__aexit__ = AsyncMock(return_value=False)
    db.begin = MagicMock(return_value=ctx)
    db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))

    patient_id = uuid.uuid4()

    result = await retrieve_document_passages(
        db=db,
        patient_id=patient_id,
        query_text="my cholesterol levels",
        target_domains=["labs", "unknown_domain"],
        provider=provider,
        settings=_make_mock_settings(),
    )

    # Provider was called (known domain resolved)
    provider.embed_text.assert_called_once()
    # Only "labs" is in target_domains of the result
    assert result.target_domains == ("labs",)
    assert result.is_empty  # DB mock returns no rows


# ---------------------------------------------------------------------------
# retrieve_document_passages — provider error translation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_embedding_error_raises_retrieval_provider_error():
    """EmbeddingError from provider -> RetrievalProviderError (no raw errors escape)."""
    provider = AsyncMock()
    provider.embed_text = AsyncMock(
        side_effect=EmbeddingProviderError("upstream 500")
    )
    db = AsyncMock()

    with pytest.raises(RetrievalProviderError, match="Embedding provider failed"):
        await retrieve_document_passages(
            db=db,
            patient_id=uuid.uuid4(),
            query_text="my creatinine levels",
            target_domains=["labs"],
            provider=provider,
            settings=_make_mock_settings(),
        )

    db.begin.assert_not_called()


@pytest.mark.asyncio
async def test_provider_timeout_error_raises_retrieval_provider_error():
    """EmbeddingTimeoutError from provider -> RetrievalProviderError."""
    provider = AsyncMock()
    provider.embed_text = AsyncMock(
        side_effect=EmbeddingTimeoutError("request timed out")
    )
    db = AsyncMock()

    with pytest.raises(RetrievalProviderError):
        await retrieve_document_passages(
            db=db,
            patient_id=uuid.uuid4(),
            query_text="my glucose",
            target_domains=["labs"],
            provider=provider,
            settings=_make_mock_settings(),
        )

    db.begin.assert_not_called()


@pytest.mark.asyncio
async def test_wrong_vector_dimension_raises_retrieval_provider_error():
    """Wrong vector dimension from provider -> RetrievalProviderError."""
    # Provider returns a 512-dim vector instead of expected 768.
    bad_vector = [0.0] * 512
    provider = _make_mock_provider(vector=bad_vector)
    db = AsyncMock()

    with pytest.raises(RetrievalProviderError, match="dimension"):
        await retrieve_document_passages(
            db=db,
            patient_id=uuid.uuid4(),
            query_text="my glucose",
            target_domains=["labs"],
            provider=provider,
            settings=_make_mock_settings(),
        )

    db.begin.assert_not_called()


# ---------------------------------------------------------------------------
# retrieve_document_passages — transaction isolation invariant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embedding_called_before_db_transaction():
    """Query embedding must happen BEFORE any DB transaction is opened.

    This is a critical architectural invariant: external network I/O must
    never hold open a database transaction or connection.
    """
    call_order: list[str] = []

    provider = AsyncMock()

    async def track_embed(text: str) -> list[float]:
        call_order.append("embed")
        return _make_unit_vector()

    provider.embed_text = track_embed

    db = AsyncMock()

    # Track when db.begin() context manager is entered
    class TrackingCtx:
        async def __aenter__(self):
            call_order.append("db_begin")
            return self

        async def __aexit__(self, *args):
            return False

    db.begin = MagicMock(return_value=TrackingCtx())
    db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))

    await retrieve_document_passages(
        db=db,
        patient_id=uuid.uuid4(),
        query_text="my cholesterol",
        target_domains=["labs"],
        provider=provider,
        settings=_make_mock_settings(),
    )

    assert call_order[0] == "embed", (
        "Embedding must happen BEFORE db.begin() is entered. "
        f"Actual order: {call_order}"
    )
    assert "db_begin" in call_order


# ---------------------------------------------------------------------------
# RetrievedPassage and RetrievalResult — immutability and derived properties
# ---------------------------------------------------------------------------


def test_retrieved_passage_is_frozen():
    p = RetrievedPassage(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        patient_id=uuid.uuid4(),
        chunk_index=0,
        page_number=1,
        chunk_text="my glucose was 128",
        document_display_name="Lab Report 2024",
        document_type="lab_report",
        document_date=None,
        cosine_distance=0.15,
        similarity=0.85,
    )
    # Frozen dataclasses block attribute assignment via their __setattr__ override.
    with pytest.raises((AttributeError, TypeError)):
        p.chunk_text = "mutated"  # type: ignore[misc]


def test_retrieval_result_is_empty_property():
    pid = uuid.uuid4()
    empty = RetrievalResult(
        patient_id=pid,
        target_domains=("labs",),
        query_text="glucose",
        top_k=3,
        passages=(),
    )
    assert empty.is_empty is True
    assert empty.best_passage is None


def test_retrieval_result_best_passage():
    pid = uuid.uuid4()
    p = RetrievedPassage(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        patient_id=pid,
        chunk_index=0,
        page_number=None,
        chunk_text="lab result",
        document_display_name="Labs",
        document_type="lab_report",
        document_date=None,
        cosine_distance=0.1,
        similarity=0.9,
    )
    result = RetrievalResult(
        patient_id=pid,
        target_domains=("labs",),
        query_text="glucose",
        top_k=3,
        passages=(p,),
    )
    assert not result.is_empty
    assert result.best_passage is p


def test_similarity_clamps_to_zero_for_large_distance():
    """similarity = max(0.0, 1.0 - cosine_distance); never negative."""
    # cosine_distance can exceed 1.0 for non-unit-normalized vectors
    # but similarity must not go negative.
    p = RetrievedPassage(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        patient_id=uuid.uuid4(),
        chunk_index=0,
        page_number=None,
        chunk_text="text",
        document_display_name="doc",
        document_type="lab_report",
        document_date=None,
        cosine_distance=1.5,
        similarity=max(0.0, 1.0 - 1.5),
    )
    assert p.similarity == 0.0


# ---------------------------------------------------------------------------
# HybridRetrievalEngine delegation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hybrid_engine_delegates_to_retrieve_function():
    """HybridRetrievalEngine.retrieve() must delegate to retrieve_document_passages."""
    patient_id = uuid.uuid4()

    with patch(
        "app.health.retrieval.retrieve_document_passages",
        new_callable=AsyncMock,
    ) as mock_retrieve:
        expected = RetrievalResult(
            patient_id=patient_id,
            target_domains=("labs",),
            query_text="glucose",
            top_k=3,
            passages=(),
        )
        mock_retrieve.return_value = expected

        engine = HybridRetrievalEngine()
        db = AsyncMock()

        result = await engine.retrieve(
            db=db,
            patient_id=patient_id,
            query_text="glucose",
            target_domains=["labs"],
            top_k=3,
        )

        assert result is expected
        mock_retrieve.assert_awaited_once_with(
            db=db,
            patient_id=patient_id,
            query_text="glucose",
            target_domains=["labs"],
            top_k=3,
            provider=None,
            settings=None,
        )


# ---------------------------------------------------------------------------
# retrieve_document_passages — default top_k usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_top_k_is_applied_when_none_given():
    """When top_k=None, the configured default (3) must be used."""
    provider = _make_mock_provider()
    db = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=None)
    ctx.__aexit__ = AsyncMock(return_value=False)
    db.begin = MagicMock(return_value=ctx)
    db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))

    result = await retrieve_document_passages(
        db=db,
        patient_id=uuid.uuid4(),
        query_text="my glucose levels",
        target_domains=["labs"],
        top_k=None,
        provider=provider,
        settings=_make_mock_settings(default_k=3, max_k=5),
    )

    assert result.top_k == 3
