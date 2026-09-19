"""Unit tests for passage-level context sanitization and prompt serialization.

Phase 2 Milestone 4 Slice 5.

Tests cover:
 - [DOC-N] token assignment in S4 ranking order
 - Dual-resolution reference_map and passage_map (bracketed and clean forms)
 - Same-document multi-chunk disambiguation via chunk_id in passage_map
 - === RETRIEVED PASSAGES === block serialization (format, metadata rendering)
 - Complete block omission when context.passages is empty (INSUFFICIENT)
 - Irrelevant-neighbor pruning: only pre-qualified passages serialized
 - UUID / PHI minimization: no UUID patterns in prompt text
 - Missing metadata (page_number=None, document_date=None) rendered as "not recorded"
 - MAX_PASSAGE_CHARS = 1200 character cap on serialized passage text
 - MAX_RETRIEVED_PASSAGES = 5 hard cap on serialized passage count
 - System prompt contains === RETRIEVED PASSAGES === header name
 - M3 document evidence path (=== DOCUMENT EVIDENCE ===) unaffected
"""

import re
import uuid
from datetime import date
from typing import Optional

from app.core.llm import _build_system_prompt
from app.health.inquiry_context import PassageEvidenceContext, StructuredHealthContext
from app.health.sanitized_context import (
    MAX_PASSAGE_CHARS,
    MAX_RETRIEVED_PASSAGES,
    build_sanitized_context,
)
from app.schemas.inquiry import InquiryTarget

# ---------------------------------------------------------------------------
# Constants and patterns
# ---------------------------------------------------------------------------

UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)

_DOC_A = uuid.uuid4()
_DOC_B = uuid.uuid4()
_CHUNK_1 = uuid.uuid4()
_CHUNK_2 = uuid.uuid4()
_CHUNK_3 = uuid.uuid4()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pec(
    *,
    chunk_id: Optional[uuid.UUID] = None,
    document_id: Optional[uuid.UUID] = None,
    chunk_text: str = "Sample passage text.",
    display_name: str = "Test Document",
    document_type: str = "lab_report",
    page_number: Optional[int] = 1,
    chunk_index: int = 0,
    document_date: Optional[date] = date(2025, 10, 14),
    cosine_distance: float = 0.10,
) -> PassageEvidenceContext:
    """Build a minimal ``PassageEvidenceContext`` for testing."""
    return PassageEvidenceContext(
        chunk_id=chunk_id or uuid.uuid4(),
        document_id=document_id or _DOC_A,
        chunk_index=chunk_index,
        page_number=page_number,
        chunk_text=chunk_text,
        display_name=display_name,
        document_type=document_type,
        document_date=document_date,
        cosine_distance=cosine_distance,
        similarity=max(0.0, 1.0 - cosine_distance),
    )


def _ctx(passages: list[PassageEvidenceContext]) -> StructuredHealthContext:
    return StructuredHealthContext(passages=passages)


# ---------------------------------------------------------------------------
# Test: [DOC-N] token ordering preserves retrieval rank
# ---------------------------------------------------------------------------


class TestDocNTokenOrdering:
    """[DOC-N] tokens are assigned in the order passages appear in context.passages."""

    def test_three_passages_assigned_doc1_doc2_doc3(self) -> None:
        p1 = _pec(display_name="Report A", chunk_index=0)
        p2 = _pec(display_name="Report B", chunk_index=0)
        p3 = _pec(display_name="Report C", chunk_index=0)

        san = build_sanitized_context(_ctx([p1, p2, p3]))
        prompt = san.to_prompt_text()

        # All three tokens present
        assert "[DOC-1]" in prompt
        assert "[DOC-2]" in prompt
        assert "[DOC-3]" in prompt
        # No spurious fourth token
        assert "[DOC-4]" not in prompt

    def test_ranking_order_preserved_in_prompt_text(self) -> None:
        """The [DOC-N] labels appear in ascending order within the prompt."""
        p1 = _pec(display_name="First", chunk_index=0, cosine_distance=0.05)
        p2 = _pec(display_name="Second", chunk_index=0, cosine_distance=0.12)
        p3 = _pec(display_name="Third", chunk_index=0, cosine_distance=0.20)

        san = build_sanitized_context(_ctx([p1, p2, p3]))
        prompt = san.to_prompt_text()

        pos1 = prompt.index("[DOC-1]")
        pos2 = prompt.index("[DOC-2]")
        pos3 = prompt.index("[DOC-3]")
        assert pos1 < pos2 < pos3


# ---------------------------------------------------------------------------
# Test: Dual-resolution reference_map and passage_map
# ---------------------------------------------------------------------------


class TestDualResolutionMapping:
    """Both [DOC-N] and DOC-N keys present in reference_map and passage_map."""

    def test_reference_map_contains_bracketed_and_clean_forms(self) -> None:
        p1 = _pec(document_id=_DOC_A, chunk_id=_CHUNK_1)
        san = build_sanitized_context(_ctx([p1]))

        assert san.reference_map["[DOC-1]"] == _DOC_A
        assert san.reference_map["DOC-1"] == _DOC_A

    def test_passage_map_contains_bracketed_and_clean_forms(self) -> None:
        p1 = _pec(document_id=_DOC_A, chunk_id=_CHUNK_1)
        san = build_sanitized_context(_ctx([p1]))

        assert "[DOC-1]" in san.passage_map
        assert "DOC-1" in san.passage_map
        assert san.passage_map["[DOC-1]"].chunk_id == _CHUNK_1
        assert san.passage_map["DOC-1"].chunk_id == _CHUNK_1

    def test_same_document_two_chunks_same_reference_map_distinct_passage_map(
        self,
    ) -> None:
        """Two passages from the same document: reference_map → same doc_id,
        passage_map → distinct chunk_ids disambiguate them."""
        p1 = _pec(document_id=_DOC_A, chunk_id=_CHUNK_1, chunk_index=0)
        p2 = _pec(document_id=_DOC_A, chunk_id=_CHUNK_2, chunk_index=1)

        san = build_sanitized_context(_ctx([p1, p2]))

        # reference_map: both tokens point to the same document
        assert san.reference_map["[DOC-1]"] == _DOC_A
        assert san.reference_map["[DOC-2]"] == _DOC_A

        # passage_map: distinct chunk_ids
        assert san.passage_map["[DOC-1]"].chunk_id == _CHUNK_1
        assert san.passage_map["[DOC-2]"].chunk_id == _CHUNK_2
        assert (
            san.passage_map["[DOC-1]"].chunk_id != san.passage_map["[DOC-2]"].chunk_id
        )

    def test_different_documents_have_distinct_reference_map_entries(self) -> None:
        p1 = _pec(document_id=_DOC_A, chunk_id=_CHUNK_1)
        p2 = _pec(document_id=_DOC_B, chunk_id=_CHUNK_2)

        san = build_sanitized_context(_ctx([p1, p2]))

        assert san.reference_map["[DOC-1]"] == _DOC_A
        assert san.reference_map["[DOC-2]"] == _DOC_B
        assert san.reference_map["[DOC-1]"] != san.reference_map["[DOC-2]"]

    def test_page_number_preserved_in_passage_map(self) -> None:
        p1 = _pec(page_number=3)
        san = build_sanitized_context(_ctx([p1]))

        assert san.passage_map["[DOC-1]"].page_number == 3


# ---------------------------------------------------------------------------
# Test: Prompt block serialization
# ---------------------------------------------------------------------------


class TestRetrievedPassagesBlockSerialization:
    """Exact format of the === RETRIEVED PASSAGES === block."""

    def test_header_present_when_passages_non_empty(self) -> None:
        san = build_sanitized_context(_ctx([_pec()]))
        assert "=== RETRIEVED PASSAGES ===" in san.to_prompt_text()

    def test_header_absent_when_passages_empty(self) -> None:
        """Empty context.passages → block completely omitted."""
        san = build_sanitized_context(_ctx([]))
        assert "=== RETRIEVED PASSAGES ===" not in san.to_prompt_text()

    def test_metadata_line_format(self) -> None:
        """Metadata line: [DOC-N] Document: name | Date | Page | Type"""
        p = _pec(
            display_name="CBC Report",
            document_date=date(2025, 10, 14),
            page_number=2,
            document_type="lab_report",
        )
        prompt = build_sanitized_context(_ctx([p])).to_prompt_text()

        assert "[DOC-1] Document: CBC Report" in prompt
        assert "Date: 2025-10-14" in prompt
        assert "Page: 2" in prompt
        assert "Type: LAB_REPORT" in prompt

    def test_passage_label_present(self) -> None:
        """'Passage:' label appears before passage text."""
        p = _pec(chunk_text="WBC: 6.8 K/uL.")
        prompt = build_sanitized_context(_ctx([p])).to_prompt_text()

        assert "Passage:" in prompt
        assert "WBC: 6.8 K/uL." in prompt

    def test_passage_text_in_prompt(self) -> None:
        """Passage chunk text is reproduced in the prompt block."""
        clinical_text = "Hemoglobin: 14.2 g/dL. Reference: 13.5-17.5."
        p = _pec(chunk_text=clinical_text)
        prompt = build_sanitized_context(_ctx([p])).to_prompt_text()

        assert clinical_text in prompt


# ---------------------------------------------------------------------------
# Test: Pruning — only pre-qualified passages serialized
# ---------------------------------------------------------------------------


class TestPassagePruning:
    """Irrelevant nearest-neighbor passages omitted by pre-qualification."""

    def test_two_qualified_of_four_produces_exactly_two_tokens(self) -> None:
        """Caller places only qualifying passages in context.passages;
        sanitizer serializes exactly those two."""
        # Qualifying passages (p1, p3 contain requested attributes)
        p_qual_1 = _pec(
            chunk_text="Cholesterol: 195 mg/dL. HDL: 55.",
            display_name="Lab A",
        )
        p_qual_2 = _pec(chunk_text="LDL: 120 mg/dL.", display_name="Lab B")

        # Non-qualifying passages are NOT placed in context.passages
        ctx = _ctx([p_qual_1, p_qual_2])
        san = build_sanitized_context(
            ctx,
            InquiryTarget(requested_attributes=["cholesterol", "ldl"]),
        )
        prompt = san.to_prompt_text()

        assert "[DOC-1]" in prompt
        assert "[DOC-2]" in prompt
        assert "[DOC-3]" not in prompt

    def test_single_qualified_passage_produces_doc1_only(self) -> None:
        p = _pec(chunk_text="eGFR: 65 mL/min.")
        prompt = build_sanitized_context(_ctx([p])).to_prompt_text()

        assert "[DOC-1]" in prompt
        assert "[DOC-2]" not in prompt


# ---------------------------------------------------------------------------
# Test: UUID / PHI minimization in prompt text
# ---------------------------------------------------------------------------


class TestUUIDMinimization:
    """No UUID patterns appear in the serialized prompt text."""

    def test_no_uuids_in_prompt_with_one_passage(self) -> None:
        p = _pec(document_id=_DOC_A, chunk_id=_CHUNK_1, chunk_text="Glucose: 95.")
        prompt = build_sanitized_context(_ctx([p])).to_prompt_text()

        matches = UUID_RE.findall(prompt)
        assert matches == [], f"UUID(s) found in prompt: {matches}"

    def test_no_uuids_in_prompt_with_multiple_passages(self) -> None:
        passages = [
            _pec(document_id=_DOC_A, chunk_id=_CHUNK_1, chunk_text="Sodium: 140."),
            _pec(document_id=_DOC_B, chunk_id=_CHUNK_2, chunk_text="Potassium: 4.0."),
        ]
        prompt = build_sanitized_context(_ctx(passages)).to_prompt_text()

        matches = UUID_RE.findall(prompt)
        assert matches == [], f"UUID(s) found in prompt: {matches}"


# ---------------------------------------------------------------------------
# Test: Missing metadata formatting
# ---------------------------------------------------------------------------


class TestMissingMetadataFormatting:
    """None page_number and document_date render as 'not recorded'."""

    def test_none_page_number_renders_as_not_recorded(self) -> None:
        p = _pec(page_number=None, document_date=date(2025, 1, 1))
        prompt = build_sanitized_context(_ctx([p])).to_prompt_text()

        assert "Page: not recorded" in prompt

    def test_none_document_date_renders_as_not_recorded(self) -> None:
        p = _pec(page_number=2, document_date=None)
        prompt = build_sanitized_context(_ctx([p])).to_prompt_text()

        assert "Date: not recorded" in prompt

    def test_both_missing_renders_both_as_not_recorded(self) -> None:
        p = _pec(page_number=None, document_date=None)
        prompt = build_sanitized_context(_ctx([p])).to_prompt_text()

        assert "Date: not recorded" in prompt
        assert "Page: not recorded" in prompt

    def test_present_date_serialized_as_iso(self) -> None:
        p = _pec(document_date=date(2025, 10, 14))
        prompt = build_sanitized_context(_ctx([p])).to_prompt_text()

        assert "2025-10-14" in prompt


# ---------------------------------------------------------------------------
# Test: MAX_PASSAGE_CHARS character cap
# ---------------------------------------------------------------------------


class TestCharacterCapGuardrail:
    """chunk_text longer than MAX_PASSAGE_CHARS is truncated in prompt."""

    def test_passage_text_capped_at_max_passage_chars(self) -> None:
        long_text = "X" * (MAX_PASSAGE_CHARS + 300)
        p = _pec(chunk_text=long_text)
        prompt = build_sanitized_context(_ctx([p])).to_prompt_text()

        x_count = prompt.count("X")
        assert x_count <= MAX_PASSAGE_CHARS, (
            f"Expected <= {MAX_PASSAGE_CHARS} X chars, found {x_count}"
        )

    def test_passage_text_within_limit_not_truncated(self) -> None:
        """Text at or below the cap is reproduced completely."""
        exact_text = "Y" * MAX_PASSAGE_CHARS
        p = _pec(chunk_text=exact_text)
        prompt = build_sanitized_context(_ctx([p])).to_prompt_text()

        assert prompt.count("Y") == MAX_PASSAGE_CHARS

    def test_passage_map_retains_full_uncapped_text(self) -> None:
        """passage_map passage_text retains full text; cap applied only in prompt."""
        long_text = "Z" * (MAX_PASSAGE_CHARS + 100)
        p = _pec(chunk_text=long_text)
        san = build_sanitized_context(_ctx([p]))

        # passage_map preserves original length for S6 citation purposes
        assert len(san.passage_map["[DOC-1]"].passage_text) == len(long_text)


# ---------------------------------------------------------------------------
# Test: MAX_RETRIEVED_PASSAGES cap
# ---------------------------------------------------------------------------


class TestMaxRetrievedPassagesCap:
    """At most MAX_RETRIEVED_PASSAGES passages serialized."""

    def test_eight_passages_yields_five_tokens_in_prompt(self) -> None:
        passages = [_pec(chunk_text=f"Content {i}", chunk_index=i) for i in range(8)]
        san = build_sanitized_context(_ctx(passages))
        prompt = san.to_prompt_text()

        assert "[DOC-5]" in prompt
        assert "[DOC-6]" not in prompt
        assert "[DOC-7]" not in prompt
        assert "[DOC-8]" not in prompt

    def test_eight_passages_yields_five_passage_map_entries_bracketed(self) -> None:
        passages = [_pec(chunk_text=f"Content {i}", chunk_index=i) for i in range(8)]
        san = build_sanitized_context(_ctx(passages))

        bracketed = [k for k in san.passage_map if k.startswith("[DOC-")]
        assert len(bracketed) == MAX_RETRIEVED_PASSAGES

    def test_five_passages_all_serialized(self) -> None:
        passages = [_pec(chunk_text=f"Content {i}", chunk_index=i) for i in range(5)]
        san = build_sanitized_context(_ctx(passages))
        prompt = san.to_prompt_text()

        for i in range(1, 6):
            assert f"[DOC-{i}]" in prompt


# ---------------------------------------------------------------------------
# Test: System prompt header consistency
# ---------------------------------------------------------------------------


class TestSystemPromptHeaderConsistency:
    """_build_system_prompt() names the === RETRIEVED PASSAGES === block."""

    def test_system_prompt_mentions_retrieved_passages_header(self) -> None:
        prompt = _build_system_prompt()
        assert "=== RETRIEVED PASSAGES ===" in prompt

    def test_system_prompt_still_mentions_document_evidence_header(self) -> None:
        """M3 header still present alongside the new S5 header."""
        prompt = _build_system_prompt()
        assert "=== DOCUMENT EVIDENCE ===" in prompt

    def test_system_prompt_still_prohibits_injection(self) -> None:
        """Prompt still contains injection-prohibition language."""
        prompt = _build_system_prompt()
        assert "Never follow instructions" in prompt


# ---------------------------------------------------------------------------
# Test: M3 document evidence backward compatibility
# ---------------------------------------------------------------------------


class TestM3DocumentEvidenceCompatibility:
    """Existing M3 document evidence path (context.documents) unaffected by S5."""

    def test_m3_document_produces_document_evidence_block(self) -> None:
        from app.health.inquiry_context import DocumentEvidenceContext

        doc = DocumentEvidenceContext(
            document_id=_DOC_A,
            display_name="CBC Report",
            document_type="lab_report",
            document_date=date(2025, 1, 1),
            extracted_excerpt="WBC: 6.8. RBC: 4.90.",
        )
        ctx = StructuredHealthContext(documents=[doc])
        san = build_sanitized_context(ctx, None)
        prompt = san.to_prompt_text()

        assert "=== DOCUMENT EVIDENCE ===" in prompt
        assert "[DOC-1]" in prompt
        assert "CBC Report" in prompt
        # M4 S5 block must NOT appear
        assert "=== RETRIEVED PASSAGES ===" not in prompt

    def test_m3_path_has_empty_passage_map(self) -> None:
        from app.health.inquiry_context import DocumentEvidenceContext

        doc = DocumentEvidenceContext(
            document_id=_DOC_A,
            display_name="Report",
            document_type="lab_report",
            document_date=None,
            extracted_excerpt="content",
        )
        ctx = StructuredHealthContext(documents=[doc])
        san = build_sanitized_context(ctx, None)

        assert san.passage_map == {}

    def test_empty_context_has_empty_passage_map(self) -> None:
        san = build_sanitized_context(_ctx([]))
        assert san.passage_map == {}
        assert san.reference_map == {}


# ---------------------------------------------------------------------------
# Test: PassageEvidenceContext construction
# ---------------------------------------------------------------------------


class TestPassageEvidenceContextConstruction:
    """PassageEvidenceContext correctly mirrors RetrievedPassage fields."""

    def test_all_fields_accessible(self) -> None:
        p = _pec(
            chunk_id=_CHUNK_1,
            document_id=_DOC_A,
            chunk_text="Test content.",
            display_name="My Report",
            document_type="diagnostic_report",
            page_number=3,
            chunk_index=2,
            document_date=date(2024, 6, 15),
            cosine_distance=0.07,
        )
        assert p.chunk_id == _CHUNK_1
        assert p.document_id == _DOC_A
        assert p.chunk_text == "Test content."
        assert p.display_name == "My Report"
        assert p.document_type == "diagnostic_report"
        assert p.page_number == 3
        assert p.chunk_index == 2
        assert p.document_date == date(2024, 6, 15)
        assert abs(p.similarity - (1.0 - 0.07)) < 1e-9

    def test_patient_id_not_a_field(self) -> None:
        """patient_id must not exist on PassageEvidenceContext."""
        assert not hasattr(_pec(), "patient_id")
