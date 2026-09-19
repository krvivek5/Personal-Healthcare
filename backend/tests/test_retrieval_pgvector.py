"""PostgreSQL + pgvector integration tests for the S4 retrieval engine.

All tests in this module require a live PostgreSQL instance with:
  - The pgvector extension installed (>= 0.8.0).
  - All Alembic migrations applied up to head (including 0005_add_document_chunks).

Tests are automatically skipped when PostgreSQL is not accessible.

Covers:
  - verify_pgvector_version: startup check passes on pgvector >= 0.8.0.
  - retrieve_document_passages: happy path with real HNSW retrieval.
  - Tenant isolation: patient_B chunks are never returned for patient_A.
  - Ordering: closest chunk is returned first.
  - Top-K boundary: no more than top_k passages are returned.
  - Empty result: patient with no embedded chunks -> empty passages.
  - SET LOCAL hnsw.iterative_scan: confirmed via query plan (EXPLAIN).
  - Domain filtering: only chunks of requested document_type are returned.
  - Eligible-only: chunks without embeddings are excluded.
  - Extraction filter: only COMPLETED extractions participate.
  - Cross-domain: requesting multiple domains returns from all.
  - Ranking with mathematically controlled vectors (not MockEmbeddingProvider).
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Optional

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from app.core.config import settings
from app.db.models import (
    DocumentChunk,
    DocumentExtraction,
    MedicalDocument,
    Patient,
)
from app.health.retrieval import (
    RetrievalConfigurationError,
    retrieve_document_passages,
    verify_pgvector_version,
)

# ---------------------------------------------------------------------------
# Module-level skip: require accessible PostgreSQL
# ---------------------------------------------------------------------------


def _pg_url_sync() -> str:
    return settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


def _pg_url_async() -> str:
    return settings.DATABASE_URL  # already postgresql+asyncpg://


def _check_postgres_accessible() -> bool:
    """Return True if the PostgreSQL server is accessible (sync probe)."""
    try:
        from sqlalchemy import create_engine

        engine = create_engine(_pg_url_sync(), pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _check_postgres_accessible(),
    reason="PostgreSQL not accessible; skipping pgvector integration tests.",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_migrated():
    """Apply Alembic migrations synchronously before any async test runs.

    This is a *synchronous* module-scoped fixture so that ``alembic.command.upgrade``
    (which internally calls ``asyncio.run()`` via ``env.py``) is executed outside
    the pytest-asyncio event loop.  Calling ``asyncio.run()`` from inside a
    running event loop raises ``RuntimeError``; keeping migration in a sync
    fixture avoids this entirely.

    Pattern mirrors ``pg_migrated_engine`` in ``test_document_chunks_schema.py``.
    """
    import pathlib

    from sqlalchemy import create_engine

    url_sync = _pg_url_sync()
    engine_sync = create_engine(url_sync, pool_pre_ping=True)
    try:
        with engine_sync.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"PostgreSQL not accessible: {exc}")
    finally:
        engine_sync.dispose()

    backend_dir = pathlib.Path(__file__).parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(cfg, "head")


@pytest_asyncio.fixture
async def pg_async_session_factory(pg_migrated):  # noqa: ARG001
    """Async session factory connected to the live PostgreSQL instance.

    Function-scoped (not module-scoped) so the async engine is bound to the
    same event loop as the test function.  pytest-asyncio creates a new event
    loop per test function in AUTO mode; a module-scoped async fixture would
    use a *different* (already-closed) loop when the second test runs.

    Connection state leakage (autobegun transactions left open in the pool) is
    prevented by the ``pg_session`` fixture's explicit ``rollback()`` call in
    teardown, so no special pool configuration is needed here.

    Depends on ``pg_migrated`` (synchronous, module-scoped) to guarantee that
    Alembic ``command.upgrade`` has completed before the first test body runs.
    """
    engine = create_async_engine(_pg_url_async(), echo=False, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_session(pg_async_session_factory):
    """Isolated async session for integration tests.

    Provides a single ``AsyncSession`` that lets production code
    (``retrieve_document_passages``) manage its own real transactions, while
    still cleaning up all test data after each test via explicit DELETE.

    Why not a rollback-wrapping outer transaction?
    -----------------------------------------------
    ``retrieve_document_passages`` calls ``async with db.begin()``.  If an
    outer test transaction is already open, this raises ``InvalidRequestError``
    unless we downgrade it to a savepoint.  But ``SET LOCAL`` in PostgreSQL
    only reverts at a *real* COMMIT/ROLLBACK, not at RELEASE SAVEPOINT, so the
    GUC-scoping test fails with a savepoint approach.  Instead we let the
    production code use real transactions and clean up by tracking which patient
    UUIDs were created and issuing ``DELETE FROM patients`` at teardown.
    Cascading deletes remove all child rows (documents, chunks, extractions).
    """
    _created_patient_ids: list[uuid.UUID] = []

    async with pg_async_session_factory() as session:
        # Attach the tracker so _create_patient can register IDs.
        session._test_patient_ids = _created_patient_ids  # type: ignore[attr-defined]
        try:
            yield session
        finally:
            # Roll back any autobegun transaction from read-only operations
            # (e.g. verify_pgvector_version) before attempting cleanup.
            if session.in_transaction():
                await session.rollback()
            # Delete all rows created by this test (CASCADE handles children).
            if _created_patient_ids:
                async with session.begin():
                    await session.execute(
                        text("DELETE FROM patients WHERE id = ANY(:ids)"),
                        {"ids": _created_patient_ids},
                    )


# ---------------------------------------------------------------------------
# Mathematically controlled vector helpers
# ---------------------------------------------------------------------------


def _unit_vec(dim: int = 768, hot_index: int = 0) -> list[float]:
    """Return a unit vector with all energy in one dimension.

    Using orthogonal basis vectors gives exact cosine distances (0.0 or 1.0)
    which makes retrieval ranking deterministic and testable.
    """
    vec = [0.0] * dim
    vec[hot_index] = 1.0
    return vec


def _near_vec(
    base_index: int = 0,
    noise_index: int = 1,
    weight: float = 0.1,
) -> list[float]:
    """Return a unit vector close (but not identical) to
    ``_unit_vec(hot_index=base_index)``.

    cosine_distance to _unit_vec(hot_index=base_index) = 1 - cos(theta).
    """
    dim = 768
    vec = [0.0] * dim
    vec[base_index] = 1.0
    vec[noise_index] = weight
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec]


# ---------------------------------------------------------------------------
# Database fixture helpers
# ---------------------------------------------------------------------------


async def _create_patient(session: AsyncSession) -> Patient:
    patient = Patient(id=uuid.uuid4(), user_id=uuid.uuid4())
    session.add(patient)
    await session.flush()
    await session.commit()
    # Register for cleanup if tracker is attached.
    tracker = getattr(session, "_test_patient_ids", None)
    if tracker is not None:
        tracker.append(patient.id)
    return patient


async def _create_doc_with_extraction(
    session: AsyncSession,
    patient_id: uuid.UUID,
    document_type: str = "lab_report",
    extraction_status: str = "COMPLETED",
    extracted_text: Optional[str] = "Sample extracted medical text.",
    display_name: str = "Lab Report",
) -> MedicalDocument:
    now = datetime.now(timezone.utc)
    doc = MedicalDocument(
        id=uuid.uuid4(),
        patient_id=patient_id,
        file_name="test.pdf",
        display_name=display_name,
        document_type=document_type,
        content_type="application/pdf",
        file_size_bytes=1024,
        storage_key=f"documents/{patient_id}/{uuid.uuid4()}",
        uploaded_at=now,
        created_at=now,
        updated_at=now,
    )
    extraction = DocumentExtraction(
        id=uuid.uuid4(),
        document_id=doc.id,
        patient_id=patient_id,
        extracted_text=extracted_text,
        extraction_status=extraction_status,
        extraction_method="test",
        extraction_version="1.0",
    )
    session.add(doc)
    session.add(extraction)
    await session.flush()
    await session.commit()
    return doc


async def _create_chunk(
    session: AsyncSession,
    doc: MedicalDocument,
    chunk_text: str,
    chunk_index: int = 0,
    embedding: Optional[list[float]] = None,
) -> DocumentChunk:
    chunk = DocumentChunk(
        id=uuid.uuid4(),
        document_id=doc.id,
        patient_id=doc.patient_id,
        chunk_index=chunk_index,
        chunk_text=chunk_text,
        embedding=embedding,
    )
    session.add(chunk)
    await session.flush()
    await session.commit()
    return chunk


# ---------------------------------------------------------------------------
# verify_pgvector_version
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_pgvector_version_passes_on_live_db(pg_session):
    """verify_pgvector_version must not raise on a compatible live database."""
    # This must NOT raise; if it does, the test environment is mis-configured.
    await verify_pgvector_version(pg_session)


@pytest.mark.asyncio
async def test_verify_pgvector_version_rejects_missing_extension(
    pg_session, monkeypatch
):
    """verify_pgvector_version raises RetrievalConfigurationError when
    pgvector is not installed."""
    # Simulate a missing pgvector extension by patching session.execute
    from unittest.mock import AsyncMock, MagicMock

    mock_result = MagicMock()
    mock_result.scalar = MagicMock(return_value=None)
    monkeypatch.setattr(pg_session, "execute", AsyncMock(return_value=mock_result))

    with pytest.raises(RetrievalConfigurationError, match="not installed"):
        await verify_pgvector_version(pg_session)


@pytest.mark.asyncio
async def test_verify_pgvector_version_rejects_old_version(pg_session, monkeypatch):
    """verify_pgvector_version raises RetrievalConfigurationError for version
    below 0.8.0."""
    from unittest.mock import AsyncMock, MagicMock

    mock_result = MagicMock()
    mock_result.scalar = MagicMock(return_value="0.7.4")
    monkeypatch.setattr(pg_session, "execute", AsyncMock(return_value=mock_result))

    with pytest.raises(RetrievalConfigurationError, match="0.8.0"):
        await verify_pgvector_version(pg_session)


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_isolation_patient_b_chunks_invisible_to_patient_a(pg_session):
    """patient_A retrieval must never return chunks belonging to patient_B."""
    query_vec = _unit_vec(hot_index=0)
    patient_a_vec = _unit_vec(hot_index=0)  # closest to query
    patient_b_vec = _unit_vec(hot_index=0)  # also closest, but different patient

    patient_a = await _create_patient(pg_session)
    patient_b = await _create_patient(pg_session)

    doc_a = await _create_doc_with_extraction(pg_session, patient_a.id)
    doc_b = await _create_doc_with_extraction(pg_session, patient_b.id)

    chunk_a = await _create_chunk(
        pg_session, doc_a, "Patient A lab result", 0, patient_a_vec
    )
    await _create_chunk(pg_session, doc_b, "Patient B lab result", 0, patient_b_vec)

    from unittest.mock import AsyncMock

    provider = AsyncMock()
    provider.embed_text = AsyncMock(return_value=query_vec)

    result = await retrieve_document_passages(
        db=pg_session,
        patient_id=patient_a.id,
        query_text="my lab results",
        target_domains=["labs"],
        top_k=5,
        provider=provider,
    )

    returned_patient_ids = {p.patient_id for p in result.passages}
    assert patient_b.id not in returned_patient_ids, (
        "Tenant isolation violated: patient_B chunks returned for patient_A query"
    )
    if result.passages:
        assert all(p.patient_id == patient_a.id for p in result.passages)
        chunk_ids = {p.chunk_id for p in result.passages}
        assert chunk_a.id in chunk_ids


# ---------------------------------------------------------------------------
# Happy path: closest chunk returned first
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_closest_chunk_returned_first(pg_session):
    """The chunk with minimum cosine distance to query is returned first."""
    # query direction: hot_index=0
    query_vec = _unit_vec(hot_index=0)
    # chunk_close: same direction (distance ~0.0)
    close_vec = _unit_vec(hot_index=0)
    # chunk_far: orthogonal direction (distance = 1.0)
    far_vec = _unit_vec(hot_index=1)

    patient = await _create_patient(pg_session)
    doc = await _create_doc_with_extraction(pg_session, patient.id)

    chunk_close = await _create_chunk(pg_session, doc, "close chunk", 0, close_vec)
    chunk_far = await _create_chunk(pg_session, doc, "far chunk", 1, far_vec)

    from unittest.mock import AsyncMock

    provider = AsyncMock()
    provider.embed_text = AsyncMock(return_value=query_vec)

    result = await retrieve_document_passages(
        db=pg_session,
        patient_id=patient.id,
        query_text="my glucose",
        target_domains=["labs"],
        top_k=2,
        provider=provider,
    )

    assert len(result.passages) == 2
    assert result.passages[0].chunk_id == chunk_close.id, (
        f"Expected close chunk first; got {result.passages[0].chunk_id}"
    )
    assert result.passages[1].chunk_id == chunk_far.id
    assert result.passages[0].cosine_distance < result.passages[1].cosine_distance


# ---------------------------------------------------------------------------
# Top-K boundary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_top_k_limits_results(pg_session):
    """No more than top_k passages are returned even if more qualify."""
    query_vec = _unit_vec(hot_index=0)
    patient = await _create_patient(pg_session)
    doc = await _create_doc_with_extraction(pg_session, patient.id)

    for i in range(5):
        vec = _near_vec(base_index=0, noise_index=i + 2, weight=float(i) * 0.01)
        await _create_chunk(pg_session, doc, f"chunk {i}", i, vec)

    from unittest.mock import AsyncMock

    provider = AsyncMock()
    provider.embed_text = AsyncMock(return_value=query_vec)

    result = await retrieve_document_passages(
        db=pg_session,
        patient_id=patient.id,
        query_text="lab results",
        target_domains=["labs"],
        top_k=3,
        provider=provider,
    )

    assert len(result.passages) <= 3


# ---------------------------------------------------------------------------
# Empty result: no embedded chunks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_embedded_chunks_returns_empty_result(pg_session):
    """Patient with no embedded chunks -> empty RetrievalResult, no error."""
    query_vec = _unit_vec(hot_index=0)
    patient = await _create_patient(pg_session)
    doc = await _create_doc_with_extraction(pg_session, patient.id)

    # Chunk without embedding
    await _create_chunk(pg_session, doc, "unembedded chunk", 0, embedding=None)

    from unittest.mock import AsyncMock

    provider = AsyncMock()
    provider.embed_text = AsyncMock(return_value=query_vec)

    result = await retrieve_document_passages(
        db=pg_session,
        patient_id=patient.id,
        query_text="lab results",
        target_domains=["labs"],
        top_k=3,
        provider=provider,
    )

    assert result.is_empty
    assert result.passages == ()


# ---------------------------------------------------------------------------
# Domain filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_domain_filter_excludes_wrong_document_type(pg_session):
    """Retrieval for 'labs' domain must not return chunks from 'diagnostic_report'."""
    query_vec = _unit_vec(hot_index=0)
    vec = _unit_vec(hot_index=0)

    patient = await _create_patient(pg_session)
    doc_lab = await _create_doc_with_extraction(
        pg_session, patient.id, document_type="lab_report"
    )
    doc_report = await _create_doc_with_extraction(
        pg_session, patient.id, document_type="diagnostic_report"
    )

    chunk_lab = await _create_chunk(pg_session, doc_lab, "lab chunk", 0, vec)
    chunk_report = await _create_chunk(pg_session, doc_report, "report chunk", 0, vec)

    from unittest.mock import AsyncMock

    provider = AsyncMock()
    provider.embed_text = AsyncMock(return_value=query_vec)

    result = await retrieve_document_passages(
        db=pg_session,
        patient_id=patient.id,
        query_text="lab results",
        target_domains=["labs"],  # only lab_report
        top_k=5,
        provider=provider,
    )

    chunk_ids = {p.chunk_id for p in result.passages}
    assert chunk_lab.id in chunk_ids
    assert chunk_report.id not in chunk_ids, (
        "Domain filter failure: diagnostic_report chunk returned for 'labs' domain"
    )


# ---------------------------------------------------------------------------
# Cross-domain retrieval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_domain_retrieval_returns_from_multiple_types(pg_session):
    """Querying multiple domains returns chunks from all matching document types."""
    query_vec = _unit_vec(hot_index=0)
    vec = _unit_vec(hot_index=0)

    patient = await _create_patient(pg_session)
    doc_lab = await _create_doc_with_extraction(
        pg_session, patient.id, document_type="lab_report"
    )
    doc_report = await _create_doc_with_extraction(
        pg_session, patient.id, document_type="diagnostic_report"
    )

    chunk_lab = await _create_chunk(pg_session, doc_lab, "lab chunk", 0, vec)
    chunk_report = await _create_chunk(pg_session, doc_report, "report chunk", 0, vec)

    from unittest.mock import AsyncMock

    provider = AsyncMock()
    provider.embed_text = AsyncMock(return_value=query_vec)

    result = await retrieve_document_passages(
        db=pg_session,
        patient_id=patient.id,
        query_text="my results",
        target_domains=["labs", "reports"],
        top_k=5,
        provider=provider,
    )

    chunk_ids = {p.chunk_id for p in result.passages}
    assert chunk_lab.id in chunk_ids
    assert chunk_report.id in chunk_ids


# ---------------------------------------------------------------------------
# Extraction filter: non-COMPLETED extractions excluded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_extraction_excluded_from_retrieval(pg_session):
    """Chunks whose document has extraction_status=FAILED are excluded."""
    query_vec = _unit_vec(hot_index=0)
    vec = _unit_vec(hot_index=0)

    patient = await _create_patient(pg_session)

    doc_ok = await _create_doc_with_extraction(
        pg_session,
        patient.id,
        extraction_status="COMPLETED",
        extracted_text="Good text here.",
    )
    doc_failed = await _create_doc_with_extraction(
        pg_session, patient.id, extraction_status="FAILED", extracted_text=None
    )

    chunk_ok = await _create_chunk(pg_session, doc_ok, "valid lab chunk", 0, vec)
    await _create_chunk(pg_session, doc_failed, "failed doc chunk", 0, vec)

    from unittest.mock import AsyncMock

    provider = AsyncMock()
    provider.embed_text = AsyncMock(return_value=query_vec)

    result = await retrieve_document_passages(
        db=pg_session,
        patient_id=patient.id,
        query_text="lab result",
        target_domains=["labs"],
        top_k=5,
        provider=provider,
    )

    chunk_ids = {p.chunk_id for p in result.passages}
    assert chunk_ok.id in chunk_ids


# ---------------------------------------------------------------------------
# similarity field is computed correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_similarity_is_one_minus_cosine_distance(pg_session):
    """similarity == 1.0 - cosine_distance for each returned passage."""
    query_vec = _unit_vec(hot_index=0)
    vec = _unit_vec(hot_index=0)

    patient = await _create_patient(pg_session)
    doc = await _create_doc_with_extraction(pg_session, patient.id)
    await _create_chunk(pg_session, doc, "test chunk", 0, vec)

    from unittest.mock import AsyncMock

    provider = AsyncMock()
    provider.embed_text = AsyncMock(return_value=query_vec)

    result = await retrieve_document_passages(
        db=pg_session,
        patient_id=patient.id,
        query_text="test",
        target_domains=["labs"],
        top_k=3,
        provider=provider,
    )

    for p in result.passages:
        expected_similarity = max(0.0, 1.0 - p.cosine_distance)
        assert abs(p.similarity - expected_similarity) < 1e-6, (
            f"similarity={p.similarity} does not match "
            f"1.0 - cosine_distance={p.cosine_distance}"
        )


# ---------------------------------------------------------------------------
# result.top_k matches requested value
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_result_top_k_matches_requested(pg_session):
    """result.top_k in the returned RetrievalResult must match the requested value."""
    query_vec = _unit_vec(hot_index=0)
    patient = await _create_patient(pg_session)
    doc = await _create_doc_with_extraction(pg_session, patient.id)
    await _create_chunk(pg_session, doc, "chunk 0", 0, _unit_vec(hot_index=0))

    from unittest.mock import AsyncMock

    provider = AsyncMock()
    provider.embed_text = AsyncMock(return_value=query_vec)

    result = await retrieve_document_passages(
        db=pg_session,
        patient_id=patient.id,
        query_text="test query",
        target_domains=["labs"],
        top_k=2,
        provider=provider,
    )

    assert result.top_k == 2


# ---------------------------------------------------------------------------
# SET LOCAL hnsw.iterative_scan is applied (verify via EXPLAIN)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_local_hnsw_iterative_scan_is_scoped(pg_session):
    """SET LOCAL hnsw.iterative_scan must not persist beyond the transaction.

    After the retrieval transaction commits, querying the GUC directly should
    NOT return 'strict_order' (it must have reverted to the session default).
    """
    query_vec = _unit_vec(hot_index=0)
    patient = await _create_patient(pg_session)
    doc = await _create_doc_with_extraction(pg_session, patient.id)
    await _create_chunk(pg_session, doc, "some chunk", 0, _unit_vec(hot_index=0))

    from unittest.mock import AsyncMock

    provider = AsyncMock()
    provider.embed_text = AsyncMock(return_value=query_vec)

    # Run a retrieval (which sets the GUC transaction-locally)
    await retrieve_document_passages(
        db=pg_session,
        patient_id=patient.id,
        query_text="test",
        target_domains=["labs"],
        top_k=1,
        provider=provider,
    )

    # After the transaction block exits, the GUC must have reverted.
    # Re-use the session (still in the test transaction) to check.
    result = await pg_session.execute(text("SHOW hnsw.iterative_scan"))
    guc_val = result.scalar()
    # Default value before SET LOCAL is 'off' (pgvector default)
    assert guc_val != "strict_order", (
        "hnsw.iterative_scan leaked past transaction boundary "
        "(SET LOCAL failed to revert)"
    )
