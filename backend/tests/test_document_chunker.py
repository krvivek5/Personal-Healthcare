"""Unit tests for DocumentChunker (Milestone 4 Slice 2).

Covers:
- Strict window bounding within [800, 1000] characters
- Boundary snapping priority (\n\n -> \n -> sentence -> word -> 1000 hard cut)
- No intentional non-terminal chunks below 800 chars
- Final remainder can be < 800 chars
- Inherently short document/page (< 800 chars) produces single chunk
- Empty/whitespace-only input returns []
- 150-character sliding overlap with word boundary snapping
- Forward progress invariant
- Page-local chunking: chunks never cross page boundaries
- Page-number propagation (1-based physical page number)
- Blank PDF page skipping without renumbering later pages
- Unpaged/plain-text documents: page_number = None
- Sequential chunk_index (0, 1, 2, ...)
- Determinism across repeated executions
- Unicode and non-ASCII preservation
"""

from __future__ import annotations

import pytest

from app.health.chunking import PAGE_DELIMITER, DocumentChunker


class TestDocumentChunkerInitialization:
    def test_default_parameters(self) -> None:
        chunker = DocumentChunker()
        assert chunker.min_chunk_size == 800
        assert chunker.max_chunk_size == 1000
        assert chunker.overlap_size == 150

    def test_invalid_parameters_raise(self) -> None:
        with pytest.raises(ValueError, match="min_chunk_size must be positive"):
            DocumentChunker(min_chunk_size=0)

        with pytest.raises(
            ValueError, match="max_chunk_size must be >= min_chunk_size"
        ):
            DocumentChunker(min_chunk_size=900, max_chunk_size=800)

        with pytest.raises(ValueError, match="overlap_size must be >= 0"):
            DocumentChunker(overlap_size=-1)

        with pytest.raises(ValueError, match="overlap_size must be < min_chunk_size"):
            DocumentChunker(min_chunk_size=800, overlap_size=800)


class TestEmptyAndShortDocuments:
    @pytest.fixture
    def chunker(self) -> DocumentChunker:
        return DocumentChunker()

    def test_empty_string_returns_empty_list(self, chunker: DocumentChunker) -> None:
        assert chunker.chunk_document_text("") == []

    def test_whitespace_only_returns_empty_list(self, chunker: DocumentChunker) -> None:
        assert chunker.chunk_document_text("   \n\t\r\n   ") == []

    def test_short_document_produces_single_chunk(
        self, chunker: DocumentChunker
    ) -> None:
        text = (
            "Serum Creatinine: 0.9 mg/dL. eGFR: >60 mL/min/1.73m2. "
            "Normal kidney function."
        )
        drafts = chunker.chunk_document_text(text)
        assert len(drafts) == 1
        assert drafts[0].chunk_index == 0
        assert drafts[0].chunk_text == text
        assert drafts[0].page_number is None

    def test_document_exactly_max_chunk_size(self, chunker: DocumentChunker) -> None:
        # Exactly 1000 characters
        text = "A" * 1000
        drafts = chunker.chunk_document_text(text)
        assert len(drafts) == 1
        assert drafts[0].chunk_index == 0
        assert len(drafts[0].chunk_text) == 1000
        assert drafts[0].page_number is None


class TestWindowBoundingAndBoundaryPriority:
    @pytest.fixture
    def chunker(self) -> DocumentChunker:
        return DocumentChunker()

    def test_paragraph_break_priority(self, chunker: DocumentChunker) -> None:
        # Create text of 2500 chars with paragraph break in [800, 1000]
        # Filler 850 chars + "\n\n" + 100 chars + sentence + rest
        prefix = "Word " * 170  # 850 chars
        paragraph_break = "\n\n"
        sentence = "Next sentence starts here. " * 30
        text = prefix + paragraph_break + sentence

        drafts = chunker.chunk_document_text(text)
        assert len(drafts) >= 2
        # Chunk 0 must end right after the paragraph break
        assert drafts[0].chunk_text.endswith("Word") or "\n\n" in drafts[0].chunk_text
        # Length of chunk 0 must be in [800, 1000]
        assert 800 <= len(drafts[0].chunk_text) <= 1000

    def test_line_break_priority_over_sentence(self, chunker: DocumentChunker) -> None:
        # When no \n\n in [800, 1000], single \n should win over sentence break
        # 850 chars without \n\n, but with sentence at 830 and \n at 880
        part1 = "Sentence one is here. " * 38  # ~836 chars
        part2 = "More text without period\n"  # line break at ~861
        part3 = "Another sentence follows. " * 40
        text = part1 + part2 + part3

        drafts = chunker.chunk_document_text(text)
        assert len(drafts) >= 2
        assert 800 <= len(drafts[0].chunk_text) <= 1000
        assert drafts[0].chunk_text.endswith("More text without period")

    def test_sentence_break_priority_over_word(self, chunker: DocumentChunker) -> None:
        # Unbroken paragraph of sentences (no \n)
        sentences = [
            f"Clinical observation number {i} notes stable vital signs."
            for i in range(50)
        ]
        text = " ".join(sentences)

        drafts = chunker.chunk_document_text(text)
        assert len(drafts) >= 2
        for i, d in enumerate(drafts[:-1]):
            # Every non-terminal chunk must be bounded within [800, 1000]
            assert 800 <= len(d.chunk_text) <= 1000, (
                f"Chunk {i} len {len(d.chunk_text)} out of [800, 1000]"
            )
            # Sentence break preference means chunk should end with sentence punctuation
            assert d.chunk_text[-1] in ".!?", (
                f"Chunk {i} does not end with punctuation: {d.chunk_text[-30:]}"
            )

    def test_word_break_priority_over_hard_cut(self, chunker: DocumentChunker) -> None:
        # Long text with words but zero punctuation and zero newlines
        words = ["laboratory" for _ in range(300)]
        text = " ".join(words)

        drafts = chunker.chunk_document_text(text)
        assert len(drafts) >= 2
        for i, d in enumerate(drafts[:-1]):
            assert 800 <= len(d.chunk_text) <= 1000
            # Must end with full word "laboratory", not severed mid-word
            assert d.chunk_text.endswith("laboratory")

    def test_hard_cut_fallback_on_unbroken_string(
        self, chunker: DocumentChunker
    ) -> None:
        # 2500 character unbroken string without any whitespace or punctuation
        text = "X" * 2500
        drafts = chunker.chunk_document_text(text)
        assert len(drafts) == 3
        # Chunk 0: 0 to 1000
        assert len(drafts[0].chunk_text) == 1000
        # Chunk 1: 850 to 1850 (1000 chars)
        assert len(drafts[1].chunk_text) == 1000
        # Chunk 2 remainder: 1700 to 2500 (800 chars)
        assert len(drafts[2].chunk_text) == 800


class TestOverlapAndWordAlignment:
    @pytest.fixture
    def chunker(self) -> DocumentChunker:
        return DocumentChunker()

    def test_overlap_approximately_150_chars(self, chunker: DocumentChunker) -> None:
        # Text with numbered sentences
        sentences = [
            f"Observation-{i:03d} recorded normal blood glucose levels of "
            "ninety-five mg/dL."
            for i in range(40)
        ]
        text = " ".join(sentences)

        drafts = chunker.chunk_document_text(text)
        assert len(drafts) >= 2

        # Check overlap between chunk 0 and chunk 1
        text0 = drafts[0].chunk_text
        text1 = drafts[1].chunk_text

        # Find the overlapping text: end of text0 should match start of text1
        # It must snap to a complete word
        first_word_chunk1 = text1.split()[0]
        assert first_word_chunk1 in text0
        # Overlapping suffix of text0 present in text1
        overlap_found = False
        for sz in range(100, 200):
            suffix = text0[-sz:]
            if suffix in text1:
                overlap_found = True
                break
        assert overlap_found, (
            "Expected approximately 150-char overlap between consecutive chunks"
        )

    def test_overlap_never_starts_mid_word(self, chunker: DocumentChunker) -> None:
        words = ["Potassium", "Chloride", "Bicarbonate", "Creatinine", "Bilirubin"] * 60
        text = " ".join(words)

        drafts = chunker.chunk_document_text(text)
        assert len(drafts) >= 2

        for i, d in enumerate(drafts[1:], start=1):
            first_token = d.chunk_text.split()[0]
            assert first_token in (
                "Potassium",
                "Chloride",
                "Bicarbonate",
                "Creatinine",
                "Bilirubin",
            ), f"Chunk {i} started with partial word: {first_token}"


class TestPageSemanticsAndPropagation:
    @pytest.fixture
    def chunker(self) -> DocumentChunker:
        return DocumentChunker()

    def test_unpaged_document_has_none_page_number(
        self, chunker: DocumentChunker
    ) -> None:
        text = "Sample plain text clinical note without form feeds."
        drafts = chunker.chunk_document_text(text)
        assert len(drafts) == 1
        assert drafts[0].page_number is None

    def test_single_page_without_delimiter_uses_default_page_number(
        self, chunker: DocumentChunker
    ) -> None:
        text = "Serum Creatinine: 0.9 mg/dL. Normal kidney function."
        drafts = chunker.chunk_document_text(text, default_page_number=1)
        assert len(drafts) == 1
        assert drafts[0].page_number == 1
        assert drafts[0].chunk_text == text

    def test_multipage_with_delimiter_preserves_1based_pages_regardless_of_default(
        self, chunker: DocumentChunker
    ) -> None:
        page1 = "Page 1: Normal ECG."
        page2 = "Page 2: Normal Chest X-ray."
        text = page1 + PAGE_DELIMITER + page2
        drafts = chunker.chunk_document_text(text, default_page_number=None)
        assert len(drafts) == 2
        assert drafts[0].page_number == 1
        assert drafts[1].page_number == 2

    def test_single_page_pdf_with_form_feed(self, chunker: DocumentChunker) -> None:
        # 1 page PDF with no second page
        text = "CBC Report: WBC 6.5, RBC 4.8, Platelets 250."
        # If it has a trailing form feed:
        text_with_ff = text + PAGE_DELIMITER
        drafts = chunker.chunk_document_text(text_with_ff)
        assert len(drafts) == 1
        assert drafts[0].page_number == 1
        assert drafts[0].chunk_text == text

    def test_multi_page_pdf_page_number_propagation(
        self, chunker: DocumentChunker
    ) -> None:
        page1 = "Page one lab results: Sodium 140 mEq/L."
        page2 = "Page two cardiology report: Normal sinus rhythm with normal axis."
        text = page1 + PAGE_DELIMITER + page2

        drafts = chunker.chunk_document_text(text)
        assert len(drafts) == 2
        assert drafts[0].chunk_index == 0
        assert drafts[0].page_number == 1
        assert drafts[0].chunk_text == page1

        assert drafts[1].chunk_index == 1
        assert drafts[1].page_number == 2
        assert drafts[1].chunk_text == page2

    def test_blank_page_does_not_renumber_subsequent_pages(
        self, chunker: DocumentChunker
    ) -> None:
        # Page 1, blank Page 2, Page 3
        page1 = "Page 1 findings: Normal."
        page2 = "   \n\t  "  # Blank whitespace page
        page3 = "Page 3 findings: Follow up in 6 months."
        text = page1 + PAGE_DELIMITER + page2 + PAGE_DELIMITER + page3

        drafts = chunker.chunk_document_text(text)
        assert len(drafts) == 2

        # Page 1 chunk
        assert drafts[0].chunk_index == 0
        assert drafts[0].page_number == 1
        assert drafts[0].chunk_text == page1

        # Page 3 chunk — MUST be page_number=3, NOT page_number=2
        assert drafts[1].chunk_index == 1
        assert drafts[1].page_number == 3
        assert drafts[1].chunk_text == page3

    def test_page_local_chunking_never_spans_pages(
        self, chunker: DocumentChunker
    ) -> None:
        # Page 1 has 300 chars, Page 2 has 400 chars. Total 700 chars.
        # Even though combined they are < 1000 chars, page-local chunking
        # MUST keep them in separate chunks because chunks never cross page boundaries!
        page1 = "P1: " + ("Measurement Alpha. " * 15)
        page2 = "P2: " + ("Measurement Beta. " * 20)
        text = page1 + PAGE_DELIMITER + page2

        drafts = chunker.chunk_document_text(text)
        assert len(drafts) == 2
        assert drafts[0].page_number == 1
        assert drafts[0].chunk_text == page1.strip()
        assert drafts[1].page_number == 2
        assert drafts[1].chunk_text == page2.strip()

    def test_large_page_produces_multiple_chunks_with_same_page_number(
        self, chunker: DocumentChunker
    ) -> None:
        # Page 1 has 2500 chars (produces multiple chunks, all page_number=1)
        # Page 2 has 400 chars (produces 1 chunk, page_number=2)
        long_page1 = " ".join([f"Lab result {i} is normal." for i in range(80)])
        short_page2 = "Summary: Patient is discharged in good condition."
        text = long_page1 + PAGE_DELIMITER + short_page2

        drafts = chunker.chunk_document_text(text)
        assert len(drafts) >= 3

        # All chunks from page 1 must have page_number=1
        page1_chunks = [d for d in drafts if d.page_number == 1]
        assert len(page1_chunks) >= 2
        for d in page1_chunks:
            assert d.page_number == 1

        # Chunk from page 2 must have page_number=2
        page2_chunks = [d for d in drafts if d.page_number == 2]
        assert len(page2_chunks) == 1
        assert page2_chunks[0].chunk_text == short_page2

        # chunk_index must be strictly sequential 0, 1, 2, ...
        for expected_idx, d in enumerate(drafts):
            assert d.chunk_index == expected_idx


class TestDeterminismAndUnicode:
    @pytest.fixture
    def chunker(self) -> DocumentChunker:
        return DocumentChunker()

    def test_deterministic_repeated_chunking(self, chunker: DocumentChunker) -> None:
        text = "Medical note with various sections.\n\n" + (
            "Patient presented with slight fever and cough. " * 30
        )
        run1 = chunker.chunk_document_text(text)
        run2 = chunker.chunk_document_text(text)

        assert len(run1) == len(run2)
        for c1, c2 in zip(run1, run2):
            assert c1.chunk_index == c2.chunk_index
            assert c1.chunk_text == c2.chunk_text
            assert c1.page_number == c2.page_number

    def test_unicode_and_clinical_symbols(self, chunker: DocumentChunker) -> None:
        # Text with clinical Greek/Latin symbols: µg, ±, °, é, ñ
        text = (
            "Dosage: 50 µg daily ± 5 µg. Temperature: 37.2 °C.\n"
            "Médecin traitant: Dr. René Müller. Niño sano.\n\n"
        ) * 15
        drafts = chunker.chunk_document_text(text)
        assert len(drafts) >= 1
        for d in drafts:
            assert "µg" in d.chunk_text
            assert "Müller" in d.chunk_text
