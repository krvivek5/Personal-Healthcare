# Phase 2 — Milestone 3 — Slice 7: Implementation Plan

**Primary Authority**: [`phases/P2-M3-architecture-lock.md`](file:///d:/Personal%20Projects/Personal%20HealthCare/phases/P2-M3-architecture-lock.md)  
**Slice Name**: *Frontend Provenance Presentation, Integration & Full Regression Suite*  
**Status**: APPROVED PLAN (Awaiting implementation authorization)  
**Verified Baseline**: 468 passed, 4 skipped live tests on backend `pytest`; 10 passed tests on `HealthInquiryView.test.tsx`; 0 Ruff errors; 0 ESLint errors; clean git working tree on `master`.

---

## 1. Context & Purpose

Milestone 3 Slices 1–6 established the foundation:
- S1–S3: Document upload, storage, and text extraction lifecycle (`DocumentExtraction`).
- S4: Deterministic query understanding (`query_understanding.py`) and document evidence evaluation (`evidence_evaluator.py`).
- S5: Deterministic document selection (`document_selection.py`) and context serialization with `[DOC-N]` tokens (`sanitized_context.py`).
- S6: LLM Gateway synthesis, non-diagnostic prompt boundary, citation reconciliation to canonical `MedicalDocument.id`, and `MockLLMProvider` document synthesis parity.

Slice 7 completes Milestone 3 by connecting the end-to-end inquiry loop:
1. Orchestrating document selection and evaluation within `submit_health_inquiry` for document domains.
2. Implementing the deterministic Top-K=2 candidate evidence policy.
3. Exposing a lightweight inline expandable provenance card in `HealthInquiryView.tsx` with a direct document download trigger.
4. Validating the full system through backend API integration tests, evaluation harness invariant tests, frontend component/interaction tests, full regression suites, and manual live-browser verification.

---

## 2. Execution Decisions & Architecture Alignment

### A. Backend Document Orchestration
* **Routing**: In `submit_health_inquiry` ([`backend/app/api/health_inquiry.py`](file:///d:/Personal%20Projects/Personal%20HealthCare/backend/app/api/health_inquiry.py)), when `target.target_domain` matches the locked document domains (`"labs"`, `"reports"`, `"clinical_documents"`, `"prescriptions"`):
  * Call `selected_docs = await select_document_evidence(db, patient.id, target)`.
* **Context Population**: Convert selected `MedicalDocument` instances into `DocumentEvidenceContext` items and assign to `context.documents`:
  ```python
  context.documents = [
      DocumentEvidenceContext(
          document_id=doc.id,
          display_name=doc.display_name,
          document_type=doc.document_type,
          document_date=doc.document_date,
          extracted_excerpt=(
              doc.document_extraction.extracted_text
              if doc.document_extraction and doc.document_extraction.extracted_text
              else ""
          ),
      )
      for doc in selected_docs
  ]
  ```
* **Identity Preservation**: `MedicalDocument.id` remains the authoritative identity. Documents are never merged or concatenated into a composite evidence container; document identities and tokens (`[DOC-1]`, `[DOC-2]`) remain separate and source-specific.
* **Structured Query Behavioral Preservation**: If `target.target_domain` is structured (`medications`, `conditions`, `allergies`, `symptoms`, `goals`, `profile`) or unclassified (`None`):
  * `select_document_evidence` is bypassed.
  * `context.documents` remains `[]`.
  * Structured inquiries continue to be evaluated through the existing structured evidence evaluator (`evaluate_evidence`), preserving identical behavioral semantics without introducing document retrieval into those paths.
  * Existing structured inquiry behavior is fully preserved behaviorally.

### B. Top-K=2 Deterministic Candidate Policy
`select_document_evidence` returns up to $K=2$ candidate documents ordered by recency (`document_date DESC NULLS LAST`, `uploaded_at DESC`). The route evaluates candidates using the approved deterministic precedence policy:

1. **Candidate Evaluation**:
   * Candidate 0 (newest) is evaluated first via `evaluate_document_evidence`:
     ```python
     ev0 = evaluate_document_evidence(target, to_evidence(selected_docs[0]), patient.id)
     ```
   * If `ev0.status == EvidenceStatus.SUFFICIENT`, candidate 0 is selected immediately.
   * Otherwise, if a second candidate exists, candidate 1 (older) is evaluated:
     ```python
     ev1 = evaluate_document_evidence(target, to_evidence(selected_docs[1]), patient.id)
     ```
2. **Deterministic Resolution Rules**:
   The resolution precedence across candidate 0 (newest) and candidate 1 (older) is:
   * **both SUFFICIENT**: Prefer newest (`ev0`).
   * **one SUFFICIENT**: Select the `SUFFICIENT` candidate (if `ev0` is `SUFFICIENT`, use `ev0`; if `ev1` is `SUFFICIENT`, use `ev1`).
   * **both PARTIALLY_SUFFICIENT**: Prefer newest (`ev0`).
   * **one PARTIALLY_SUFFICIENT**: Select the `PARTIALLY_SUFFICIENT` candidate (if only `ev0` is partial, use `ev0`; if only `ev1` is partial, use `ev1`).
   * **both INSUFFICIENT**: Prefer newest (`ev0`), preserving the newest examined candidate's existing absence semantics.
3. **No Concatenation**: Candidate documents are evaluated as distinct individual `DocumentExtractionEvidence` objects; they are never combined into a single text body.

### C. Zero-Candidate Safety
When `select_document_evidence` returns 0 matching completed candidates:
* The route returns `EvidenceStatus.INSUFFICIENT`.
* Directive wording:
  ```python
  EvidenceResult(
      status=EvidenceStatus.INSUFFICIENT,
      evidence_directive="No completed matching document evidence was available to answer this inquiry.",
  )
  ```
* The system does **not** claim that all uploaded documents were searched and lacked the fact; it accurately states that no completed matching document evidence was available.
* When a selected document was examined, the existing `evaluate_document_evidence` absence semantics (`_absent_directive`) are reused without alteration.

### D. Citation & Provenance Integrity
* **Authoritative Canonical ID**: All emitted citations for documents point to `record_id = MedicalDocument.id` with `entity_type = "DOCUMENT"`.
* **Server-Side Citation Gate**: The server maps `context.documents` in `_build_record_map(context)` and verifies that every cited ID returned by the LLM exists in the patient's authenticated records. Unmapped or foreign tokens fail closed and are discarded.
* **Tenant Isolation**: Strictly enforced at both the SQL selection query (`MedicalDocument.patient_id == patient.id`) and inside `evaluate_document_evidence` (`evidence.patient_id == requesting_patient_id`).
* **Locked Schema**: Reuses the locked `InquiryCitation` and `HealthInquiryResponse` schemas without adding new schema fields.

### E. Frontend Provenance Presentation (`HealthInquiryView.tsx`)
* **Lightweight Inline Provenance Card**: Replaces the generic `<li>` rendering for `citation.entity_type === "DOCUMENT"` with an inline expandable card.
* **No Modals / Drawers / Portals**: Avoids introducing modal dialogs, global drawer managers, or portal trees. The card renders directly in the inquiry Sources section.
* **Card Information**:
  * Reference badge: `[{citation.citation_id}]`
  * Document Type badge (e.g. `DOCUMENT`)
  * Document display name and date (from `citation.label`)
  * Verification state badge (`SOURCE RECORDED`)
  * "Download Document" button calling `documentsApi.download(session.access_token, citation.record_id)` with blob URL download trigger.
  * "Inspect Details" button toggling inline expansion.
* **Inline Expanded Details**:
  * Shows Canonical Record ID, Entity Type, and full label.
* **Preservation of Structured Citations**: Non-document citations (`CONDITION`, `MEDICATION`, `ALLERGY`, etc.) continue to render using the existing list-item presentation.

---

## 3. Files to Modify & Responsibilities

| # | File Path | Scope of Changes |
| :--- | :--- | :--- |
| 1 | [`backend/app/api/health_inquiry.py`](file:///d:/Personal%20Projects/Personal%20HealthCare/backend/app/api/health_inquiry.py) | **[MODIFY]**: In `submit_health_inquiry`, branch on document domains (`labs`, `reports`, `clinical_documents`, `prescriptions`); call `select_document_evidence`; populate `context.documents`; implement the Top-K=2 deterministic candidate policy with explicit tie-breaking; implement zero-candidate safe absence; preserve structured inquiries behaviorally. |
| 2 | [`frontend/src/components/HealthInquiryView.tsx`](file:///d:/Personal%20Projects/Personal%20HealthCare/frontend/src/components/HealthInquiryView.tsx) | **[MODIFY]**: Add inline expandable document citation card for `entity_type === "DOCUMENT"`; display reference token, type badge, display name, date, verification state, download button via `documentsApi.download`, and inline details toggle; manage download loading/error state; preserve structured citation rendering. |
| 3 | [`backend/tests/test_health_inquiry_api.py`](file:///d:/Personal%20Projects/Personal%20HealthCare/backend/tests/test_health_inquiry_api.py) | **[MODIFY]**: Add API integration tests for document inquiries: sufficient evidence, absent analyte, zero candidates, Top-K=2 candidate precedence and tie-breaking, tenant isolation, and emergency safety pre-flight precedence. |
| 4 | [`backend/tests/eval/test_m2_evaluation.py`](file:///d:/Personal%20Projects/Personal%20HealthCare/backend/tests/eval/test_m2_evaluation.py) | **[MODIFY]**: Expand offline comparative evaluation harness to evaluate core invariants on document-grounded inquiries (evidence adherence, absence honesty, citation integrity, safety precedence). |
| 5 | [`frontend/src/components/HealthInquiryView.test.tsx`](file:///d:/Personal%20Projects/Personal%20HealthCare/frontend/src/components/HealthInquiryView.test.tsx) | **[MODIFY]**: Add component interaction tests for document citation cards, inline details expand/collapse, download triggers via `documentsApi.download`, download loading/error states, and structured citation preservation. |

---

## 4. Test & Verification Plan

### A. Backend API Integration Tests (`test_health_inquiry_api.py`)
1. **Document-Domain Routing & Sufficient Evidence**:
   - Patient uploads completed lab report with creatinine.
   - Query: *"What was my creatinine on my lab report?"*
   - Expected: HTTP 200, `evidence_status == SUFFICIENT`, answer cites document, citation contains `entity_type == "DOCUMENT"` and `record_id == doc.id`.
2. **Analyte Absent in Document (Absence Honesty)**:
   - Patient has lab report without cholesterol.
   - Query: *"What was my cholesterol on my lab report?"*
   - Expected: HTTP 200, `evidence_status == INSUFFICIENT`, answer explicitly states document does not contain cholesterol, 0 citations.
3. **Zero Matching Candidates**:
   - Patient has no uploaded documents (or only unsupported/failed extractions).
   - Query: *"What did my blood test say?"*
   - Expected: HTTP 200, `evidence_status == INSUFFICIENT`, directive states: *"No completed matching document evidence was available to answer this inquiry."*, 0 citations.
4. **Top-K=2 Deterministic Candidate Resolution**:
   - *both SUFFICIENT*: Doc 1 (newer) and Doc 2 (older) both contain analyte $\rightarrow$ resolves to `SUFFICIENT` using newest Doc 1.
   - *one SUFFICIENT*: Doc 1 missing analyte, Doc 2 containing analyte $\rightarrow$ evaluates Doc 1 then Doc 2 $\rightarrow$ resolves to `SUFFICIENT` using Doc 2.
   - *both PARTIALLY_SUFFICIENT*: Both Doc 1 and Doc 2 have partial attributes $\rightarrow$ resolves to `PARTIALLY_SUFFICIENT` using newest Doc 1.
   - *one PARTIALLY_SUFFICIENT*: Doc 1 has partial attribute, Doc 2 has zero $\rightarrow$ resolves to `PARTIALLY_SUFFICIENT` using Doc 1; Doc 1 has zero, Doc 2 has partial $\rightarrow$ resolves to `PARTIALLY_SUFFICIENT` using Doc 2.
   - *both INSUFFICIENT*: Neither document contains the queried analyte $\rightarrow$ resolves to `INSUFFICIENT` using newest Doc 1's absence directive.
5. **Strict Tenant Isolation**:
   - Patient A uploads lab report; Patient B queries lab report.
   - Expected: Patient B receives `INSUFFICIENT` ("No completed matching document evidence was available..."), 0 citations; Patient A's document is never read or cited.
6. **Deterministic Safety Pre-flight Precedence**:
   - Patient has uploaded lab report.
   - Query describes acute emergency symptoms (*"I have crushing chest pain right now, what does my lab report say?"*).
   - Expected: HTTP 200, `safety.triggered == True`, answer is `SAFETY_ADVISORY`, 0 LLM calls and 0 citations; synthesis is not invoked.
7. **Structured Inquiry Behavioral Regression**:
   - Verify all 10 existing structured inquiry tests continue to pass with identical assertions.

### B. Offline Invariant Evaluation Tests (`test_m2_evaluation.py`)
1. **Document Grounding**: Grounded document context synthesizes answer citing `[DOC-1]`.
2. **Absence Honesty**: Missing analyte directive synthesized without diagnostic hallucination.
3. **Citation Integrity**: Reconciled citations map 100% to verified canonical document UUIDs.
4. **Safety Precedence**: Acute emergency queries bypass synthesis even when document context is attached.

### C. Frontend Component & Interaction Tests (`HealthInquiryView.test.tsx`)
1. **Document Citation Card Presentation**: Renders reference badge, type badge, display name, date, and verification state.
2. **Inline Details Toggle**: Clicking "Inspect Details" expands details; clicking again collapses details.
3. **Document Download Trigger**: Clicking "Download Document" calls `documentsApi.download(token, citation.record_id)` and creates a blob download.
4. **Download Loading & Error State**: Download button indicates loading state during fetch; displays error message if download fails.
5. **Structured Citations Intact**: Verifies that condition and medication citations continue rendering in their existing format.

### D. Regression Suite Execution
1. Backend test suite: `pytest` (all existing 468+ tests pass, 0 regressions).
2. Backend linting and formatting: `ruff check app tests` (0 errors).
3. Frontend test suite: `npm test` / Vitest (all component tests pass).
4. Frontend linting: `npm run lint` / ESLint (0 errors).

### E. Manual Live-Browser Verification
1. Launch backend (`uvicorn app.main:app`) and frontend (`npm run dev`).
2. Log in with test account.
3. Upload a lab report text/PDF.
4. Submit natural language query referencing the document.
5. Verify visual presentation:
   - Answer rendered with inline `[1]` citation.
   - Evidence status badge neutral and clear.
   - Document citation card rendered with display name, date, and badges.
   - Click "Inspect Details" to view inline metadata.
   - Click "Download Document" and verify browser file download initiates.
6. Submit an emergency symptom query with document present $\rightarrow$ verify prominent safety advisory banner.

---

## 5. Acceptance Criteria

* [ ] **AC-1 (Document-Domain Routing)**: Inquiries matching `"labs"`, `"reports"`, `"clinical_documents"`, and `"prescriptions"` invoke `select_document_evidence` and populate `context.documents`.
* [ ] **AC-2 (Zero-Candidate Safety)**: When no completed matching document candidate is selected, return `INSUFFICIENT` with directive *"No completed matching document evidence was available to answer this inquiry."* without claiming all documents were searched.
* [ ] **AC-3 (Top-K=2 Candidate Policy & Tie-Breaking)**:
  - both SUFFICIENT $\rightarrow$ newest.
  - one SUFFICIENT $\rightarrow$ SUFFICIENT.
  - both PARTIALLY_SUFFICIENT $\rightarrow$ newest.
  - one PARTIALLY_SUFFICIENT $\rightarrow$ PARTIALLY_SUFFICIENT.
  - both INSUFFICIENT $\rightarrow$ newest.
* [ ] **AC-4 (No Composite Evidence)**: Multiple documents are never concatenated into a single evidence container; citations remain distinct and source-specific.
* [ ] **AC-5 (Canonical Citation Identity)**: All document citations emit `entity_type: "DOCUMENT"` with `record_id == MedicalDocument.id`.
* [ ] **AC-6 (Strict Tenant Isolation)**: Inquiries never select, evaluate, cite, or leak documents belonging to a different patient.
* [ ] **AC-7 (Deterministic Safety Precedence)**: Acute emergency queries return `SAFETY_ADVISORY` with 0 LLM calls and 0 citations; synthesis is not invoked, even when matching documents exist.
* [ ] **AC-8 (Structured Inquiry Behavioral Regression)**: Structured inquiries (`conditions`, `medications`, etc.) behave identically to M2 baseline with zero behavioral regression.
* [ ] **AC-9 (Frontend Inline Provenance Card)**: Document citations render an inline expandable card with reference badge, display name, date, type badge, verification state, and download action.
* [ ] **AC-10 (Download Flow)**: Clicking the download action triggers `documentsApi.download(...)` and downloads the source file.
* [ ] **AC-11 (Frontend Error / Loading States)**: Loading and error states are handled gracefully during inquiry submission and document download.
* [ ] **AC-12 (Full Regression)**: 100% pass rate on backend `pytest`, frontend `vitest`, `ruff check`, and `eslint`.
* [ ] **AC-13 (Manual Live-Browser Verification)**: Manual end-to-end flow verified in live browser without UI regressions.

---

## 6. Strict Non-Goals (Scope Protections)

The following remain strictly excluded from Slice 7:
* **NO Vector Databases or `pgvector`**: Retrieval remains purely deterministic metadata/intent/recency based.
* **NO Text Embeddings**: Zero embedding model calls.
* **NO Optical Character Recognition (OCR)**: Scanned image documents remain `UNSUPPORTED`.
* **NO Multi-Turn Conversational Memory**: Pure single-turn stateless request/response.
* **NO Background Workers / Celery / Redis**: In-process synchronous execution preserved.
* **NO Clinical Decision Support (CDS)**: Strictly non-diagnostic factual reporting of documented records and reference intervals; no diagnoses, treatments, or triage scores.
* **NO Citation Schema Changes**: Preserves existing `InquiryCitation` fields.
* **NO Client-Side Citation Authority**: Server owns canonical citation validation.
* **NO Modal Framework or Global Drawer Manager**: Uses lightweight inline cards only.
* **NO Unrelated Refactoring**: Preserves existing M1/M2/M3 modules outside the scoped files.

---

## 7. Open Decisions / Blockers

* **None**: All architectural decisions (Top-K=2 candidate policy, tie-breaking rules, zero-candidate wording, inline card UX, and testing strategy) are fully resolved and locked.
