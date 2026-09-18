"""Deterministic document chunking service for Milestone 4 Slice 2.

Adheres strictly to phases/P2-M4-architecture-lock.md §7 and phases/P2-M4-S2-plan.md:
- Target chunk size: 800–1000 characters
- Sliding overlap: 150 characters
- Natural boundary priority:
    paragraph (\\n\\n) -> line (\\n) -> sentence -> word -> hard cut at 1000 chars
- Page-local chunking: chunks never cross page boundaries
- Page-number propagation:
    - 1-based physical page number for paged PDF documents (\\x0c delimiter)
    - Blank pages emit zero chunks but do not renumber later pages
    - Unpaged / plain-text / legacy extractions: page_number = None
- Savepoint-isolated transactional persistence:
    - Uses `async with db.begin_nested():` so chunk replacement failures roll back
      only derived chunks without affecting outer canonical document transactions.
    - Stale chunks purged before inserting new chunks.
    - Zero unrestricted session.rollback() calls.
- Derived-data invariant:
    - MedicalDocument and DocumentExtraction remain canonical authorities.
    - DocumentChunk rows are strictly derived data.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DocumentChunk, DocumentExtraction, MedicalDocument

logger = logging.getLogger(__name__)

# Standard Form Feed control character used for PDF page demarcation
PAGE_DELIMITER: str = "\x0c"


@dataclass(frozen=True)
class ChunkDraft:
    """In-memory value object representing a chunk prior to DB persistence."""

    chunk_index: int
    chunk_text: str
    page_number: Optional[int] = None


class DocumentChunker:
    """Deterministic document chunking engine adhering to P2-M4 architecture lock §7.1.

    Splits text into bounded, ordered passages of approximately 800–1000 characters
    with 150-character sliding overlap, snapping strictly to natural boundaries
    within the [min_chunk_size, max_chunk_size] window:
      paragraph (\\n\\n) -> line (\\n) -> sentence -> word -> hard cut at 1000 chars.
    """

    def __init__(
        self,
        min_chunk_size: int = 800,
        max_chunk_size: int = 1000,
        overlap_size: int = 150,
    ) -> None:
        if min_chunk_size <= 0:
            raise ValueError("min_chunk_size must be positive")
        if max_chunk_size < min_chunk_size:
            raise ValueError("max_chunk_size must be >= min_chunk_size")
        if overlap_size < 0:
            raise ValueError("overlap_size must be >= 0")
        if overlap_size >= min_chunk_size:
            raise ValueError(
                "overlap_size must be < min_chunk_size to ensure forward progress"
            )

        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.overlap_size = overlap_size

    def chunk_document_text(
        self,
        text: str,
        default_page_number: Optional[int] = None,
    ) -> list[ChunkDraft]:
        """Split full document text into an ordered list of ChunkDraft objects.

        Normalization & Emptiness Pre-Check:
          - If text is null, empty, or whitespace-only after stripping: returns [].

        Page-Boundary Partitioning:
          - If PAGE_DELIMITER ('\\x0c') is present in text:
              Splits into pages: `pages = text.split(PAGE_DELIMITER)`.
              Iterates through pages using 1-based index (page_idx = 1, 2, ...).
              If a page is blank/whitespace-only: skipped without emitting chunks,
              preserving subsequent physical page numbers.
              Each non-empty page is chunked page-locally (no cross-page chunks).
          - If PAGE_DELIMITER is NOT present:
              Treated as a single continuous document with
              `page_number = default_page_number` (e.g. 1 for single-page PDFs
              without delimiters, None for plain text/legacy extractions).

        Sequential chunk_index:
          - chunk_index is strictly 0-indexed and continuous (0, 1, 2, ...).
        """
        if not text or not text.strip():
            return []

        if PAGE_DELIMITER in text:
            pages = text.split(PAGE_DELIMITER)
            drafts: list[ChunkDraft] = []
            current_chunk_idx = 0
            for page_idx, page_str in enumerate(pages, start=1):
                page_cleaned = page_str.strip()
                if not page_cleaned:
                    # Blank page: skip chunking, keep subsequent physical page numbers
                    continue
                page_drafts, current_chunk_idx = self._chunk_stream(
                    page_str,
                    page_number=page_idx,
                    start_chunk_index=current_chunk_idx,
                )
                drafts.extend(page_drafts)
            return drafts
        else:
            drafts, _ = self._chunk_stream(
                text,
                page_number=default_page_number,
                start_chunk_index=0,
            )
            return drafts

    def _chunk_stream(
        self,
        text: str,
        page_number: Optional[int],
        start_chunk_index: int,
    ) -> tuple[list[ChunkDraft], int]:
        """Chunk a continuous text stream (single page or unpaged document)."""
        cleaned = text.strip()
        if not cleaned:
            return [], start_chunk_index

        # Inherently short document or page content: produces exactly 1 chunk
        if len(cleaned) <= self.max_chunk_size:
            draft = ChunkDraft(
                chunk_index=start_chunk_index,
                chunk_text=cleaned,
                page_number=page_number,
            )
            return [draft], start_chunk_index + 1

        chunks: list[ChunkDraft] = []
        idx = start_chunk_index
        n = len(cleaned)
        start = 0

        while start < n:
            remaining_len = n - start
            if remaining_len <= self.max_chunk_size:
                remainder_text = cleaned[start:n].strip()
                if remainder_text:
                    chunks.append(
                        ChunkDraft(
                            chunk_index=idx,
                            chunk_text=remainder_text,
                            page_number=page_number,
                        )
                    )
                    idx += 1
                break

            target_end = start + self.max_chunk_size
            min_end = start + self.min_chunk_size
            sub = cleaned[min_end:target_end]

            # Priority 1: Paragraph break (\n\n)
            p_idx = sub.rfind("\n\n")
            if p_idx != -1:
                cut_end = min_end + p_idx + 2
            else:
                # Priority 2: Line break (\n)
                l_idx = sub.rfind("\n")
                if l_idx != -1:
                    cut_end = min_end + l_idx + 1
                else:
                    # Priority 3: Sentence break ((?<=[.!?])\s+)
                    sentence_matches = list(re.finditer(r"(?<=[.!?])\s+", sub))
                    if sentence_matches:
                        cut_end = min_end + sentence_matches[-1].start()
                    else:
                        # Priority 4: Word boundary (\s+)
                        word_matches = list(re.finditer(r"\s+", sub))
                        if word_matches:
                            cut_end = min_end + word_matches[-1].start()
                        else:
                            # Priority 5: Hard cut fallback at max_chunk_size (1000)
                            cut_end = target_end

            chunk_text = cleaned[start:cut_end].strip()
            if chunk_text:
                chunks.append(
                    ChunkDraft(
                        chunk_index=idx,
                        chunk_text=chunk_text,
                        page_number=page_number,
                    )
                )
                idx += 1

            # Compute next start position with sliding overlap
            next_start = cut_end - self.overlap_size
            if next_start > start and next_start < cut_end:
                if not cleaned[next_start - 1].isspace():
                    # Snap forward to next complete word
                    match = re.search(r"\s+\S", cleaned[next_start:cut_end])
                    if match:
                        snapped = next_start + match.end() - 1
                        if snapped < cut_end:
                            next_start = snapped

            # Strict forward progress invariant
            if next_start <= start or next_start >= cut_end:
                next_start = cut_end

            start = next_start

        return chunks, idx


async def delete_document_chunks(
    db: AsyncSession,
    document_id: uuid.UUID,
    patient_id: uuid.UUID,
) -> int:
    """Delete all DocumentChunk rows for *document_id* and *patient_id*.

    Returns number of deleted rows.
    """
    stmt = delete(DocumentChunk).where(
        DocumentChunk.document_id == document_id,
        DocumentChunk.patient_id == patient_id,
    )
    result = await db.execute(stmt)
    return result.rowcount or 0


async def chunk_and_persist_document(
    db: AsyncSession,
    document: MedicalDocument,
    extraction: DocumentExtraction,
    chunker: Optional[DocumentChunker] = None,
) -> list[DocumentChunk]:
    """Deterministically chunk and persist DocumentChunk rows for *document*.

    Transaction Isolation:
      Uses `async with db.begin_nested():` (SAVEPOINT) around:
        1. Purging stale chunks for this document
        2. Bulk-inserting newly generated chunks
        3. Flushing changes to DB
      If an error occurs during chunking or persistence, only the SAVEPOINT
      rolls back. The outer transaction and already-committed canonical
      MedicalDocument / DocumentExtraction records remain completely intact.

    Tenant Safety:
      `patient_id` is always derived strictly from `document.patient_id`.

    Status Gating:
      Only extractions with `extraction_status == 'COMPLETED'` and non-empty
      `extracted_text` produce chunks.
      If status is FAILED, UNSUPPORTED, or text is empty/whitespace-only,
      stale chunks are purged within the savepoint and an empty list is returned.
    """
    if chunker is None:
        chunker = DocumentChunker()

    is_valid_completed = (
        extraction.extraction_status == "COMPLETED"
        and extraction.extracted_text is not None
        and bool(extraction.extracted_text.strip())
    )

    if not is_valid_completed:
        async with db.begin_nested():
            await delete_document_chunks(db, document.id, document.patient_id)
            await db.flush()
        return []

    default_page_number = 1 if extraction.extraction_method == "pypdf" else None
    drafts = chunker.chunk_document_text(
        extraction.extracted_text,
        default_page_number=default_page_number,
    )
    if not drafts:
        async with db.begin_nested():
            await delete_document_chunks(db, document.id, document.patient_id)
            await db.flush()
        return []

    async with db.begin_nested():
        # 1. Purge stale chunks
        await delete_document_chunks(db, document.id, document.patient_id)

        # 2. Bulk insert newly generated chunks
        models = [
            DocumentChunk(
                document_id=document.id,
                patient_id=document.patient_id,
                chunk_index=d.chunk_index,
                page_number=d.page_number,
                chunk_text=d.chunk_text,
                embedding=None,
            )
            for d in drafts
        ]
        db.add_all(models)

        # 3. Flush to enforce DB constraints within this savepoint
        await db.flush()

    return models
