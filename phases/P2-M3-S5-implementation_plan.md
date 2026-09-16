# Phase 2 — Milestone 3 — Slice 5: Deterministic Document Selection & Context Tokenizer

Extend the inquiry context pipeline to deterministically select, budget, and serialize patient-owned, completed document evidence into the LLM context using `[DOC-N]` tokens.

## User Review Required

Please review the final clarifications and boundary logic below to ensure it perfectly aligns with the M3 architecture intent before implementation begins.

## Proposed Changes

---

### 1. Deterministic Selection

#### [NEW] `backend/app/health/document_selection.py`
Create the document-selection boundary:
- Implement `select_document_evidence(db: AsyncSession, patient_id: uuid.UUID, target: InquiryTarget)`
- **Tenant Isolation**: Strictly match `patient_id` to prevent cross-tenant access.
- **Extraction Gating**: Only consider `MedicalDocument`s with `DocumentExtraction.extraction_status == "COMPLETED"` and non-empty `extracted_text`.
- **Target Logic (Locked Mapping)**:
  - `target_domain="labs"` maps to `["lab_report"]`.
  - `target_domain="prescriptions"` maps to `["prescription"]`.
  - `target_domain="reports"` maps to `["diagnostic_report"]`.
  - `target_domain="clinical_documents"` maps to `["discharge_summary", "medical_record", "other"]`.
  - `target_domain=None` or `"profile"` does **NOT** select any documents.
- **Ordering**: Prioritise `document_date DESC NULLS LAST`, then tie-break with `uploaded_at DESC`.
- **Top-K**: Enforce a deterministic limit of 2 documents.

---

### 2. Lightweight Document Context & Budgeting

#### [MODIFY] `backend/app/health/inquiry_context.py`
- Define a lightweight non-ORM schema:
  ```python
  class DocumentEvidenceContext(BaseModel):
      document_id: uuid.UUID
      display_name: str
      document_type: str
      document_date: Optional[date]
      extracted_excerpt: str
  ```
- **Budgeting Strategy**: The architectural budget is defined as approximately 1,500 tokens per document. For M3, this will be implemented as a deterministic hard character cap:
  - `MAX_DOCUMENT_EXCERPT_CHARS = 6000`
  - This 6,000-character cap is a conservative approximation. No tokenizer dependency or token-counting service will be introduced.
- Add `documents: list[DocumentEvidenceContext] = Field(default_factory=list)` to `StructuredHealthContext`.

#### Orchestration
- `build_inquiry_context` remains responsible **only** for structured data.
- The existing health-inquiry orchestration layer (which calls `build_inquiry_context`) will be responsible for:
  1. Building structured context.
  2. Calling `select_document_evidence()`.
  3. Combining the resulting `DocumentEvidenceContext` objects with the structured context by appending them to `StructuredHealthContext.documents`.

---

### 3. Context Sanitization and Tokenization

#### [MODIFY] `backend/app/health/sanitized_context.py`
- Extend `build_sanitized_context` to process the new `documents` array.
- Introduce `[DOC-1]`, `[DOC-2]` deterministic tokenization for documents, completely distinct from `[REC-N]`.
- Ensure only safe fields (`display_name`, `document_type`, `document_date`, `extracted_excerpt`) are injected into the payload.
- Guarantee that `document_id`, `patient_id`, and `storage_key` are entirely stripped from the external payload.

#### [MODIFY] `reconcile_reference_tokens` (in `sanitized_context.py`)
- Explicitly update reconciliation logic to recognise both `[REC-N]` and `[DOC-N]` prefixes.
- **Exact Invariants**:
  - `[REC-N]` -> authoritative structured record UUID
  - `[DOC-N]` -> authoritative `MedicalDocument.id`
- The reference map remains server-private.
- Unknown, malformed, forged, foreign, or out-of-range tokens must be discarded.
- Do not change the external `InquiryCitation` contract yet; Slice 7 owns frontend presentation.

---

### 4. Testing

#### [NEW] `backend/tests/test_document_selection_slice5.py`
- Prove patient isolation (A cannot access B's document).
- Prove exclusion of `FAILED`/`UNSUPPORTED`/empty extractions.
- Prove locked mapping logic (e.g., `labs` targets `lab_report`, `None` yields no docs).
- Prove temporal sorting (`document_date DESC`, `uploaded_at DESC`).
- Prove Top-K limit of 2.

#### [NEW] `backend/tests/test_document_tokenization_slice5.py`
- Prove deterministic `[DOC-1]`... tokenization.
- Prove the 6000 character excerpt truncation works deterministically.
- Prove safe serialization (no DB IDs or storage keys).
- Prove `reconcile_reference_tokens` correctly handles both `[REC-N]` and `[DOC-N]`, ignoring unmapped/forged tokens, and strictly adhering to the invariants.

## Verification Plan

### Automated Tests
```bash
py -m pytest tests/test_document_selection_slice5.py tests/test_document_tokenization_slice5.py -q
py -m pytest tests/ -q
```
Verify that all existing tests (schema, extraction, context, query understanding, etc.) remain green without modifying their behaviors.

### Manual Verification
Review `ruff` results to ensure zero regressions in formatting or linting.
