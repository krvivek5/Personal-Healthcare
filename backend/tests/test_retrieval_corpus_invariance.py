"""Corpus-size invariance and retrieval regression suite.

Authority:
  M5 Retrieval Fix for Corpus-Size Instability.

Tests:
  A. Existing successful retrieval still works.
  B. Corpus-size invariance:
     Progressively add unrelated documents:
     - target only (0 unrelated)
     - target + 1 unrelated
     - target + 5 unrelated
     - target + 10 unrelated
     - target + 20 unrelated
     The target document must remain retrievable and the query must remain SUFFICIENT.
  C. Exact entity retrieval:
     "What is my dosage of Lisinopril?" retrieves the Lisinopril document
     even when many unrelated documents exist.
  D. Unanchored queries:
     target_entity=None retains existing dense-only behavior with LIMIT effective_top_k.
  E. Anti-misattribution:
     Unrelated prescription documents (e.g. Amoxicillin) must not become valid evidence
     for Lisinopril.
  F. Tenant isolation:
     Patient B's Lisinopril documents are never retrievable by Patient A.
  G. Citation provenance:
     Qualified evidence points strictly to the actual Lisinopril source
     document and chunk.
"""

from __future__ import annotations

import math
import pathlib
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
from app.health.evidence_evaluator import evaluate_passage_evidence
from app.health.query_understanding import parse_natural_language_query
from app.health.retrieval import (
    retrieve_document_passages,
)
from app.schemas.inquiry import EvidenceStatus

# ---------------------------------------------------------------------------
# Database connectivity & skipping
# ---------------------------------------------------------------------------


def _pg_url_sync() -> str:
    return settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


def _pg_url_async() -> str:
    return settings.DATABASE_URL


def _check_postgres_accessible() -> bool:
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
    reason="PostgreSQL not accessible; skipping retrieval corpus invariance tests.",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_migrated():
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
    engine = create_async_engine(_pg_url_async(), echo=False, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_session(pg_async_session_factory):
    _created_patient_ids: list[uuid.UUID] = []

    async with pg_async_session_factory() as session:
        session._test_patient_ids = _created_patient_ids  # type: ignore[attr-defined]
        yield session

        if _created_patient_ids:
            try:
                id_list = ", ".join(f"'{p}'" for p in _created_patient_ids)
                await session.execute(
                    text(f"DELETE FROM patients WHERE id IN ({id_list})")
                )
                await session.commit()
            except Exception:
                await session.rollback()


# ---------------------------------------------------------------------------
# Vector and DB helper utilities
# ---------------------------------------------------------------------------


def _unit_vec(dim: int = 768, hot_index: int = 0) -> list[float]:
    vec = [0.0] * dim
    vec[hot_index] = 1.0
    return vec


def _near_vec(
    base_index: int = 0,
    noise_index: int = 1,
    weight: float = 0.1,
) -> list[float]:
    dim = 768
    vec = [0.0] * dim
    vec[base_index] = 1.0
    vec[noise_index] = weight
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec]


async def _create_patient(session: AsyncSession) -> Patient:
    patient = Patient(id=uuid.uuid4(), user_id=uuid.uuid4())
    session.add(patient)
    await session.flush()
    await session.commit()
    tracker = getattr(session, "_test_patient_ids", None)
    if tracker is not None:
        tracker.append(patient.id)
    return patient


async def _create_doc(
    session: AsyncSession,
    patient_id: uuid.UUID,
    display_name: str,
    document_type: str = "prescription",
    extracted_text: Optional[str] = None,
) -> MedicalDocument:
    now = datetime.now(timezone.utc)
    doc = MedicalDocument(
        id=uuid.uuid4(),
        patient_id=patient_id,
        file_name=f"{display_name.lower().replace(' ', '_')}.pdf",
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
        extracted_text=extracted_text or display_name,
        extraction_status="COMPLETED",
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


class DeterministicEmbeddingProvider:
    """Mock provider returning a controllable query vector."""

    def __init__(self, query_vec: list[float]) -> None:
        self._query_vec = query_vec

    async def embed_text(self, text: str) -> list[float]:
        return self._query_vec


LISINOPRIL_CHUNK_TEXT = (
    "PRESCRIPTION\n"
    "Patient: John Doe\n"
    "Rx: Lisinopril. Dosage: 10 mg daily.\n"
    "Dispense: #30 (thirty)\n"
    "Refills: 3\n"
    "Prescribing Physician: Dr. Jordan Casey, MD\n"
    "Clinic: Metro Health Clinic"
)


# ---------------------------------------------------------------------------
# Test Suite
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_existing_successful_retrieval_still_works(pg_session):
    """Test A: Standard entity retrieval succeeds on a single document."""
    patient = await _create_patient(pg_session)
    query_vec = _unit_vec(hot_index=0)
    provider = DeterministicEmbeddingProvider(query_vec)

    doc = await _create_doc(
        pg_session,
        patient.id,
        "06-prescription-partial-old.pdf",
        document_type="prescription",
        extracted_text=LISINOPRIL_CHUNK_TEXT,
    )
    await _create_chunk(
        pg_session,
        doc,
        LISINOPRIL_CHUNK_TEXT,
        0,
        _near_vec(base_index=0, noise_index=1, weight=0.1),
    )

    query_str = "Who prescribed my Lisinopril and at what dose?"
    target = parse_natural_language_query(query_str)

    res = await retrieve_document_passages(
        db=pg_session,
        patient_id=patient.id,
        query_text=query_str,
        target_domains=["prescriptions", "clinical_documents"],
        target_entity=target.target_entity,
        provider=provider,
    )

    assert len(res.passages) >= 1
    assert any("Lisinopril" in p.chunk_text for p in res.passages)

    ev = evaluate_passage_evidence(target, res, patient.id)
    assert ev.status == EvidenceStatus.SUFFICIENT
    assert "dosage" in ev.matched_fields
    assert "physician_name" in ev.matched_fields


@pytest.mark.asyncio
@pytest.mark.parametrize("unrelated_count", [0, 1, 5, 10, 20])
async def test_b_corpus_size_invariance(pg_session, unrelated_count: int):
    """Test B: Target document remains retrievable and SUFFICIENT as unrelated
    documents grow.

    Unrelated documents are given vectors with higher dense similarity than
    the target document (noise_index weight 0.001 vs 0.8), ensuring that pure dense
    retrieval with limit 3 would exclude the target once >= 3 unrelated documents
    exist. Deterministic lexical recall guarantees the target document is never
    displaced.
    """
    patient = await _create_patient(pg_session)
    query_vec = _unit_vec(hot_index=0)
    provider = DeterministicEmbeddingProvider(query_vec)

    # 1. Target Lisinopril document (further in dense distance)
    target_doc = await _create_doc(
        pg_session,
        patient.id,
        "06-prescription-partial-old.pdf",
        document_type="prescription",
        extracted_text=LISINOPRIL_CHUNK_TEXT,
    )
    target_vec = _near_vec(base_index=0, noise_index=1, weight=0.8)
    await _create_chunk(
        pg_session,
        target_doc,
        LISINOPRIL_CHUNK_TEXT,
        0,
        target_vec,
    )

    # 2. Add unrelated documents (closer in dense distance, e.g. weight=0.001)
    for i in range(unrelated_count):
        unrelated_text = (
            f"Routine Health Note #{i + 1}\n"
            f"Vitals: BP 120/80, Pulse 72 bpm.\n"
            f"Discussion of general diet, exercise, and hydration goals."
        )
        u_doc = await _create_doc(
            pg_session,
            patient.id,
            f"Routine Note {i + 1}",
            document_type="other",
            extracted_text=unrelated_text,
        )
        u_vec = _near_vec(base_index=0, noise_index=1, weight=0.01 * (i + 1))
        await _create_chunk(pg_session, u_doc, unrelated_text, 0, u_vec)

    query_str = "Who prescribed my Lisinopril and at what dose?"
    target = parse_natural_language_query(query_str)

    res = await retrieve_document_passages(
        db=pg_session,
        patient_id=patient.id,
        query_text=query_str,
        target_domains=["prescriptions", "clinical_documents"],
        target_entity=target.target_entity,
        provider=provider,
    )

    # Target document must be present regardless of corpus size
    target_passages = [p for p in res.passages if p.document_id == target_doc.id]
    assert len(target_passages) == 1, (
        f"Target document was displaced when corpus had {unrelated_count} "
        "unrelated docs!"
    )

    # Candidate union must remain bounded (|U| <= 20)
    assert len(res.passages) <= 20

    # Evidence qualification must remain SUFFICIENT
    ev = evaluate_passage_evidence(target, res, patient.id)
    assert ev.status == EvidenceStatus.SUFFICIENT
    assert "dosage" in ev.matched_fields
    assert "physician_name" in ev.matched_fields


@pytest.mark.asyncio
async def test_c_exact_entity_retrieval_dosage_query(pg_session):
    """Test C: 'What is my dosage of Lisinopril?' retrieves Lisinopril amidst
    unrelated documents (including unrelated prescriptions).
    """
    patient = await _create_patient(pg_session)
    query_vec = _unit_vec(hot_index=0)
    provider = DeterministicEmbeddingProvider(query_vec)

    # Target Lisinopril document
    target_doc = await _create_doc(
        pg_session,
        patient.id,
        "06-prescription-partial-old.pdf",
        document_type="prescription",
        extracted_text=LISINOPRIL_CHUNK_TEXT,
    )
    await _create_chunk(
        pg_session,
        target_doc,
        LISINOPRIL_CHUNK_TEXT,
        0,
        _near_vec(base_index=0, noise_index=1, weight=0.5),
    )

    # Add 12 unrelated documents, including unrelated prescriptions
    for i in range(12):
        if i % 2 == 0:
            u_text = (
                f"PRESCRIPTION\n"
                f"Patient: John Doe\n"
                f"Rx: Amoxicillin #{i} 500mg capsule orally three times daily.\n"
                f"Prescribed by: Dr. Sarah Jenkins, MD\n"
                f"Clinic: Health Clinic #{i}"
            )
            u_type = "prescription"
            u_name = f"Prescription - Amoxicillin {i}"
        else:
            u_text = f"Lab Panel #{i}: Cholesterol 195, Triglycerides 150."
            u_type = "lab_report"
            u_name = f"Lab {i}"

        u_doc = await _create_doc(
            pg_session,
            patient.id,
            u_name,
            document_type=u_type,
            extracted_text=u_text,
        )
        await _create_chunk(
            pg_session,
            u_doc,
            u_text,
            0,
            _near_vec(base_index=0, noise_index=1, weight=0.05),
        )

    query_str = "What is my dosage of Lisinopril?"
    target = parse_natural_language_query(query_str)

    res = await retrieve_document_passages(
        db=pg_session,
        patient_id=patient.id,
        query_text=query_str,
        target_domains=target.candidate_document_domains,
        target_entity=target.target_entity,
        provider=provider,
    )

    assert any(p.document_id == target_doc.id for p in res.passages)
    ev = evaluate_passage_evidence(target, res, patient.id)
    assert ev.status == EvidenceStatus.SUFFICIENT
    assert "dosage" in ev.matched_fields
    assert all(p.document_id == target_doc.id for p in ev.qualified_passages)


@pytest.mark.asyncio
async def test_d_unanchored_queries_retain_dense_only_behavior(pg_session):
    """Test D: target_entity=None must retain existing dense-only behavior with
    LIMIT effective_top_k.
    """
    patient = await _create_patient(pg_session)
    query_vec = _unit_vec(hot_index=0)
    provider = DeterministicEmbeddingProvider(query_vec)

    # Add 8 documents with varying distances
    for i in range(8):
        text_content = f"Clinical Note #{i}: General progress update."
        doc = await _create_doc(
            pg_session,
            patient.id,
            f"Doc {i}",
            document_type="other",
            extracted_text=text_content,
        )
        await _create_chunk(
            pg_session,
            doc,
            text_content,
            0,
            _near_vec(base_index=0, noise_index=1, weight=0.1 * i),
        )

    # Unanchored query (target_entity=None, top_k=3)
    res = await retrieve_document_passages(
        db=pg_session,
        patient_id=patient.id,
        query_text="general clinical notes",
        target_domains=["clinical_documents"],
        target_entity=None,
        top_k=3,
        provider=provider,
    )

    # Must obey top_k exactly
    assert len(res.passages) == 3
    # Must be sorted strictly by cosine distance ascending
    distances = [p.cosine_distance for p in res.passages]
    assert distances == sorted(distances)


@pytest.mark.asyncio
async def test_e_anti_misattribution_unrelated_prescription_rejected(pg_session):
    """Test E: Amoxicillin prescription must not become valid evidence for
    Lisinopril.
    """
    patient = await _create_patient(pg_session)
    query_vec = _unit_vec(hot_index=0)
    provider = DeterministicEmbeddingProvider(query_vec)

    # Amoxicillin prescription
    amox_text = (
        "PRESCRIPTION\n"
        "Patient: John Doe\n"
        "Rx: Amoxicillin 500mg capsule orally three times daily.\n"
        "Prescribed by: Dr. Emily Brown, MD\n"
        "Clinic: Downtown Urgent Care"
    )
    amox_doc = await _create_doc(
        pg_session,
        patient.id,
        "Prescription - Amoxicillin",
        document_type="prescription",
        extracted_text=amox_text,
    )
    await _create_chunk(
        pg_session,
        amox_doc,
        amox_text,
        0,
        _near_vec(base_index=0, noise_index=1, weight=0.01),
    )

    # Query specifically asks for Lisinopril
    query_str = "Who prescribed my Lisinopril and at what dose?"
    target = parse_natural_language_query(query_str)

    res = await retrieve_document_passages(
        db=pg_session,
        patient_id=patient.id,
        query_text=query_str,
        target_domains=["prescriptions", "clinical_documents"],
        target_entity=target.target_entity,
        provider=provider,
    )

    ev = evaluate_passage_evidence(target, res, patient.id)
    # Must NOT qualify Amoxicillin as Lisinopril evidence
    assert ev.status == EvidenceStatus.INSUFFICIENT
    assert len(ev.qualified_passages) == 0
    assert (
        "do not contain a record of: Lisinopril" in ev.evidence_directive
        or "No records found matching: Lisinopril" in ev.evidence_directive
    )


@pytest.mark.asyncio
async def test_f_tenant_isolation_intact(pg_session):
    """Test F: Patient B's Lisinopril document is never returned for Patient A."""
    patient_a = await _create_patient(pg_session)
    patient_b = await _create_patient(pg_session)

    query_vec = _unit_vec(hot_index=0)
    provider = DeterministicEmbeddingProvider(query_vec)

    # Lisinopril doc owned exclusively by Patient B
    doc_b = await _create_doc(
        pg_session,
        patient_b.id,
        "06-prescription-partial-old.pdf",
        document_type="prescription",
        extracted_text=LISINOPRIL_CHUNK_TEXT,
    )
    await _create_chunk(
        pg_session,
        doc_b,
        LISINOPRIL_CHUNK_TEXT,
        0,
        _near_vec(base_index=0, noise_index=1, weight=0.01),
    )

    # Query executed for Patient A
    query_str = "Who prescribed my Lisinopril and at what dose?"
    target = parse_natural_language_query(query_str)

    res = await retrieve_document_passages(
        db=pg_session,
        patient_id=patient_a.id,
        query_text=query_str,
        target_domains=["prescriptions", "clinical_documents"],
        target_entity=target.target_entity,
        provider=provider,
    )

    assert len(res.passages) == 0
    ev = evaluate_passage_evidence(target, res, patient_a.id)
    assert ev.status == EvidenceStatus.INSUFFICIENT
    assert len(ev.qualified_passages) == 0


@pytest.mark.asyncio
async def test_g_citation_provenance_points_to_lisinopril_source(pg_session):
    """Test G: Citation provenance points directly to the actual Lisinopril
    document and chunk.
    """
    patient = await _create_patient(pg_session)
    query_vec = _unit_vec(hot_index=0)
    provider = DeterministicEmbeddingProvider(query_vec)

    # 1. Target Lisinopril document
    target_doc = await _create_doc(
        pg_session,
        patient.id,
        "06-prescription-partial-old.pdf",
        document_type="prescription",
        extracted_text=LISINOPRIL_CHUNK_TEXT,
    )
    target_chunk = await _create_chunk(
        pg_session,
        target_doc,
        LISINOPRIL_CHUNK_TEXT,
        0,
        _near_vec(base_index=0, noise_index=1, weight=0.5),
    )

    # 2. Add multiple unrelated documents
    for i in range(5):
        u_text = f"Unrelated record #{i} with random clinical notes."
        u_doc = await _create_doc(
            pg_session,
            patient.id,
            f"Note {i}",
            document_type="other",
            extracted_text=u_text,
        )
        await _create_chunk(
            pg_session,
            u_doc,
            u_text,
            0,
            _near_vec(base_index=0, noise_index=1, weight=0.02),
        )

    query_str = "Who prescribed my Lisinopril and at what dose?"
    target = parse_natural_language_query(query_str)

    res = await retrieve_document_passages(
        db=pg_session,
        patient_id=patient.id,
        query_text=query_str,
        target_domains=["prescriptions", "clinical_documents"],
        target_entity=target.target_entity,
        provider=provider,
    )

    ev = evaluate_passage_evidence(target, res, patient.id)
    assert ev.status == EvidenceStatus.SUFFICIENT
    assert len(ev.qualified_passages) == 1

    qualified = ev.qualified_passages[0]
    assert qualified.document_id == target_doc.id
    assert qualified.chunk_id == target_chunk.id
    assert qualified.document_display_name == "06-prescription-partial-old.pdf"
    assert "Dr. Jordan Casey, MD" in qualified.chunk_text
    assert "10 mg" in qualified.chunk_text


@pytest.mark.asyncio
async def test_h_prescription_fixture_metadata_and_dosage_query(pg_session):
    """Test H (Regression): 06-prescription-partial-old.pdf is classified as
    'prescription', retrieved for 'What is my dosage of Lisinopril?' through
    candidate_document_domains ['prescriptions'], and unrelated prescriptions
    remain correctly handled without false attribution.
    """
    patient = await _create_patient(pg_session)
    query_vec = _unit_vec(hot_index=0)
    provider = DeterministicEmbeddingProvider(query_vec)

    # 1. Target Lisinopril prescription fixture
    target_doc = await _create_doc(
        pg_session,
        patient.id,
        "06-prescription-partial-old.pdf",
        document_type="prescription",
        extracted_text=LISINOPRIL_CHUNK_TEXT,
    )
    assert target_doc.document_type == "prescription"

    target_chunk = await _create_chunk(
        pg_session,
        target_doc,
        LISINOPRIL_CHUNK_TEXT,
        0,
        _near_vec(base_index=0, noise_index=1, weight=0.6),
    )

    # 2. Add multiple unrelated prescriptions with closer dense vectors
    unrelated_prescriptions = [
        (
            "Prescription - Metformin",
            "PRESCRIPTION\nRx: Metformin 1000mg orally daily.\n"
            "Prescriber: Dr. Adams, MD",
        ),
        (
            "Prescription - Atorvastatin",
            "PRESCRIPTION\nRx: Atorvastatin 20mg orally daily.\n"
            "Prescriber: Dr. Baker, MD",
        ),
        (
            "Prescription - Amoxicillin",
            "PRESCRIPTION\nRx: Amoxicillin 500mg capsule TID.\n"
            "Prescriber: Dr. Clark, MD",
        ),
    ]
    for idx, (p_name, p_text) in enumerate(unrelated_prescriptions):
        u_doc = await _create_doc(
            pg_session,
            patient.id,
            p_name,
            document_type="prescription",
            extracted_text=p_text,
        )
        await _create_chunk(
            pg_session,
            u_doc,
            p_text,
            0,
            _near_vec(base_index=0, noise_index=1, weight=0.01 * (idx + 1)),
        )

    # 3. Dosage query: candidate_document_domains is strictly ['prescriptions']
    query_str = "What is my dosage of Lisinopril?"
    target = parse_natural_language_query(query_str)
    assert target.candidate_document_domains == ["prescriptions"]
    assert target.target_entity == "Lisinopril"

    res = await retrieve_document_passages(
        db=pg_session,
        patient_id=patient.id,
        query_text=query_str,
        target_domains=target.candidate_document_domains,
        target_entity=target.target_entity,
        provider=provider,
    )

    # Target document must be retrieved despite dense displacement by 3 closer
    # prescriptions
    assert any(p.document_id == target_doc.id for p in res.passages)

    # Evidence qualification evaluates Lisinopril dosage as SUFFICIENT
    ev = evaluate_passage_evidence(target, res, patient.id)
    assert ev.status == EvidenceStatus.SUFFICIENT
    assert "dosage" in ev.matched_fields
    assert len(ev.qualified_passages) == 1
    assert ev.qualified_passages[0].document_id == target_doc.id
    assert ev.qualified_passages[0].chunk_id == target_chunk.id

    # 4. Anti-misattribution: unrelated prescriptions are not falsely qualified
    qualified_doc_ids = {p.document_id for p in ev.qualified_passages}
    assert target_doc.id in qualified_doc_ids
    assert len(qualified_doc_ids) == 1
