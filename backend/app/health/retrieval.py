"""Tenant-Isolated Semantic Retrieval Engine (Phase 2 — Milestone 4 — Slice 4).

Provides deterministic, tenant-scoped vector similarity retrieval over persisted
``DocumentChunk`` embeddings using PostgreSQL + pgvector HNSW cosine index.

Architecture lock references:
  phases/P2-M4-S4-architecture-lock.md
  phases/P2-M4-S4-architecture.md

Core invariants (strictly enforced):
  1. Query embedding happens BEFORE any DB transaction is opened.
  2. Unknown / None domain -> zero embedding calls, zero DB calls.
  3. Safety classification is owned by the orchestrator; NOT duplicated here.
  4. One retrieval SELECT statement per request (plus one SET LOCAL command).
  5. No application-side oversampling; no secondary retrieval queries.
  6. SET LOCAL hnsw.iterative_scan = 'strict_order' (transaction-local).
  7. Stage 1: distance-only ORDER BY -> HNSW index scan, LIMIT K.
  8. Stage 2: deterministic tie-break over <= 5 candidates (outer query sort).
  9. No per-request pgvector version SELECT.
  10. No raw SQLAlchemy / asyncpg errors escape the retrieval boundary.
  11. Strict patient_id isolation at both the SQL predicate and JOIN level.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Optional, Sequence

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.config import settings as app_settings
from app.core.embeddings import (
    EmbeddingError,
    EmbeddingProvider,
    get_embedding_provider,
)
from app.db.models import DocumentChunk, DocumentExtraction, MedicalDocument

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain -> document_type mapping (section 5 of architecture spec)
# ---------------------------------------------------------------------------

#: Maps inquiry target domains to concrete stored ``MedicalDocument.document_type``
#: values.  Every valid ``DocumentType`` literal is covered by exactly one domain.
DOMAIN_TO_DOCUMENT_TYPES: dict[str, tuple[str, ...]] = {
    "labs": ("lab_report",),
    "reports": ("diagnostic_report",),
    "prescriptions": ("prescription",),
    "clinical_documents": ("discharge_summary", "medical_record", "other"),
}


# ---------------------------------------------------------------------------
# Typed exception hierarchy (section 12 of architecture spec)
# ---------------------------------------------------------------------------


class RetrievalError(Exception):
    """Base exception for all retrieval operations."""


class RetrievalConfigurationError(RetrievalError):
    """Raised when environment or pgvector extension version is unsupported."""


class RetrievalInputError(RetrievalError):
    """Raised when query input, target domain, or top_k fails validation."""


class RetrievalProviderError(RetrievalError):
    """Raised when upstream embedding provider fails during query embedding."""


class RetrievalDatabaseError(RetrievalError):
    """Raised when PostgreSQL or pgvector query execution fails."""


# ---------------------------------------------------------------------------
# Public result contracts (section 11 of architecture spec)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetrievedPassage:
    """Immutable value object representing a single retrieved document chunk passage.

    Fields intentionally excluded:
      - ``embedding``: large, exposes model internals, unnecessary downstream.
      - ``storage_key``: internal S3 path; never exposed per M1 security invariant.
    """

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    patient_id: uuid.UUID
    chunk_index: int
    page_number: Optional[int]
    chunk_text: str
    document_display_name: str
    document_type: str
    document_date: Optional[date]
    cosine_distance: float
    similarity: float


@dataclass(frozen=True)
class RetrievalResult:
    """Immutable container for the results of a semantic passage retrieval operation."""

    patient_id: uuid.UUID
    target_domains: tuple[str, ...]
    query_text: str
    top_k: int
    passages: tuple[RetrievedPassage, ...]

    @property
    def is_empty(self) -> bool:
        return len(self.passages) == 0

    @property
    def best_passage(self) -> Optional[RetrievedPassage]:
        return self.passages[0] if self.passages else None


# ---------------------------------------------------------------------------
# pgvector version validation (startup / test-init only, NOT per-request)
# ---------------------------------------------------------------------------


def parse_pgvector_version(version_str: str) -> tuple[int, ...]:
    """Parse a semantic version string into a numeric tuple for safe comparison.

    Uses numeric tuple comparison to avoid lexical ordering bugs such as
    ``"0.10.0" < "0.8.0"`` when compared as strings.

    Args:
        version_str: Raw version string, e.g. ``"0.8.6"``.

    Returns:
        Tuple of integers, e.g. ``(0, 8, 6)``.  Returns ``(0, 0, 0)`` for
        unparseable input rather than raising, to avoid crashing callers.
    """
    matches = re.findall(r"\d+", version_str)
    if not matches:
        return (0, 0, 0)
    return tuple(int(x) for x in matches[:3])


async def verify_pgvector_version(session: AsyncSession) -> None:
    """Verify that the installed pgvector extension meets the minimum required version.

    ENVIRONMENT / STARTUP / TEST-INITIALIZATION CHECK ONLY.
    This verification is executed once during application startup, service
    initialization, or test-suite setup.  It is NOT executed on the per-request
    retrieval path — doing so would violate the one-SELECT per request budget.

    Per-request retrieval budget is strictly:
      - one retrieval SELECT statement
      - one transaction-local SET LOCAL command

    Args:
        session: An async SQLAlchemy session connected to the target database.

    Raises:
        RetrievalConfigurationError: If pgvector is not installed or its version
            is below 0.8.0.
    """
    stmt = text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    result = await session.execute(stmt)
    version_raw = result.scalar()

    if not version_raw:
        raise RetrievalConfigurationError(
            "pgvector extension is not installed in the database.  "
            "Install pgvector >= 0.8.0 before serving retrieval traffic."
        )

    parsed = parse_pgvector_version(str(version_raw))
    if parsed < (0, 8, 0):
        raise RetrievalConfigurationError(
            f"pgvector extension version must be >= 0.8.0 for iterative HNSW "
            f"scanning.  Installed version is '{version_raw}'.  "
            "Upgrade pgvector before serving retrieval traffic."
        )


# ---------------------------------------------------------------------------
# Query text normalization (section 6.2 of architecture spec)
# ---------------------------------------------------------------------------


def format_query_for_embedding(raw_query: str) -> str:
    """Format a user's natural language query for vector embedding.

    Establishes the canonical query-side embedding representation.
    Normalizes excessive whitespace and strips boundary artifacts while
    preserving clinical casing and terminology.

    This function owns query-side text formatting.  The embedding provider
    adapter (``app/core/embedding_adapters/``) remains a pure mathematical
    transport and must not apply retrieval-level formatting.

    Args:
        raw_query: The user's original natural language query string.

    Returns:
        Normalized query string ready for embedding.

    Raises:
        RetrievalInputError: If ``raw_query`` is empty or whitespace-only.
    """
    cleaned = " ".join(raw_query.split()).strip()
    if not cleaned:
        raise RetrievalInputError("Query cannot be empty or whitespace-only.")
    return cleaned


# ---------------------------------------------------------------------------
# Primary retrieval function
# ---------------------------------------------------------------------------


async def retrieve_document_passages(
    db: AsyncSession,
    patient_id: uuid.UUID,
    query_text: str,
    target_domains: Sequence[str],
    *,
    top_k: Optional[int] = None,
    provider: Optional[EmbeddingProvider] = None,
    settings: Optional[Settings] = None,
) -> RetrievalResult:
    """Execute tenant-isolated semantic retrieval over persisted
    ``DocumentChunk`` embeddings.

    Lifecycle (two-phase decoupled):

    Phase 1 -- Query Embedding (zero DB connections held):
      1. Validate and normalize query text via ``format_query_for_embedding``.
      2. Resolve and validate target domains against ``DOMAIN_TO_DOCUMENT_TYPES``.
         Unknown / None domains return immediately with empty passages.
      3. Validate ``top_k`` boundaries (1 <= top_k <= RETRIEVAL_MAX_TOP_K).
      4. Call ``provider.embed_text(normalized_query)`` outside any DB transaction.
      5. Validate returned vector dimension == 768.

    Phase 2 -- Vector Search (fast read-only DB query):
      6. Open transaction block with ``async with db.begin()``.
      7. ``SET LOCAL hnsw.iterative_scan = 'strict_order'`` (transaction-local GUC).
      8. Execute single retrieval SELECT (Stage 1 subquery + Stage 2 sort).
      9. Map rows to immutable ``RetrievedPassage`` objects.
      10. Return ``RetrievalResult``.

    Args:
        db: Async SQLAlchemy session.  Must not be in an open transaction when
            this function is called; a fresh transaction is opened internally.
        patient_id: UUID of the authenticated patient.  Hard tenant boundary.
        query_text: Raw user natural language query (may contain PHI).
        target_domains: Ordered sequence of inquiry domain strings to retrieve
            from.  Unrecognized domains are silently excluded.
        top_k: Number of top passages to retrieve.  Defaults to
            ``Settings.RETRIEVAL_DEFAULT_TOP_K`` (3).  Max is
            ``Settings.RETRIEVAL_MAX_TOP_K`` (5).
        provider: Optional pre-resolved ``EmbeddingProvider``.  If ``None``,
            resolved from ``get_embedding_provider()``.
        settings: Optional ``Settings`` override (for testing).

    Returns:
        ``RetrievalResult`` with immutable ``passages`` tuple.  Never raises for
        empty result sets; returns ``RetrievalResult(passages=())``.

    Raises:
        RetrievalInputError: Empty query, ``top_k`` out of bounds.
        RetrievalProviderError: Embedding provider failure.
        RetrievalDatabaseError: PostgreSQL / pgvector execution failure.
    """
    cfg = settings or app_settings

    # ------------------------------------------------------------------
    # Resolve effective top_k and validate bounds
    # ------------------------------------------------------------------
    effective_top_k: int = top_k if top_k is not None else cfg.RETRIEVAL_DEFAULT_TOP_K

    if effective_top_k < 1 or effective_top_k > cfg.RETRIEVAL_MAX_TOP_K:
        raise RetrievalInputError(
            f"top_k must be between 1 and {cfg.RETRIEVAL_MAX_TOP_K} "
            f"(received {effective_top_k})."
        )

    # ------------------------------------------------------------------
    # Phase 1a -- Query text normalization
    # ------------------------------------------------------------------
    normalized_query = format_query_for_embedding(query_text)

    # ------------------------------------------------------------------
    # Phase 1b -- Domain resolution
    # Unknown / None domains produce an empty result with zero provider / DB calls.
    # ------------------------------------------------------------------
    target_document_types: list[str] = []
    resolved_domains: list[str] = []

    for domain in target_domains:
        if domain is not None and domain in DOMAIN_TO_DOCUMENT_TYPES:
            resolved_domains.append(domain)
            target_document_types.extend(DOMAIN_TO_DOCUMENT_TYPES[domain])

    if not target_document_types:
        return RetrievalResult(
            patient_id=patient_id,
            target_domains=tuple(target_domains),
            query_text=normalized_query,
            top_k=effective_top_k,
            passages=(),
        )

    # ------------------------------------------------------------------
    # Phase 1c -- Query embedding (ZERO DB CONNECTIONS HELD during I/O)
    # ------------------------------------------------------------------
    if provider is None:
        provider = get_embedding_provider(cfg)

    try:
        query_vector = await provider.embed_text(normalized_query)
    except EmbeddingError as exc:
        raise RetrievalProviderError(
            f"Embedding provider failed during query embedding: {exc}"
        ) from exc
    except Exception as exc:
        raise RetrievalProviderError(
            f"Unexpected error from embedding provider: {type(exc).__name__}: {exc}"
        ) from exc

    if len(query_vector) != 768:
        raise RetrievalProviderError(
            f"Embedding provider returned a vector of dimension {len(query_vector)}; "
            "expected 768."
        )

    # ------------------------------------------------------------------
    # Phase 2 -- Vector search (single transaction, one SELECT + SET LOCAL)
    # ------------------------------------------------------------------
    try:
        async with db.begin():
            # Transaction-local GUC: automatically reverts on commit/rollback.
            # Prevents GUC state from leaking across pooled connections.
            await db.execute(text("SET LOCAL hnsw.iterative_scan = 'strict_order'"))

            # ----------------------------------------------------------------
            # Stage 1 subquery: distance-only ORDER BY so PostgreSQL uses the
            # HNSW index scan (ix_document_chunks_embedding_hnsw).
            # Compound ORDER BY in a single query forces a Seq Scan + Sort.
            # All eligibility filters are enforced inside PostgreSQL (section 8.1).
            # ----------------------------------------------------------------
            subquery = (
                select(
                    DocumentChunk.id.label("chunk_id"),
                    DocumentChunk.document_id.label("document_id"),
                    DocumentChunk.patient_id.label("patient_id"),
                    DocumentChunk.chunk_index.label("chunk_index"),
                    DocumentChunk.page_number.label("page_number"),
                    DocumentChunk.chunk_text.label("chunk_text"),
                    MedicalDocument.display_name.label("document_display_name"),
                    MedicalDocument.document_type.label("document_type"),
                    MedicalDocument.document_date.label("document_date"),
                    DocumentChunk.embedding.cosine_distance(query_vector).label(
                        "cosine_distance"
                    ),
                )
                .join(
                    MedicalDocument,
                    (DocumentChunk.document_id == MedicalDocument.id)
                    & (DocumentChunk.patient_id == MedicalDocument.patient_id),
                )
                .join(
                    DocumentExtraction,
                    (MedicalDocument.id == DocumentExtraction.document_id)
                    & (MedicalDocument.patient_id == DocumentExtraction.patient_id),
                )
                .where(
                    # Hard tenant boundary enforced at both predicate AND join.
                    DocumentChunk.patient_id == patient_id,
                    MedicalDocument.patient_id == patient_id,
                    # Domain constraint.
                    MedicalDocument.document_type.in_(target_document_types),
                    # Extraction eligibility.
                    DocumentExtraction.extraction_status == "COMPLETED",
                    DocumentExtraction.extracted_text.is_not(None),
                    func.length(func.trim(DocumentExtraction.extracted_text)) > 0,
                    # Embedding and passage integrity.
                    DocumentChunk.embedding.is_not(None),
                    func.length(func.trim(DocumentChunk.chunk_text)) > 0,
                )
                # Stage 1: distance-only -> HNSW index scan is used.
                .order_by(DocumentChunk.embedding.cosine_distance(query_vector).asc())
                .limit(effective_top_k)
            ).subquery("candidate_chunks")

            # ----------------------------------------------------------------
            # Stage 2: outer query applies deterministic tie-breaking over the
            # <= K candidates already selected by Stage 1.
            # Only one composite SELECT is sent to the DB.
            # ----------------------------------------------------------------
            final_stmt = select(subquery).order_by(
                subquery.c.cosine_distance.asc(),
                subquery.c.document_id.asc(),
                subquery.c.chunk_index.asc(),
            )

            result = await db.execute(final_stmt)
            rows = result.all()

    except RetrievalError:
        # Already a typed retrieval error; re-raise as-is.
        raise
    except SQLAlchemyError as exc:
        logger.error(
            "Retrieval DB error for patient=%s domains=%s: %s",
            patient_id,
            resolved_domains,
            type(exc).__name__,
            # Deliberately NOT logging exc details to prevent PHI leakage.
        )
        raise RetrievalDatabaseError(
            f"Database error during retrieval: {type(exc).__name__}"
        ) from exc
    except Exception as exc:
        # Catch anything else so raw asyncpg / pgvector internals never escape
        # the retrieval boundary.
        logger.error(
            "Unexpected retrieval error for patient=%s: %s",
            patient_id,
            type(exc).__name__,
        )
        raise RetrievalDatabaseError(
            f"Unexpected database error during retrieval: {type(exc).__name__}"
        ) from exc

    # ------------------------------------------------------------------
    # Map rows to immutable public contracts
    # ------------------------------------------------------------------
    passages: list[RetrievedPassage] = []
    for row in rows:
        cosine_dist = float(row.cosine_distance)
        passages.append(
            RetrievedPassage(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                patient_id=row.patient_id,
                chunk_index=row.chunk_index,
                page_number=row.page_number,
                chunk_text=row.chunk_text,
                document_display_name=row.document_display_name,
                document_type=row.document_type,
                document_date=row.document_date,
                cosine_distance=cosine_dist,
                # similarity = 1.0 - cosine_distance for unit-normalized vectors.
                similarity=max(0.0, 1.0 - cosine_dist),
            )
        )

    return RetrievalResult(
        patient_id=patient_id,
        target_domains=tuple(resolved_domains),
        query_text=normalized_query,
        top_k=effective_top_k,
        passages=tuple(passages),
    )


# ---------------------------------------------------------------------------
# HybridRetrievalEngine class wrapper (used by orchestrator)
# ---------------------------------------------------------------------------


class HybridRetrievalEngine:
    """Thin stateless wrapper providing a class-based interface to retrieval.

    Delegates all logic to ``retrieve_document_passages``.  The engine is
    stateless; there is no session caching or connection pooling here.

    Args:
        provider: Optional pre-configured ``EmbeddingProvider``.
        settings: Optional ``Settings`` override (for testing).
    """

    def __init__(
        self,
        provider: Optional[EmbeddingProvider] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self._provider = provider
        self._settings = settings

    async def retrieve(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
        query_text: str,
        target_domains: Sequence[str],
        *,
        top_k: Optional[int] = None,
    ) -> RetrievalResult:
        """Retrieve top-K relevant document passages for patient_id.

        Thin delegation to :func:`retrieve_document_passages`.  All invariants
        from that function apply here without exception.
        """
        return await retrieve_document_passages(
            db=db,
            patient_id=patient_id,
            query_text=query_text,
            target_domains=target_domains,
            top_k=top_k,
            provider=self._provider,
            settings=self._settings,
        )
