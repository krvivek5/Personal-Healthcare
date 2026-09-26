"""Tenant-Isolated Semantic Retrieval Engine (Phase 2 — Milestone 6 — Slice 2).

Provides deterministic, tenant-scoped vector similarity retrieval and recency-ranked
longitudinal candidate recall over persisted ``DocumentChunk`` embeddings using
PostgreSQL + pgvector HNSW cosine index and structure-aware lexical candidate matching.

Architecture lock references:
  phases/P2-M4-S4-architecture-lock.md
  phases/P2-M6-architecture-lock.md (Sections 5.1, 5.2, Slice 2)

Core invariants (strictly enforced):
  1. Query embedding happens BEFORE any DB transaction is opened.
  2. Unknown / None domain -> zero embedding calls, zero DB calls.
  3. Safety classification is owned by the orchestrator; NOT duplicated here.
  4. One retrieval SELECT statement per request (plus one SET LOCAL command) for
     ordinary vector retrieval; superlative retrieval paths execute structured
     pre-resolution or dual-path candidate queries as required by M6 architecture.
  5. No application-side oversampling; no secondary retrieval queries on ordinary path.
  6. SET LOCAL hnsw.iterative_scan = 'strict_order' (transaction-local).
  7. Stage 1: distance-only ORDER BY -> HNSW index scan, LIMIT K.
  8. Stage 2: deterministic tie-break over candidates (outer query sort).
  9. No per-request pgvector version SELECT.
  10. No raw SQLAlchemy / asyncpg errors escape the retrieval boundary.
  11. Strict patient_id isolation at both the SQL predicate and JOIN level.
  12. Superlative paths require document_date IS NOT NULL (no undated candidates).
  13. Hybrid candidate union (K_dense=10, K_lexical=10) bounded at <= 20 candidates.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional, Sequence

from sqlalchemy import func, or_, select, text
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
from app.schemas.inquiry import SuperlativeType

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
# Milestone 6 Constants & Maps (Sections 5.1, 5.2 of P2-M6 Architecture Lock)
# ---------------------------------------------------------------------------

#: Internal superlative candidate recall limits (bypass caller top_k guard).
K_DENSE: int = 10
K_LEXICAL: int = 10

#: Curated narrow lexical variant map for entity-anchored superlative retrieval.
LEXICAL_VARIANT_MAP: dict[str, list[str]] = {
    "cholesterol": ["cholesterol", "total cholesterol", "chol"],
    "blood pressure": ["blood pressure", "bp"],
}

#: Documented sentinel value for lexical-only candidates where vector cosine distance
#: is not computed. Float 0.0 satisfies RetrievedPassage.cosine_distance type contract.
LEXICAL_SENTINEL_COSINE_DISTANCE: float = 0.0


# ---------------------------------------------------------------------------
# Milestone 6 Lexical Escaping & Pattern Helpers
# ---------------------------------------------------------------------------


def escape_regex_literal(token: str) -> str:
    """Escape all PostgreSQL ARE (Advanced Regular Expression) metacharacters.

    Escapes characters that have special meaning in POSIX / PostgreSQL ARE:
    ``\\``, ``^``, ``$``, ``.``, ``[``, ``]``, ``(``, ``)``, ``|``, ``*``,
    ``+``, ``?``, ``{``, ``}``.
    Backslash is escaped first to avoid double-escaping.

    Args:
        token: Single-token literal string to escape.

    Returns:
        Escaped literal string safe for inclusion in a PostgreSQL ARE pattern.
    """
    return re.sub(r"([\\^$.[\]()|*+?{}])", r"\\\1", token)


def build_token_boundary_regex(token: str) -> str:
    """Build a PostgreSQL ARE whole-token boundary pattern: ``\\m<escaped_literal>\\M``.

    Uses PostgreSQL word boundaries:
      - ``\\m``: matches at the beginning of a word
      - ``\\M``: matches at the end of a word
    Does NOT use Python/PCRE ``\\b``.

    Args:
        token: Raw single-token variant string.

    Returns:
        PostgreSQL ARE boundary pattern string.
    """
    escaped = escape_regex_literal(token)
    return rf"\m{escaped}\M"


def escape_ilike_literal(text: str, escape_char: str = "!") -> str:
    """Escape PostgreSQL ILIKE wildcard metacharacters for literal matching.

    Escapes the escape character itself, '%', and '_'.

    Args:
        text: Phrase text to escape.
        escape_char: Escape delimiter character (default '!').

    Returns:
        Safely escaped string for use in parameterized ILIKE ... ESCAPE '!'.
    """
    return (
        text.replace(escape_char, escape_char + escape_char)
        .replace("%", escape_char + "%")
        .replace("_", escape_char + "_")
    )


def resolve_lexical_variants(target_entity: str) -> list[str]:
    """Resolve curated variants or fallback single/multi-word variant for target_entity.

    If absent from LEXICAL_VARIANT_MAP:
      variants = [target_entity.strip()]
    """
    cleaned = target_entity.strip()
    if not cleaned:
        return []
    lower = cleaned.lower()
    if lower in LEXICAL_VARIANT_MAP:
        return list(LEXICAL_VARIANT_MAP[lower])
    return [cleaned]


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
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    top_k: Optional[int] = None,
    superlative: Optional[SuperlativeType] = None,
    target_entity: Optional[str] = None,
    provider: Optional[EmbeddingProvider] = None,
    settings: Optional[Settings] = None,
) -> RetrievalResult:
    """Execute tenant-isolated semantic retrieval over persisted
    ``DocumentChunk`` embeddings, with recency-ranked candidate recall for
    superlative inquiries.

    Lifecycle (two-phase decoupled):

    Phase 1 -- Query Embedding (zero DB connections held):
      1. Validate caller-facing ``top_k`` boundaries
         (1 <= top_k <= RETRIEVAL_MAX_TOP_K).
      2. Validate and normalize query text via ``format_query_for_embedding``.
      3. Resolve and validate target domains against ``DOMAIN_TO_DOCUMENT_TYPES``.
         Unknown / None domains return immediately with empty passages.
      4. Call ``provider.embed_text(normalized_query)`` outside any DB transaction.
      5. Validate returned vector dimension == 768.

    Phase 2 -- DB Retrieval:
      6. Open transaction block with ``async with db.begin()``.
      7. Route to appropriate retrieval strategy:
         a. Ordinary (superlative is None):
            - Single composite SELECT (HNSW strict_order index scan + tie-break).
         b. Domain-Level Superlative (superlative is not None, target_entity is None):
            - Pre-retrieval SQL resolving MAX/MIN(document_date).
            - Scoped dense vector search on target_date (or empty if no dated record).
         c. Entity-Anchored Superlative (superlative is not None,
            target_entity is not None):
            - Dense semantic candidates (K_dense=10, document_date IS NOT NULL).
            - Lexical/entity candidates (K_lexical=10, structure-aware predicates).
            - Deterministic candidate union U = C_dense ∪ C_lexical (|U| <= 20).
            - Deduplication by canonical chunk_id.
            - Strict chronological candidate ranking (LATEST -> DESC, FIRST -> ASC).
      8. Map rows to immutable ``RetrievedPassage`` objects.
      9. Return ``RetrievalResult``.

    Args:
        db: Async SQLAlchemy session. Must not be in an open transaction when
            this function is called; a fresh transaction is opened internally.
        patient_id: UUID of the authenticated patient. Hard tenant boundary.
        query_text: Raw user natural language query (may contain PHI).
        target_domains: Ordered sequence of inquiry domain strings to retrieve
            from. Unrecognized domains are silently excluded.
        start_date: Optional lower bound date filter (inclusive).
        end_date: Optional upper bound date filter (inclusive).
        top_k: Number of top passages to retrieve. Defaults to
            ``Settings.RETRIEVAL_DEFAULT_TOP_K`` (3). Max is
            ``Settings.RETRIEVAL_MAX_TOP_K`` (5).
        superlative: Optional superlative extremity requested (LATEST or FIRST).
        target_entity: Optional clinical target entity anchoring the query.
        provider: Optional pre-resolved ``EmbeddingProvider``. If ``None``,
            resolved from ``get_embedding_provider()``.
        settings: Optional ``Settings`` override (for testing).

    Returns:
        ``RetrievalResult`` with immutable ``passages`` tuple. Never raises for
        empty result sets; returns ``RetrievalResult(passages=())``.

    Raises:
        RetrievalInputError: Empty query, ``top_k`` out of bounds.
        RetrievalProviderError: Embedding provider failure.
        RetrievalDatabaseError: PostgreSQL / pgvector execution failure.
    """
    cfg = settings or app_settings

    # ------------------------------------------------------------------
    # Resolve effective top_k and validate caller-facing bounds
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
    # Phase 2 -- Database Retrieval
    # ------------------------------------------------------------------
    try:
        async with db.begin():
            # --------------------------------------------------------------
            # Branch 1: Ordinary Non-Superlative Retrieval (Preserved verbatim)
            # --------------------------------------------------------------
            if superlative is None:
                await db.execute(text("SET LOCAL hnsw.iterative_scan = 'strict_order'"))

                where_clauses = [
                    DocumentChunk.patient_id == patient_id,
                    MedicalDocument.patient_id == patient_id,
                    MedicalDocument.document_type.in_(target_document_types),
                    DocumentExtraction.extraction_status == "COMPLETED",
                    DocumentExtraction.extracted_text.is_not(None),
                    func.length(func.trim(DocumentExtraction.extracted_text)) > 0,
                    DocumentChunk.embedding.is_not(None),
                    func.length(func.trim(DocumentChunk.chunk_text)) > 0,
                ]

                if start_date is not None and end_date is not None:
                    where_clauses.append(MedicalDocument.document_date.is_not(None))
                    where_clauses.append(
                        MedicalDocument.document_date.between(start_date, end_date)
                    )

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
                    .where(*where_clauses)
                    .order_by(DocumentChunk.embedding.cosine_distance(query_vector).asc())
                    .limit(effective_top_k)
                ).subquery("candidate_chunks")

                final_stmt = select(subquery).order_by(
                    subquery.c.cosine_distance.asc(),
                    subquery.c.document_id.asc(),
                    subquery.c.chunk_index.asc(),
                )

                result = await db.execute(final_stmt)
                rows = result.all()

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

            # --------------------------------------------------------------
            # Branch 2: Domain-Level Superlative (target_entity is None)
            # --------------------------------------------------------------
            if target_entity is None:
                date_agg = (
                    func.max(MedicalDocument.document_date)
                    if superlative == SuperlativeType.LATEST
                    else func.min(MedicalDocument.document_date)
                )

                date_where = [
                    MedicalDocument.patient_id == patient_id,
                    MedicalDocument.document_type.in_(target_document_types),
                    MedicalDocument.document_date.is_not(None),
                ]
                if start_date is not None:
                    date_where.append(MedicalDocument.document_date >= start_date)
                if end_date is not None:
                    date_where.append(MedicalDocument.document_date <= end_date)

                date_stmt = select(date_agg).where(*date_where)
                date_result = await db.execute(date_stmt)
                target_date: Optional[date] = date_result.scalar_one_or_none()

                # If no dated document exists, return empty result without vector search
                if target_date is None:
                    return RetrievalResult(
                        patient_id=patient_id,
                        target_domains=tuple(resolved_domains),
                        query_text=normalized_query,
                        top_k=effective_top_k,
                        passages=(),
                    )

                # Target date exists -> scope vector retrieval to target_date
                await db.execute(text("SET LOCAL hnsw.iterative_scan = 'strict_order'"))

                where_clauses = [
                    DocumentChunk.patient_id == patient_id,
                    MedicalDocument.patient_id == patient_id,
                    MedicalDocument.document_type.in_(target_document_types),
                    DocumentExtraction.extraction_status == "COMPLETED",
                    DocumentExtraction.extracted_text.is_not(None),
                    func.length(func.trim(DocumentExtraction.extracted_text)) > 0,
                    DocumentChunk.embedding.is_not(None),
                    func.length(func.trim(DocumentChunk.chunk_text)) > 0,
                    MedicalDocument.document_date.is_not(None),
                    MedicalDocument.document_date == target_date,
                ]

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
                    .where(*where_clauses)
                    .order_by(DocumentChunk.embedding.cosine_distance(query_vector).asc())
                    .limit(effective_top_k)
                ).subquery("candidate_chunks")

                final_stmt = select(subquery).order_by(
                    subquery.c.cosine_distance.asc(),
                    subquery.c.document_id.asc(),
                    subquery.c.chunk_index.asc(),
                )

                result = await db.execute(final_stmt)
                rows = result.all()

                passages = []
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

            # --------------------------------------------------------------
            # Branch 3: Entity-Anchored Superlative (target_entity is not None)
            # Hybrid Recall Union: C_dense (K=10) ∪ C_lexical (K=10)
            # --------------------------------------------------------------
            await db.execute(text("SET LOCAL hnsw.iterative_scan = 'strict_order'"))

            # Path A: Dense Semantic Candidates (K_DENSE=10, document_date IS NOT NULL)
            dense_where = [
                DocumentChunk.patient_id == patient_id,
                MedicalDocument.patient_id == patient_id,
                MedicalDocument.document_type.in_(target_document_types),
                DocumentExtraction.extraction_status == "COMPLETED",
                DocumentExtraction.extracted_text.is_not(None),
                func.length(func.trim(DocumentExtraction.extracted_text)) > 0,
                DocumentChunk.embedding.is_not(None),
                func.length(func.trim(DocumentChunk.chunk_text)) > 0,
                MedicalDocument.document_date.is_not(None),
            ]
            if start_date is not None:
                dense_where.append(MedicalDocument.document_date >= start_date)
            if end_date is not None:
                dense_where.append(MedicalDocument.document_date <= end_date)

            dense_subquery = (
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
                .where(*dense_where)
                .order_by(DocumentChunk.embedding.cosine_distance(query_vector).asc())
                .limit(K_DENSE)
            ).subquery("dense_candidate_chunks")

            dense_final = select(dense_subquery).order_by(
                dense_subquery.c.cosine_distance.asc(),
                dense_subquery.c.document_id.asc(),
                dense_subquery.c.chunk_index.asc(),
            )
            dense_rows = (await db.execute(dense_final)).all()

            # Path B: Deterministic Lexical / Entity Candidates (K_LEXICAL = 10)
            variants = resolve_lexical_variants(target_entity)
            variant_predicates = []
            for var in variants:
                tokens = var.split()
                if len(tokens) == 1:
                    pat = build_token_boundary_regex(var)
                    variant_predicates.append(DocumentChunk.chunk_text.op("~*")(pat))
                elif len(tokens) > 1:
                    escaped_ph = escape_ilike_literal(var, escape_char="!")
                    variant_predicates.append(
                        DocumentChunk.chunk_text.ilike(f"%{escaped_ph}%", escape="!")
                    )

            if variant_predicates:
                lexical_where = [
                    DocumentChunk.patient_id == patient_id,
                    MedicalDocument.patient_id == patient_id,
                    MedicalDocument.document_type.in_(target_document_types),
                    MedicalDocument.document_date.is_not(None),
                    or_(*variant_predicates),
                ]
                if start_date is not None:
                    lexical_where.append(MedicalDocument.document_date >= start_date)
                if end_date is not None:
                    lexical_where.append(MedicalDocument.document_date <= end_date)

                if superlative == SuperlativeType.LATEST:
                    lexical_order = [
                        MedicalDocument.document_date.desc(),
                        MedicalDocument.id.asc(),
                        DocumentChunk.chunk_index.asc(),
                    ]
                else:
                    lexical_order = [
                        MedicalDocument.document_date.asc(),
                        MedicalDocument.id.asc(),
                        DocumentChunk.chunk_index.asc(),
                    ]

                lexical_stmt = (
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
                    )
                    .join(
                        MedicalDocument,
                        (DocumentChunk.document_id == MedicalDocument.id)
                        & (DocumentChunk.patient_id == MedicalDocument.patient_id),
                    )
                    .where(*lexical_where)
                    .order_by(*lexical_order)
                    .limit(K_LEXICAL)
                )
                lexical_rows = (await db.execute(lexical_stmt)).all()
            else:
                lexical_rows = []

    except RetrievalError:
        # Already a typed retrieval error; re-raise as-is.
        raise
    except SQLAlchemyError as exc:
        logger.error(
            "Retrieval DB error for patient=%s domains=%s: %s",
            patient_id,
            resolved_domains,
            type(exc).__name__,
        )
        raise RetrievalDatabaseError(
            f"Database error during retrieval: {type(exc).__name__}"
        ) from exc
    except Exception as exc:
        logger.error(
            "Unexpected retrieval error for patient=%s: %s",
            patient_id,
            type(exc).__name__,
        )
        raise RetrievalDatabaseError(
            f"Unexpected database error during retrieval: {type(exc).__name__}"
        ) from exc

    # Map candidate rows to RetrievedPassage objects
    dense_passages = [
        RetrievedPassage(
            chunk_id=r.chunk_id,
            document_id=r.document_id,
            patient_id=r.patient_id,
            chunk_index=r.chunk_index,
            page_number=r.page_number,
            chunk_text=r.chunk_text,
            document_display_name=r.document_display_name,
            document_type=r.document_type,
            document_date=r.document_date,
            cosine_distance=float(r.cosine_distance),
            similarity=max(0.0, 1.0 - float(r.cosine_distance)),
        )
        for r in dense_rows
    ]

    lexical_passages = [
        RetrievedPassage(
            chunk_id=r.chunk_id,
            document_id=r.document_id,
            patient_id=r.patient_id,
            chunk_index=r.chunk_index,
            page_number=r.page_number,
            chunk_text=r.chunk_text,
            document_display_name=r.document_display_name,
            document_type=r.document_type,
            document_date=r.document_date,
            cosine_distance=LEXICAL_SENTINEL_COSINE_DISTANCE,
            similarity=1.0,
        )
        for r in lexical_rows
    ]

    # Candidate union & deterministic deduplication by canonical chunk_id
    seen_chunk_ids: set[uuid.UUID] = set()
    union_candidates: list[RetrievedPassage] = []

    # Dense candidates preserved first (including real cosine distances)
    for p in dense_passages:
        if p.chunk_id not in seen_chunk_ids:
            seen_chunk_ids.add(p.chunk_id)
            union_candidates.append(p)

    for p in lexical_passages:
        if p.chunk_id not in seen_chunk_ids:
            seen_chunk_ids.add(p.chunk_id)
            union_candidates.append(p)

    # Chronological candidate ordering
    # LATEST -> document_date DESC, document_id ASC, chunk_index ASC
    # FIRST  -> document_date ASC, document_id ASC, chunk_index ASC
    if superlative == SuperlativeType.LATEST:
        union_candidates.sort(
            key=lambda p: (
                -(p.document_date.toordinal() if p.document_date is not None else 0),
                p.document_id,
                p.chunk_index,
            )
        )
    else:
        union_candidates.sort(
            key=lambda p: (
                (p.document_date.toordinal() if p.document_date is not None else 0),
                p.document_id,
                p.chunk_index,
            )
        )

    return RetrievalResult(
        patient_id=patient_id,
        target_domains=tuple(resolved_domains),
        query_text=normalized_query,
        top_k=effective_top_k,
        passages=tuple(union_candidates),
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
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        top_k: Optional[int] = None,
        superlative: Optional[SuperlativeType] = None,
        target_entity: Optional[str] = None,
    ) -> RetrievalResult:
        """Retrieve top-K relevant document passages for patient_id.

        Thin delegation to :func:`retrieve_document_passages`.  All invariants
        from that function apply here without exception.
        """
        kwargs: dict[str, Any] = {}
        if start_date is not None:
            kwargs["start_date"] = start_date
        if end_date is not None:
            kwargs["end_date"] = end_date
        if superlative is not None:
            kwargs["superlative"] = superlative
        if target_entity is not None:
            kwargs["target_entity"] = target_entity
        return await retrieve_document_passages(
            db=db,
            patient_id=patient_id,
            query_text=query_text,
            target_domains=target_domains,
            top_k=top_k,
            provider=self._provider,
            settings=self._settings,
            **kwargs,
        )
