"""Unit and integration tests for M6 Slice 2: Recency-Ranked Retrieval Engine.

Authority:
  phases/P2-M6-architecture-lock.md (Sections 5.1, 5.2, Slice 2)

Covers:
  1. Lexical Precision:
     - Curated variant map exact entries.
     - Single-token boundary pattern construction (\\m...\\M, no \\b).
     - Escaped PostgreSQL ARE regex metacharacters.
     - Escaped ILIKE metacharacters (!, %, _).
     - Token boundary precision: bp does not match RBP; chol does not match
       cholecystectomy, cholecystitis, cholelithiasis, cholangitis, cholera.
     - Literal escaping: a.b does not match axb; c+d does not match cccd.
     - Fallback single-token and multi-word entity handling.
  2. Domain-Level Superlative:
     - LATEST -> MAX(document_date).
     - FIRST -> MIN(document_date).
     - Interval-bounded LATEST / FIRST.
     - No dated records -> empty result, vector search bypassed.
     - No dated records in interval -> empty result, vector search bypassed.
  3. Entity-Anchored Superlative:
     - LATEST cholesterol / FIRST cholesterol.
     - LATEST blood pressure (multi-word + single token).
     - Dense-blind latest recovery (lexical recovers newer report missed by dense).
     - Dense-blind first recovery (lexical recovers older baseline missed by dense).
  4. Candidate Mechanics:
     - Dense + lexical overlap deduplication (dense candidate and score preserved).
     - Dense-only candidate preserved.
     - Lexical-only candidate preserved (sentinel cosine_distance=0.0).
     - Union candidate bound <= 20.
     - Deterministic output under candidate-order permutation.
     - K_DENSE = 10, K_LEXICAL = 10 constants.
     - Internal limits bypass caller top_k guard (top_k=10 raises input error).
     - Strict tenant isolation enforced in both paths.
     - Dated candidates only for superlative paths.
     - Ordinary non-superlative retrieval still permits NULL document_date.
  5. HybridRetrievalEngine:
     - Forwards superlative and target_entity parameters.
"""

from __future__ import annotations

import math
import re
import uuid
from collections import namedtuple
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings
from app.health.retrieval import (
    K_DENSE,
    K_LEXICAL,
    LEXICAL_SENTINEL_COSINE_DISTANCE,
    LEXICAL_VARIANT_MAP,
    HybridRetrievalEngine,
    RetrievalInputError,
    RetrievalResult,
    build_token_boundary_regex,
    escape_ilike_literal,
    escape_regex_literal,
    resolve_lexical_variants,
    retrieve_document_passages,
)
from app.schemas.inquiry import SuperlativeType

# ---------------------------------------------------------------------------
# Test Helpers & Fixtures
# ---------------------------------------------------------------------------

MockRow = namedtuple(
    "MockRow",
    [
        "chunk_id",
        "document_id",
        "patient_id",
        "chunk_index",
        "page_number",
        "chunk_text",
        "document_display_name",
        "document_type",
        "document_date",
        "cosine_distance",
    ],
    defaults=[0.0],
)


def _make_unit_vector(dim: int = 768, seed_val: float = 1.0) -> list[float]:
    """Build a deterministic unit vector."""
    vec = [0.0] * dim
    vec[0] = seed_val
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec]


def _make_mock_provider() -> AsyncMock:
    """Build an AsyncMock embedding provider returning a 768-dim unit vector."""
    provider = AsyncMock()
    provider.embed_text = AsyncMock(return_value=_make_unit_vector())
    return provider


def _make_mock_settings(default_k: int = 3, max_k: int = 5) -> MagicMock:
    cfg = MagicMock(spec=Settings)
    cfg.RETRIEVAL_DEFAULT_TOP_K = default_k
    cfg.RETRIEVAL_MAX_TOP_K = max_k
    return cfg


class _TrackingCtx:
    """Async context manager for db.begin()."""

    def __init__(self, callback=None):
        self.callback = callback

    async def __aenter__(self):
        if self.callback:
            self.callback()
        return self

    async def __aexit__(self, *args):
        return False


def _build_mock_db(execute_side_effect) -> AsyncMock:
    """Construct an AsyncMock DB session wired with an async begin() context."""
    db = AsyncMock()
    db.begin = MagicMock(return_value=_TrackingCtx())
    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


# ===========================================================================
# 1. Lexical Precision Tests
# ===========================================================================


class TestLexicalPrecision:
    """Tests covering variant maps, pattern construction, and literal escaping."""

    def test_lexical_variant_map_exact_entries(self):
        """Locked lexical variant map must contain exactly the specified entries."""
        assert LEXICAL_VARIANT_MAP == {
            "cholesterol": ["cholesterol", "total cholesterol", "chol"],
            "blood pressure": ["blood pressure", "bp"],
        }

    def test_resolve_lexical_variants_curated(self):
        """Curated entities resolve to locked variants regardless of case."""
        assert resolve_lexical_variants("cholesterol") == [
            "cholesterol",
            "total cholesterol",
            "chol",
        ]
        assert resolve_lexical_variants("Cholesterol") == [
            "cholesterol",
            "total cholesterol",
            "chol",
        ]
        assert resolve_lexical_variants("CHOLESTEROL") == [
            "cholesterol",
            "total cholesterol",
            "chol",
        ]
        assert resolve_lexical_variants("blood pressure") == ["blood pressure", "bp"]
        assert resolve_lexical_variants("  Blood Pressure  ") == [
            "blood pressure",
            "bp",
        ]

    def test_resolve_lexical_variants_fallback(self):
        """Unmapped entities fallback to [target_entity.strip()]."""
        assert resolve_lexical_variants("ferritin") == ["ferritin"]
        assert resolve_lexical_variants("  fasting glucose  ") == ["fasting glucose"]
        assert resolve_lexical_variants("   ") == []

    def test_escape_regex_literal_all_metacharacters(self):
        """All PostgreSQL ARE metacharacters must be safely escaped."""
        raw = r"a\b^c$d.e[f]g(h)i|j*k+l?m{n}o"
        escaped = escape_regex_literal(raw)
        expected = r"a\\b\^c\$d\.e\[f\]g\(h\)i\|j\*k\+l\?m\{n\}o"
        assert escaped == expected

    def test_escape_regex_literal_specific_clinical_tokens(self):
        assert escape_regex_literal("a.b") == r"a\.b"
        assert escape_regex_literal("c+d") == r"c\+d"
        assert escape_regex_literal("bp") == "bp"
        assert escape_regex_literal("chol") == "chol"

    def test_build_token_boundary_regex_postgre_syntax(self):
        """PostgreSQL ARE whole-token boundaries use \\m and \\M (never \\b)."""
        pattern_bp = build_token_boundary_regex("bp")
        assert pattern_bp == r"\mbp\M"
        assert r"\b" not in pattern_bp

        pattern_chol = build_token_boundary_regex("chol")
        assert pattern_chol == r"\mchol\M"
        assert r"\b" not in pattern_chol

        pattern_ab = build_token_boundary_regex("a.b")
        assert pattern_ab == r"\ma\.b\M"

        pattern_cd = build_token_boundary_regex("c+d")
        assert pattern_cd == r"\mc\+d\M"

    def test_escape_ilike_literal(self):
        """escape_ilike_literal escapes escape_char, %, and _."""
        assert escape_ilike_literal("100% pure") == "100!% pure"
        assert escape_ilike_literal("high_risk") == "high!_risk"
        assert escape_ilike_literal("alert! danger") == "alert!! danger"
        assert escape_ilike_literal("blood pressure") == "blood pressure"
        assert escape_ilike_literal("100%_pure!") == "100!%!_pure!!"

    def test_token_boundary_logic_simulation(self):
        """Simulate PostgreSQL ARE word boundary rules:

        In PostgreSQL ARE, a word character is [A-Za-z0-9_].
        \\m matches at transition from non-word to word (word start).
        \\M matches at transition from word to non-word (word end).
        """

        def pg_are_word_match(token: str, text_to_test: str) -> bool:
            escaped = re.escape(token)
            pattern = rf"(?<!\w){escaped}(?!\w)"
            return bool(re.search(pattern, text_to_test, re.IGNORECASE))

        # bp matches
        assert pg_are_word_match("bp", "BP: 120/80")
        assert pg_are_word_match("bp", "Current BP 130/85")
        assert pg_are_word_match("bp", "(BP)")
        assert pg_are_word_match("bp", "bp")
        # bp non-matches: RBP
        assert not pg_are_word_match("bp", "RBP")
        assert not pg_are_word_match("bp", "Serum RBP level")

        # chol matches
        assert pg_are_word_match("chol", "chol: 180")
        assert pg_are_word_match("chol", "Total Chol 200")
        assert pg_are_word_match("chol", "(chol)")
        # chol non-matches: clinical compounds
        assert not pg_are_word_match("chol", "cholecystectomy")
        assert not pg_are_word_match("chol", "cholecystitis")
        assert not pg_are_word_match("chol", "cholelithiasis")
        assert not pg_are_word_match("chol", "cholangitis")
        assert not pg_are_word_match("chol", "cholera")

        # a.b literal vs axb
        def literal_are_match(raw_token: str, text_to_test: str) -> bool:
            escaped = escape_regex_literal(raw_token)
            pattern = rf"(?<!\w){escaped}(?!\w)"
            return bool(re.search(pattern, text_to_test, re.IGNORECASE))

        assert literal_are_match("a.b", "measured a.b level")
        assert not literal_are_match("a.b", "measured axb level")

        # c+d literal vs cccd
        assert literal_are_match("c+d", "result c+d observed")
        assert not literal_are_match("c+d", "result cccd observed")


# ===========================================================================
# 2. Domain-Level Superlative Tests
# ===========================================================================


class TestDomainLevelSuperlative:
    """Tests covering target_entity is None domain-level superlative pre-resolution."""

    @pytest.mark.asyncio
    async def test_domain_level_latest_resolves_max_date(self):
        """LATEST query without entity resolves MAX(document_date)."""
        pid = uuid.uuid4()
        doc_id = uuid.uuid4()
        chunk_id = uuid.uuid4()
        target_dt = date(2025, 7, 1)

        captured_stmts = []

        async def mock_exec(stmt):
            captured_stmts.append(stmt)
            if len(captured_stmts) == 1:
                res = MagicMock()
                res.scalar_one_or_none.return_value = target_dt
                return res
            elif len(captured_stmts) == 2:
                return MagicMock()
            else:
                row = MockRow(
                    chunk_id=chunk_id,
                    document_id=doc_id,
                    patient_id=pid,
                    chunk_index=0,
                    page_number=1,
                    chunk_text="Latest lab summary",
                    document_display_name="Lab Report 2025",
                    document_type="lab_report",
                    document_date=target_dt,
                    cosine_distance=0.12,
                )
                res = MagicMock()
                res.all.return_value = [row]
                return res

        db = _build_mock_db(mock_exec)

        result = await retrieve_document_passages(
            db=db,
            patient_id=pid,
            query_text="What is my latest lab report?",
            target_domains=["labs"],
            superlative=SuperlativeType.LATEST,
            target_entity=None,
            provider=_make_mock_provider(),
            settings=_make_mock_settings(),
        )

        assert not result.is_empty
        assert len(result.passages) == 1
        passage = result.passages[0]
        assert passage.document_date == target_dt
        assert passage.chunk_id == chunk_id

        compiled_date_stmt = str(captured_stmts[0])
        assert "max(" in compiled_date_stmt.lower()

    @pytest.mark.asyncio
    async def test_domain_level_first_resolves_min_date(self):
        """FIRST query without entity resolves MIN(document_date)."""
        pid = uuid.uuid4()
        doc_id = uuid.uuid4()
        chunk_id = uuid.uuid4()
        target_dt = date(2020, 2, 10)

        captured_stmts = []

        async def mock_exec(stmt):
            captured_stmts.append(stmt)
            if len(captured_stmts) == 1:
                res = MagicMock()
                res.scalar_one_or_none.return_value = target_dt
                return res
            elif len(captured_stmts) == 2:
                return MagicMock()
            else:
                row = MockRow(
                    chunk_id=chunk_id,
                    document_id=doc_id,
                    patient_id=pid,
                    chunk_index=0,
                    page_number=1,
                    chunk_text="Initial lab baseline",
                    document_display_name="Lab Baseline 2020",
                    document_type="lab_report",
                    document_date=target_dt,
                    cosine_distance=0.15,
                )
                res = MagicMock()
                res.all.return_value = [row]
                return res

        db = _build_mock_db(mock_exec)

        result = await retrieve_document_passages(
            db=db,
            patient_id=pid,
            query_text="What was my first lab report?",
            target_domains=["labs"],
            superlative=SuperlativeType.FIRST,
            target_entity=None,
            provider=_make_mock_provider(),
            settings=_make_mock_settings(),
        )

        assert not result.is_empty
        assert result.passages[0].document_date == target_dt

        compiled_date_stmt = str(captured_stmts[0])
        assert "min(" in compiled_date_stmt.lower()

    @pytest.mark.asyncio
    async def test_domain_level_interval_bounded_latest(self):
        """Interval-bounded latest applies start and end bounds to date query."""
        pid = uuid.uuid4()
        start = date(2024, 1, 1)
        end = date(2024, 12, 31)
        target_dt = date(2024, 11, 15)

        captured_stmts = []

        async def mock_exec(stmt):
            captured_stmts.append(stmt)
            if len(captured_stmts) == 1:
                res = MagicMock()
                res.scalar_one_or_none.return_value = target_dt
                return res
            elif len(captured_stmts) == 2:
                return MagicMock()
            else:
                row = MockRow(
                    chunk_id=uuid.uuid4(),
                    document_id=uuid.uuid4(),
                    patient_id=pid,
                    chunk_index=0,
                    page_number=1,
                    chunk_text="Late 2024 report",
                    document_display_name="Report 2024",
                    document_type="diagnostic_report",
                    document_date=target_dt,
                    cosine_distance=0.2,
                )
                res = MagicMock()
                res.all.return_value = [row]
                return res

        db = _build_mock_db(mock_exec)

        result = await retrieve_document_passages(
            db=db,
            patient_id=pid,
            query_text="What was my latest report in 2024?",
            target_domains=["reports"],
            start_date=start,
            end_date=end,
            superlative=SuperlativeType.LATEST,
            target_entity=None,
            provider=_make_mock_provider(),
            settings=_make_mock_settings(),
        )

        assert not result.is_empty
        assert result.passages[0].document_date == target_dt

        compiled = str(captured_stmts[0]).lower()
        assert ">=" in compiled
        assert "<=" in compiled

    @pytest.mark.asyncio
    async def test_domain_level_interval_bounded_first(self):
        """Interval-bounded first applies document_date >= start and <= end with MIN."""
        pid = uuid.uuid4()
        start = date(2023, 1, 1)
        end = date(2023, 12, 31)
        target_dt = date(2023, 2, 1)

        captured_stmts = []

        async def mock_exec(stmt):
            captured_stmts.append(stmt)
            if len(captured_stmts) == 1:
                res = MagicMock()
                res.scalar_one_or_none.return_value = target_dt
                return res
            elif len(captured_stmts) == 2:
                return MagicMock()
            else:
                row = MockRow(
                    chunk_id=uuid.uuid4(),
                    document_id=uuid.uuid4(),
                    patient_id=pid,
                    chunk_index=0,
                    page_number=1,
                    chunk_text="Early 2023 report",
                    document_display_name="Report 2023",
                    document_type="diagnostic_report",
                    document_date=target_dt,
                    cosine_distance=0.2,
                )
                res = MagicMock()
                res.all.return_value = [row]
                return res

        db = _build_mock_db(mock_exec)

        result = await retrieve_document_passages(
            db=db,
            patient_id=pid,
            query_text="What was my first report in 2023?",
            target_domains=["reports"],
            start_date=start,
            end_date=end,
            superlative=SuperlativeType.FIRST,
            target_entity=None,
            provider=_make_mock_provider(),
            settings=_make_mock_settings(),
        )

        assert not result.is_empty
        assert result.passages[0].document_date == target_dt
        compiled = str(captured_stmts[0]).lower()
        assert "min(" in compiled

    @pytest.mark.asyncio
    async def test_domain_level_no_dated_records_returns_empty_no_vector_search(self):
        """If MAX/MIN returns None, empty result returned without vector search."""
        pid = uuid.uuid4()
        captured_stmts = []

        async def mock_exec(stmt):
            captured_stmts.append(stmt)
            res = MagicMock()
            res.scalar_one_or_none.return_value = None
            return res

        db = _build_mock_db(mock_exec)

        result = await retrieve_document_passages(
            db=db,
            patient_id=pid,
            query_text="What is my latest report?",
            target_domains=["reports"],
            superlative=SuperlativeType.LATEST,
            target_entity=None,
            provider=_make_mock_provider(),
            settings=_make_mock_settings(),
        )

        assert result.is_empty
        assert result.passages == ()
        assert len(captured_stmts) == 1

    @pytest.mark.asyncio
    async def test_domain_level_no_dated_records_inside_interval_returns_empty(self):
        """If interval has no dated records, return empty result."""
        pid = uuid.uuid4()
        captured_stmts = []

        async def mock_exec(stmt):
            captured_stmts.append(stmt)
            res = MagicMock()
            res.scalar_one_or_none.return_value = None
            return res

        db = _build_mock_db(mock_exec)

        result = await retrieve_document_passages(
            db=db,
            patient_id=pid,
            query_text="What was my latest report in 2020?",
            target_domains=["reports"],
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            superlative=SuperlativeType.LATEST,
            target_entity=None,
            provider=_make_mock_provider(),
            settings=_make_mock_settings(),
        )

        assert result.is_empty
        assert len(captured_stmts) == 1


# ===========================================================================
# 3. Entity-Anchored Superlative Tests
# ===========================================================================


class TestEntityAnchoredSuperlative:
    """Tests covering target_entity is not None hybrid recall union and ranking."""

    @pytest.mark.asyncio
    async def test_entity_anchored_latest_cholesterol(self):
        """Latest cholesterol ranks candidates chronologically descending."""
        pid = uuid.uuid4()
        chunk_older = uuid.uuid4()
        chunk_newer = uuid.uuid4()

        row_dense = MockRow(
            chunk_id=chunk_older,
            document_id=uuid.uuid4(),
            patient_id=pid,
            chunk_index=0,
            page_number=1,
            chunk_text="Cholesterol 190 mg/dL",
            document_display_name="Lab 2023",
            document_type="lab_report",
            document_date=date(2023, 5, 1),
            cosine_distance=0.08,
        )
        row_lexical = MockRow(
            chunk_id=chunk_newer,
            document_id=uuid.uuid4(),
            patient_id=pid,
            chunk_index=0,
            page_number=1,
            chunk_text="Total Cholesterol: 175 mg/dL",
            document_display_name="Lab 2025",
            document_type="lab_report",
            document_date=date(2025, 6, 1),
        )

        call_idx = 0

        async def mock_exec(stmt):
            nonlocal call_idx
            call_idx += 1
            res = MagicMock()
            if call_idx == 1:
                return res
            elif call_idx == 2:
                res.all.return_value = [row_dense]
                return res
            elif call_idx == 3:
                res.all.return_value = [row_lexical]
                return res
            return res

        db = _build_mock_db(mock_exec)

        result = await retrieve_document_passages(
            db=db,
            patient_id=pid,
            query_text="What is my latest cholesterol?",
            target_domains=["labs"],
            superlative=SuperlativeType.LATEST,
            target_entity="cholesterol",
            provider=_make_mock_provider(),
            settings=_make_mock_settings(),
        )

        assert len(result.passages) == 2
        assert result.passages[0].chunk_id == chunk_newer
        assert result.passages[0].document_date == date(2025, 6, 1)
        assert result.passages[1].chunk_id == chunk_older
        assert result.passages[1].document_date == date(2023, 5, 1)

    @pytest.mark.asyncio
    async def test_entity_anchored_first_cholesterol(self):
        """First cholesterol ranks candidates chronologically ascending."""
        pid = uuid.uuid4()
        chunk_older = uuid.uuid4()
        chunk_newer = uuid.uuid4()

        row_dense = MockRow(
            chunk_id=chunk_newer,
            document_id=uuid.uuid4(),
            patient_id=pid,
            chunk_index=0,
            page_number=1,
            chunk_text="Total Cholesterol: 180 mg/dL",
            document_display_name="Lab 2024",
            document_type="lab_report",
            document_date=date(2024, 1, 1),
            cosine_distance=0.05,
        )
        row_lexical = MockRow(
            chunk_id=chunk_older,
            document_id=uuid.uuid4(),
            patient_id=pid,
            chunk_index=0,
            page_number=1,
            chunk_text="Cholesterol 210 mg/dL",
            document_display_name="Lab 2020",
            document_type="lab_report",
            document_date=date(2020, 3, 1),
        )

        call_idx = 0

        async def mock_exec(stmt):
            nonlocal call_idx
            call_idx += 1
            res = MagicMock()
            if call_idx == 1:
                return res
            elif call_idx == 2:
                res.all.return_value = [row_dense]
                return res
            elif call_idx == 3:
                res.all.return_value = [row_lexical]
                return res
            return res

        db = _build_mock_db(mock_exec)

        result = await retrieve_document_passages(
            db=db,
            patient_id=pid,
            query_text="What was my first cholesterol?",
            target_domains=["labs"],
            superlative=SuperlativeType.FIRST,
            target_entity="cholesterol",
            provider=_make_mock_provider(),
            settings=_make_mock_settings(),
        )

        assert len(result.passages) == 2
        assert result.passages[0].chunk_id == chunk_older
        assert result.passages[0].document_date == date(2020, 3, 1)
        assert result.passages[1].chunk_id == chunk_newer
        assert result.passages[1].document_date == date(2024, 1, 1)

    @pytest.mark.asyncio
    async def test_entity_anchored_latest_blood_pressure_variants(self):
        """blood pressure generates phrase ILIKE and token boundary predicates."""
        pid = uuid.uuid4()
        captured_stmts = []

        async def mock_exec(stmt):
            captured_stmts.append(stmt)
            res = MagicMock()
            res.all.return_value = []
            return res

        db = _build_mock_db(mock_exec)

        await retrieve_document_passages(
            db=db,
            patient_id=pid,
            query_text="What is my latest blood pressure?",
            target_domains=["clinical_documents"],
            superlative=SuperlativeType.LATEST,
            target_entity="blood pressure",
            provider=_make_mock_provider(),
            settings=_make_mock_settings(),
        )

        assert len(captured_stmts) == 3
        from sqlalchemy.dialects import postgresql

        lexical_sql = str(captured_stmts[2].compile(dialect=postgresql.dialect()))
        assert "ilike" in lexical_sql.lower()
        assert "escape '!'" in lexical_sql.lower()
        assert "~*" in lexical_sql

    @pytest.mark.asyncio
    async def test_dense_blind_latest_recovery(self):
        """When vector search returns older reports, lexical recall recovers newer."""
        pid = uuid.uuid4()
        old_chunk_1 = uuid.uuid4()
        old_chunk_2 = uuid.uuid4()
        latest_chunk = uuid.uuid4()

        dense_rows = [
            MockRow(
                chunk_id=old_chunk_1,
                document_id=uuid.uuid4(),
                patient_id=pid,
                chunk_index=0,
                page_number=1,
                chunk_text="Cholesterol: 195",
                document_display_name="Lab 2021",
                document_type="lab_report",
                document_date=date(2021, 6, 1),
                cosine_distance=0.04,
            ),
            MockRow(
                chunk_id=old_chunk_2,
                document_id=uuid.uuid4(),
                patient_id=pid,
                chunk_index=0,
                page_number=1,
                chunk_text="Cholesterol: 188",
                document_display_name="Lab 2022",
                document_type="lab_report",
                document_date=date(2022, 8, 1),
                cosine_distance=0.06,
            ),
        ]
        lexical_rows = [
            MockRow(
                chunk_id=latest_chunk,
                document_id=uuid.uuid4(),
                patient_id=pid,
                chunk_index=0,
                page_number=1,
                chunk_text="Total Cholesterol: 165",
                document_display_name="Lab 2025",
                document_type="lab_report",
                document_date=date(2025, 9, 1),
            ),
        ]

        call_idx = 0

        async def mock_exec(stmt):
            nonlocal call_idx
            call_idx += 1
            res = MagicMock()
            if call_idx == 1:
                return res
            elif call_idx == 2:
                res.all.return_value = dense_rows
                return res
            elif call_idx == 3:
                res.all.return_value = lexical_rows
                return res
            return res

        db = _build_mock_db(mock_exec)

        result = await retrieve_document_passages(
            db=db,
            patient_id=pid,
            query_text="What is my latest cholesterol?",
            target_domains=["labs"],
            superlative=SuperlativeType.LATEST,
            target_entity="cholesterol",
            provider=_make_mock_provider(),
            settings=_make_mock_settings(),
        )

        assert len(result.passages) == 3
        assert result.passages[0].chunk_id == latest_chunk
        assert result.passages[0].document_date == date(2025, 9, 1)

    @pytest.mark.asyncio
    async def test_dense_blind_first_recovery(self):
        """Lexical recall recovers earliest baseline report missed by dense search."""
        pid = uuid.uuid4()
        recent_chunk_1 = uuid.uuid4()
        recent_chunk_2 = uuid.uuid4()
        earliest_chunk = uuid.uuid4()

        dense_rows = [
            MockRow(
                chunk_id=recent_chunk_1,
                document_id=uuid.uuid4(),
                patient_id=pid,
                chunk_index=0,
                page_number=1,
                chunk_text="BP: 122/80",
                document_display_name="Clinic 2024",
                document_type="medical_record",
                document_date=date(2024, 4, 1),
                cosine_distance=0.03,
            ),
            MockRow(
                chunk_id=recent_chunk_2,
                document_id=uuid.uuid4(),
                patient_id=pid,
                chunk_index=0,
                page_number=1,
                chunk_text="BP: 120/78",
                document_display_name="Clinic 2025",
                document_type="medical_record",
                document_date=date(2025, 1, 15),
                cosine_distance=0.05,
            ),
        ]
        lexical_rows = [
            MockRow(
                chunk_id=earliest_chunk,
                document_id=uuid.uuid4(),
                patient_id=pid,
                chunk_index=0,
                page_number=1,
                chunk_text="Initial BP: 140/90",
                document_display_name="Clinic 2019",
                document_type="medical_record",
                document_date=date(2019, 1, 10),
            ),
        ]

        call_idx = 0

        async def mock_exec(stmt):
            nonlocal call_idx
            call_idx += 1
            res = MagicMock()
            if call_idx == 1:
                return res
            elif call_idx == 2:
                res.all.return_value = dense_rows
                return res
            elif call_idx == 3:
                res.all.return_value = lexical_rows
                return res
            return res

        db = _build_mock_db(mock_exec)

        result = await retrieve_document_passages(
            db=db,
            patient_id=pid,
            query_text="What was my first blood pressure?",
            target_domains=["clinical_documents"],
            superlative=SuperlativeType.FIRST,
            target_entity="blood pressure",
            provider=_make_mock_provider(),
            settings=_make_mock_settings(),
        )

        assert len(result.passages) == 3
        assert result.passages[0].chunk_id == earliest_chunk
        assert result.passages[0].document_date == date(2019, 1, 10)


# ===========================================================================
# 4. Candidate Mechanics Tests
# ===========================================================================


class TestCandidateMechanics:
    """Tests covering union deduplication, scores, bounds, and ordering guarantees."""

    @pytest.mark.asyncio
    async def test_dense_and_lexical_overlap_deduplicates_preserving_dense_score(self):
        """If a chunk is returned by both paths, it appears once with dense scores."""
        pid = uuid.uuid4()
        shared_chunk_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        dt = date(2024, 5, 1)

        row_dense = MockRow(
            chunk_id=shared_chunk_id,
            document_id=doc_id,
            patient_id=pid,
            chunk_index=0,
            page_number=1,
            chunk_text="Cholesterol 180",
            document_display_name="Lab 2024",
            document_type="lab_report",
            document_date=dt,
            cosine_distance=0.15,
        )
        row_lexical = MockRow(
            chunk_id=shared_chunk_id,
            document_id=doc_id,
            patient_id=pid,
            chunk_index=0,
            page_number=1,
            chunk_text="Cholesterol 180",
            document_display_name="Lab 2024",
            document_type="lab_report",
            document_date=dt,
        )

        call_idx = 0

        async def mock_exec(stmt):
            nonlocal call_idx
            call_idx += 1
            res = MagicMock()
            if call_idx == 1:
                return res
            elif call_idx == 2:
                res.all.return_value = [row_dense]
                return res
            elif call_idx == 3:
                res.all.return_value = [row_lexical]
                return res
            return res

        db = _build_mock_db(mock_exec)

        result = await retrieve_document_passages(
            db=db,
            patient_id=pid,
            query_text="latest cholesterol",
            target_domains=["labs"],
            superlative=SuperlativeType.LATEST,
            target_entity="cholesterol",
            provider=_make_mock_provider(),
            settings=_make_mock_settings(),
        )

        assert len(result.passages) == 1
        passage = result.passages[0]
        assert passage.chunk_id == shared_chunk_id
        assert passage.cosine_distance == 0.15
        assert passage.similarity == pytest.approx(0.85)

    @pytest.mark.asyncio
    async def test_dense_only_candidate_preserved(self):
        """Dense-only candidate is preserved with original scores."""
        pid = uuid.uuid4()
        dense_chunk_id = uuid.uuid4()

        row_dense = MockRow(
            chunk_id=dense_chunk_id,
            document_id=uuid.uuid4(),
            patient_id=pid,
            chunk_index=0,
            page_number=1,
            chunk_text="Lipid panel results",
            document_display_name="Lab 2024",
            document_type="lab_report",
            document_date=date(2024, 3, 1),
            cosine_distance=0.18,
        )

        call_idx = 0

        async def mock_exec(stmt):
            nonlocal call_idx
            call_idx += 1
            res = MagicMock()
            if call_idx == 1:
                return res
            elif call_idx == 2:
                res.all.return_value = [row_dense]
                return res
            elif call_idx == 3:
                res.all.return_value = []
                return res
            return res

        db = _build_mock_db(mock_exec)

        result = await retrieve_document_passages(
            db=db,
            patient_id=pid,
            query_text="latest cholesterol",
            target_domains=["labs"],
            superlative=SuperlativeType.LATEST,
            target_entity="cholesterol",
            provider=_make_mock_provider(),
            settings=_make_mock_settings(),
        )

        assert len(result.passages) == 1
        assert result.passages[0].chunk_id == dense_chunk_id
        assert result.passages[0].cosine_distance == 0.18

    @pytest.mark.asyncio
    async def test_lexical_only_candidate_receives_sentinel_cosine_score(self):
        """Lexical-only candidates receive documented sentinel cosine_distance=0.0."""
        pid = uuid.uuid4()
        lexical_chunk_id = uuid.uuid4()

        row_lexical = MockRow(
            chunk_id=lexical_chunk_id,
            document_id=uuid.uuid4(),
            patient_id=pid,
            chunk_index=0,
            page_number=1,
            chunk_text="Total cholesterol 200",
            document_display_name="Lab 2025",
            document_type="lab_report",
            document_date=date(2025, 1, 1),
        )

        call_idx = 0

        async def mock_exec(stmt):
            nonlocal call_idx
            call_idx += 1
            res = MagicMock()
            if call_idx == 1:
                return res
            elif call_idx == 2:
                res.all.return_value = []
                return res
            elif call_idx == 3:
                res.all.return_value = [row_lexical]
                return res
            return res

        db = _build_mock_db(mock_exec)

        result = await retrieve_document_passages(
            db=db,
            patient_id=pid,
            query_text="latest cholesterol",
            target_domains=["labs"],
            superlative=SuperlativeType.LATEST,
            target_entity="cholesterol",
            provider=_make_mock_provider(),
            settings=_make_mock_settings(),
        )

        assert len(result.passages) == 1
        passage = result.passages[0]
        assert passage.chunk_id == lexical_chunk_id
        assert passage.cosine_distance == LEXICAL_SENTINEL_COSINE_DISTANCE
        assert passage.similarity == 1.0

    @pytest.mark.asyncio
    async def test_union_bound_less_or_equal_20(self):
        """Candidate union |U| <= 20 prior to/after deduplication."""
        pid = uuid.uuid4()
        dense_rows = [
            MockRow(
                chunk_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                patient_id=pid,
                chunk_index=i,
                page_number=1,
                chunk_text=f"Dense passage {i}",
                document_display_name="Doc",
                document_type="lab_report",
                document_date=date(2024, 1, 1 + i),
                cosine_distance=0.1 * i,
            )
            for i in range(10)
        ]
        lexical_rows = [
            MockRow(
                chunk_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                patient_id=pid,
                chunk_index=i,
                page_number=1,
                chunk_text=f"Lexical passage {i}",
                document_display_name="Doc",
                document_type="lab_report",
                document_date=date(2024, 2, 1 + i),
            )
            for i in range(10)
        ]

        call_idx = 0

        async def mock_exec(stmt):
            nonlocal call_idx
            call_idx += 1
            res = MagicMock()
            if call_idx == 1:
                return res
            elif call_idx == 2:
                res.all.return_value = dense_rows
                return res
            elif call_idx == 3:
                res.all.return_value = lexical_rows
                return res
            return res

        db = _build_mock_db(mock_exec)

        result = await retrieve_document_passages(
            db=db,
            patient_id=pid,
            query_text="latest cholesterol",
            target_domains=["labs"],
            superlative=SuperlativeType.LATEST,
            target_entity="cholesterol",
            provider=_make_mock_provider(),
            settings=_make_mock_settings(),
        )

        assert len(result.passages) <= 20
        assert len(result.passages) == 20

    def test_k_dense_and_k_lexical_constants(self):
        """Locked constants K_DENSE=10 and K_LEXICAL=10."""
        assert K_DENSE == 10
        assert K_LEXICAL == 10

    @pytest.mark.asyncio
    async def test_caller_top_k_10_raises_retrieval_input_error(self):
        """Passing top_k=10 from caller raises RetrievalInputError."""
        db = AsyncMock()
        cfg = _make_mock_settings(default_k=3, max_k=5)

        with pytest.raises(RetrievalInputError, match="top_k must be between 1 and 5"):
            await retrieve_document_passages(
                db=db,
                patient_id=uuid.uuid4(),
                query_text="my query",
                target_domains=["labs"],
                top_k=10,
                superlative=SuperlativeType.LATEST,
                target_entity="cholesterol",
                provider=_make_mock_provider(),
                settings=cfg,
            )

    @pytest.mark.asyncio
    async def test_deterministic_output_under_candidate_order_permutation(self):
        """Candidate ranking must be deterministic regardless of row order."""
        pid = uuid.uuid4()
        d1 = date(2025, 6, 1)
        d2 = date(2025, 6, 1)
        doc1 = uuid.UUID("00000000-0000-0000-0000-000000000001")
        doc2 = uuid.UUID("00000000-0000-0000-0000-000000000002")

        row_a = MockRow(
            chunk_id=uuid.uuid4(),
            document_id=doc1,
            patient_id=pid,
            chunk_index=0,
            page_number=1,
            chunk_text="text a",
            document_display_name="Doc 1",
            document_type="lab_report",
            document_date=d1,
            cosine_distance=0.1,
        )
        row_b = MockRow(
            chunk_id=uuid.uuid4(),
            document_id=doc2,
            patient_id=pid,
            chunk_index=1,
            page_number=1,
            chunk_text="text b",
            document_display_name="Doc 2",
            document_type="lab_report",
            document_date=d2,
            cosine_distance=0.2,
        )

        async def run_with_order(rows_dense, rows_lexical):
            call_idx = 0

            async def mock_exec(stmt):
                nonlocal call_idx
                call_idx += 1
                res = MagicMock()
                if call_idx == 1:
                    return res
                elif call_idx == 2:
                    res.all.return_value = rows_dense
                    return res
                elif call_idx == 3:
                    res.all.return_value = rows_lexical
                    return res
                return res

            db = _build_mock_db(mock_exec)
            res = await retrieve_document_passages(
                db=db,
                patient_id=pid,
                query_text="latest cholesterol",
                target_domains=["labs"],
                superlative=SuperlativeType.LATEST,
                target_entity="cholesterol",
                provider=_make_mock_provider(),
                settings=_make_mock_settings(),
            )
            return [p.document_id for p in res.passages]

        order_1 = await run_with_order([row_a, row_b], [])
        order_2 = await run_with_order([row_b, row_a], [])
        assert order_1 == order_2 == [doc1, doc2]

    @pytest.mark.asyncio
    async def test_tenant_isolation_enforced_in_both_paths(self):
        """Both dense and lexical queries must strictly filter by patient_id."""
        pid = uuid.uuid4()
        captured_stmts = []

        async def mock_exec(stmt):
            captured_stmts.append(stmt)
            res = MagicMock()
            res.all.return_value = []
            return res

        db = _build_mock_db(mock_exec)

        await retrieve_document_passages(
            db=db,
            patient_id=pid,
            query_text="latest cholesterol",
            target_domains=["labs"],
            superlative=SuperlativeType.LATEST,
            target_entity="cholesterol",
            provider=_make_mock_provider(),
            settings=_make_mock_settings(),
        )

        dense_sql = str(captured_stmts[1]).lower()
        lexical_sql = str(captured_stmts[2]).lower()

        assert "patient_id" in dense_sql
        assert "patient_id" in lexical_sql

    @pytest.mark.asyncio
    async def test_dated_candidates_only_for_superlative_paths(self):
        """Superlative paths must strictly require document_date IS NOT NULL."""
        pid = uuid.uuid4()
        captured_stmts = []

        async def mock_exec(stmt):
            captured_stmts.append(stmt)
            res = MagicMock()
            res.all.return_value = []
            return res

        db = _build_mock_db(mock_exec)

        await retrieve_document_passages(
            db=db,
            patient_id=pid,
            query_text="latest cholesterol",
            target_domains=["labs"],
            superlative=SuperlativeType.LATEST,
            target_entity="cholesterol",
            provider=_make_mock_provider(),
            settings=_make_mock_settings(),
        )

        dense_sql = str(captured_stmts[1]).lower()
        lexical_sql = str(captured_stmts[2]).lower()

        assert "document_date is not null" in dense_sql
        assert "document_date is not null" in lexical_sql

    @pytest.mark.asyncio
    async def test_ordinary_non_superlative_permits_null_document_date(self):
        """When superlative is None and no date bounds, document_date can be NULL."""
        pid = uuid.uuid4()
        captured_stmts = []

        async def mock_exec(stmt):
            captured_stmts.append(stmt)
            res = MagicMock()
            res.all.return_value = []
            return res

        db = _build_mock_db(mock_exec)

        await retrieve_document_passages(
            db=db,
            patient_id=pid,
            query_text="cholesterol levels",
            target_domains=["labs"],
            superlative=None,
            target_entity=None,
            provider=_make_mock_provider(),
            settings=_make_mock_settings(),
        )

        assert len(captured_stmts) == 2
        ordinary_sql = str(captured_stmts[1]).lower()
        assert "document_date is not null" not in ordinary_sql


# ===========================================================================
# 5. HybridRetrievalEngine Wrapper Tests
# ===========================================================================


class TestHybridRetrievalEngineWrapper:
    """Verify delegation from HybridRetrievalEngine to retrieve_document_passages."""

    @pytest.mark.asyncio
    async def test_hybrid_engine_forwards_superlative_and_target_entity(self):
        """HybridRetrievalEngine.retrieve forwards superlative and target_entity."""
        pid = uuid.uuid4()

        with patch(
            "app.health.retrieval.retrieve_document_passages",
            new_callable=AsyncMock,
        ) as mock_func:
            expected = RetrievalResult(
                patient_id=pid,
                target_domains=("labs",),
                query_text="latest cholesterol",
                top_k=3,
                passages=(),
            )
            mock_func.return_value = expected

            engine = HybridRetrievalEngine()
            db = AsyncMock()

            result = await engine.retrieve(
                db=db,
                patient_id=pid,
                query_text="latest cholesterol",
                target_domains=["labs"],
                top_k=3,
                superlative=SuperlativeType.LATEST,
                target_entity="cholesterol",
            )

            assert result is expected
            mock_func.assert_awaited_once_with(
                db=db,
                patient_id=pid,
                query_text="latest cholesterol",
                target_domains=["labs"],
                top_k=3,
                superlative=SuperlativeType.LATEST,
                target_entity="cholesterol",
                provider=None,
                settings=None,
            )
