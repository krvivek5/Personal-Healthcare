# Phase 2 — Milestone 3: Medical Document Grounding & Content Understanding
## Architecture Lock Specification

> **Milestone Theme**: *Extend Personal Health Intelligence from structured records to unstructured clinical documents via deterministic text extraction, document evidence evaluation, and verified document citation.*  
> **Status**: APPROVED ARCHITECTURE SPECIFICATION (READ-ONLY ARCHITECTURE LOCK)  
> **Milestone 1 State**: COMPLETE & LOCKED (2026-09-14)  
> **Milestone 2 State**: COMPLETE & LOCKED (2026-09-15)  
> **Milestone 3 Target Scope**: Native Text PDF & Plain Text Extraction + Deterministic Document Selection + Document Evidence Evaluation + Document Reference Tokenization (`[DOC-N]`) + Canonical Artifact Citation Reconciliation  
> **Implementation Mandate**: Architectural lock only. No implementation code or migrations are modified in this step.

---

## 1. Purpose

The purpose of Milestone 3 is to enable **Medical Document Understanding & Content Grounding** within the Personal Health Intelligence system.

In Phase 1, users were provided a secure personal health workspace to upload and store clinical documents (e.g., blood work reports, discharge summaries, prescriptions, clinical notes) in S3/MinIO object storage. In Milestones 1 and 2 of Phase 2, the inquiry engine was strictly bounded to structured database entities (`conditions`, `medications`, `allergies`, `symptoms`, `patient_goals`, `timeline_events`). When a user submitted an inquiry regarding findings recorded inside an uploaded document (e.g., *"What did my metabolic panel show?"* or *"What are my wound care instructions from the hospital discharge?"*), the inquiry engine was blind to document contents and deterministically returned that records did not contain the information.

Milestone 3 bridges this gap by unlocking the actual textual content of uploaded documents. It introduces direct text extraction, deterministic document selection, document evidence evaluation, bounded context serialization, and citation reconciliation.

### Explicit Boundary
Milestone 3 delivers **document-grounded understanding and plain-language explanation**. It is:
* **NOT** Retrieval-Augmented Generation (RAG) with vector databases or semantic similarity search.
* **NOT** an autonomous diagnostic engine.
* **NOT** a treatment recommendation or prescription system.
* **NOT** a clinical triage or symptom severity scorer.
* **NOT** Clinical Decision Support (CDS).

---

## 2. Product Outcome

### The Patient Experience
When an authenticated patient asks a question regarding their uploaded medical documents:

1. **Grounded Document Understanding**:
   The system synthesizes a plain-language, compassionate explanation answering the inquiry directly from the text of their uploaded clinical documents, combined where relevant with their structured profile.
   > *Example Query*: *"What did my blood test on August 12 say about my kidney function?"*  
   > *System Response*: *"According to your Comprehensive Metabolic Panel from August 12, 2026 [1], your serum creatinine was recorded at 0.9 mg/dL (reference range: 0.6–1.2 mg/dL) and your Blood Urea Nitrogen (BUN) was 14 mg/dL (reference range: 7–20 mg/dL). Both documented values were within the laboratory's standard reference intervals. Please discuss these results with your prescribing doctor."*

2. **Verified Document Provenance**:
   The response emits an explicit document reference token (`[1]`) that reconciles to the canonical uploaded `MedicalDocument` in the patient's records. Clicking or inspecting the citation in the frontend provenance drawer presents the document display name, document date, document type (`LAB_REPORT`), and relevant extracted excerpt.

3. **Honest Absence Communication**:
   If an uploaded document does not contain the queried analyte, measurement, or clinical instruction, the system clearly and unambiguously states that the document does not record this information:
   > *System Response*: *"Your uploaded Comprehensive Metabolic Panel from August 12, 2026 [1] records metabolic and kidney markers, but it does not contain a Vitamin D or Thyroid Stimulating Hormone (TSH) measurement."*

4. **Zero Diagnostic Hallucination**:
   The system quotes and explains documented values, standard laboratory reference intervals, and explicit lab flags ("High", "Low", "Abnormal") without inferring systemic pathology, declaring clinical diagnoses, or suggesting treatment modifications.

---

## 3. Capability Boundary

### What M3 Adds Beyond M2

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                MILESTONE 2 (LOCKED)                                    │
│  - Input: User Question                                                                │
│  - Context: Structured Health Context ONLY (conditions, medications, allergies, etc.)  │
│  - Grounding: Database rows only; Documents are opaque metadata entries in S3          │
│  - Citations: [REC-N] reconciled to structured entity UUIDs                           │
│  - Safety: Deterministic pre-flight on acute symptoms                                  │
│  - Gateway: OpenAI Adapter with MockLLMProvider offline fallback                       │
└────────────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                           ▼ (M3 Extensions)
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                MILESTONE 3 (M3 LOCK)                                   │
│  - Input: User Question                                                                │
│  - Context: Structured Records + Extracted Document Text Excerpts                      │
│  - Grounding: Structured database rows + Canonical uploaded document content           │
│  - Selection: Deterministic Document Selection (query intent + metadata + recency)     │
│  - Extraction: Native text PDFs + plain text (in-process, swappable interface)         │
│  - Citations: [REC-N] + [DOC-N] reconciled to canonical MedicalDocument UUIDs          │
│  - Safety: Unchanged deterministic pre-flight (acute symptoms bypass all inference)   │
│  - Clinical Boundary: Quote/summarize/explain records; strict no-diagnosis boundary    │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### Detailed Capability Matrix

| Feature Dimension | Milestone 2 (Locked) | Milestone 3 (Document Grounding) | Future Milestones (M4+) |
| :--- | :--- | :--- | :--- |
| **Grounding Source** | Structured health records only | Structured health records + text-extracted clinical documents | Vector-indexed chunk passages across large archives |
| **Document Storage** | Raw binary in S3/MinIO; metadata in PostgreSQL | Raw binary in S3/MinIO; canonical metadata + derived extraction entity | Raw binary in S3; derived extraction; vector embedding index |
| **Supported Formats** | Catalog only (all formats stored, none extracted) | Native digital PDF (`application/pdf`) and plain text (`text/plain`) | Optical Character Recognition (OCR) for scanned images / handwritten notes |
| **Document Selection** | N/A (documents not read) | **Deterministic Document Selection** (query domain + document type + recency) | Semantic Vector Search (pgvector embeddings + hybrid search) |
| **Evidence Evaluator** | Evaluates presence of structured fields | Evaluates presence of structured fields + document text findings | Semantic passage relevance scoring |
| **Prompt Tokenization** | `[REC-1]`, `[REC-2]` | `[REC-N]` (structured) + `[DOC-N]` (document evidence) | `[DOC-N]`, `[PASSAGE-N]` with page coordinates |
| **Citation Target** | Structured record UUID | Canonical `MedicalDocument.id` owned by patient | Canonical `MedicalDocument.id` with chunk/page deep-linking |
| **Conversation State** | Single-turn inquiry | Single-turn inquiry | Multi-turn conversational memory & sessions (M5) |

---

## 4. Non-Negotiable Invariants

All architectural invariants established in Milestone 1 and Milestone 2 remain inviolable:

1. **The Backend Owns Evidence Truth; The LLM Owns Language Synthesis**:
   - The backend deterministically performs text extraction, inspects document content, evaluates evidence sufficiency (`SUFFICIENT`, `PARTIALLY_SUFFICIENT`, `INSUFFICIENT`), and validates citation ownership.
   - The LLM is strictly confined to plain-language explanation and synthesis within backend-defined evidence boundaries. It cannot invent findings, assume unrecorded tests were normal, or claim an uploaded document contains information absent from the backend extraction.

2. **Deterministic Safety Primacy**:
   - Pattern-based safety evaluation (`evaluate_safety`) in `backend/app/health/safety_guardrails.py` runs **before** document selection, context assembly, or LLM invocation.
   - Any query describing acute or life-threatening symptoms immediately short-circuits the gateway, returning the deterministic M1/M2 `SAFETY_ADVISORY` with **zero external LLM network calls** and zero tokens spent.
   - Document processing logic must never weaken, bypass, or replace this deterministic pre-flight interceptor.

3. **Strict Tenant Isolation**:
   - Every document query, text extraction, context retrieval, and citation lookup is scoped strictly to `patient_id == current_authenticated_patient.id`.
   - Cross-patient document leakage is impossible by construction at the SQL query boundary.

4. **Patient-Data Minimization & Reference Tokenization**:
   - Prompts sent to external LLMs never receive internal database UUIDs, S3 `storage_key` paths, patient IDs, user emails, or administrative hospital account numbers.
   - Documents are tokenized using ordinal reference markers (`[DOC-1]`, `[DOC-2]`). The server maintains a private in-memory reconciliation map to translate emitted tokens back to database UUIDs.
   - Data minimization is practiced defensibly, but the system **does NOT claim guaranteed de-identification** of free-text clinical narratives.

5. **Document Citation Integrity to Canonical Artifact**:
   - Every document citation emitted by the system must resolve to the authenticated patient's canonical uploaded `MedicalDocument` artifact, not merely to a derived extraction row or transient in-memory representation.

6. **Truthful Evidence Hierarchy & Provenance**:
   - The system preserves a strict server-side distinction between:
     - `PATIENT_REPORTED`: Self-reported entries created by the user.
     - `SOURCE_RECORDED`: Verifiable facts originating from uploaded clinical documents (`source_type = SOURCE_DOCUMENT`, `source_id = MedicalDocument.id`).
     - `AI_DERIVED`: Machine-synthesized explanations or summaries.
   - Document-derived facts must **never** be silently converted into patient-reported information or structured clinical records without explicit patient confirmation.

7. **Provider-Neutral Gateway & CI Offline Determinism**:
   - All model inference flows through `LLMGateway`.
   - The offline `MockLLMProvider` must implement deterministic document-synthesis rules, ensuring all test suites pass in offline CI/CD environments with 100% determinism.

---

## 5. Data & Evidence Model

### Separation of Concerns: Canonical Artifact vs. Derived Content

The architecture establishes a strict conceptual and physical separation between:
1. **Canonical Uploaded Document Artifact** (`MedicalDocument`):
   - Represents the authentic file provided by the user.
   - Stored immutably in S3/MinIO under private `storage_key`.
   - Preserves user metadata: original filename, user display name, document type, content type, file size, document date, and notes.
   - Governed by migration `0003` check constraints: `source_type = 'PATIENT_REPORTED'`, `verification_state = 'PATIENT_REPORTED'`.
2. **Derived Extracted Content** (`DocumentExtraction`):
   - Represents the machine-extracted text derived from the canonical artifact.
   - Computed, ephemeral/re-runnable, and versioned.
   - Has its own lifecycle status: `PENDING`, `COMPLETED`, `FAILED`, `UNSUPPORTED`.

### Evaluation of Representation: Option A vs. Option B

```text
OPTION A (Recommended): Separate Entity              OPTION B: Direct Column on MedicalDocument
┌───────────────────────────────┐                    ┌───────────────────────────────┐
│       medical_documents       │                    │       medical_documents       │
├───────────────────────────────┤                    ├───────────────────────────────┤
│ id (PK)                       │                    │ id (PK)                       │
│ patient_id (FK)               │                    │ patient_id (FK)               │
│ file_name, display_name       │                    │ file_name, display_name       │
│ storage_key (S3)              │                    │ storage_key (S3)              │
│ document_type, document_date  │                    │ document_type, document_date  │
└───────────────┬───────────────┘                    │ extracted_text (Text)         │
                │ 1                                  │ extraction_status (String)    │
                ▼ 1                                  │ extraction_method (String)    │
┌───────────────────────────────┐                    │ extraction_version (String)   │
│      document_extractions     │                    │ extracted_at (DateTime)       │
├───────────────────────────────┤                    └───────────────────────────────┘
│ id (PK)                       │
│ document_id (FK, UNIQUE)      │
│ patient_id (FK)               │
│ extracted_text (Text)         │
│ extraction_status (String)    │
│ extraction_method (String)    │
│ extraction_version (String)   │
│ extracted_at (DateTime)       │
│ error_message (Text, nullable)│
└───────────────────────────────┘
```

#### Detailed Trade-Off Analysis

* **Option B (Direct Columns on `medical_documents`)**:
  - *Pros*: Slightly fewer lines of initial SQLAlchemy mapping; avoids a single table join.
  - *Cons*:
    - **Bloats the core entity**: Medical reports can yield 50KB–500KB of plain text. Placing large text directly on `medical_documents` causes table row fragmentation and slows down routine workspace queries (`GET /documents`) unless columns are deferred.
    - **Violates provenance semantics**: Migration `0003` enforces check constraints locking `medical_documents.verification_state = 'PATIENT_REPORTED'`. Extracted text is machine-derived (`AI_DERIVED`), creating an ontological conflict on the same row.
    - **Constrains Milestone 4**: In M4, when chunking is introduced, having text on the parent row creates confusion over whether the column is deprecated, canonical, or redundant with chunks.

* **Option A (Lightweight Separate Entity: `document_extractions`) — RECOMMENDED**:
  - *Pros*:
    - **Clean Lifecycle Isolation**: Upload success is completely decoupled from extraction success. If extraction fails, the canonical document record remains clean, valid, and untouched.
    - **Fast Workspace Queries**: Standard catalog and document listing queries do not load megabytes of extracted text into application memory.
    - **Re-extraction & Upgrades**: If extraction libraries are updated or re-run with improved parsers, the extraction row can be updated or replaced without modifying the user's canonical document metadata.
    - **Natural Evolutionary Bridge to M4**: When M4 introduces `document_chunks`, the chunks naturally hang off the extraction or document entity without requiring column deprecation.
    - **Zero Premature Complexity**: It is a simple, single 1-to-1 table with exactly 9 fields. It does not introduce chunking, vector stores, or speculative abstraction.

**Architectural Lock**: **Option A (`document_extractions`) is locked as the M3 data representation.**

### Minimum Extraction Provenance Metadata

To guarantee trustworthy derived content without adding speculative metadata, `document_extractions` will store strictly the following fields:

```python
class DocumentExtraction(Base):
    """Derived text content extracted from a canonical MedicalDocument."""

    __tablename__ = "document_extractions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("medical_documents.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    extraction_status: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # COMPLETED | FAILED | UNSUPPORTED
    extraction_method: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # e.g., "pypdf", "plaintext"
    extraction_version: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # e.g., "1.0.0"
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
```

---

## 6. Extraction Architecture

### Supported Extraction Formats (M3 Scope)
* **Native Digital PDF (`application/pdf`)**: Documents containing an extractable digital text stream (e.g., electronic lab reports, generated discharge letters).
* **Plain Text (`text/plain`)**: Unstructured clinical notes, transcribed visit text, or exported text summaries.

### Explicitly Unsupported Formats
* **Scanned Image Documents (`image/png`, `image/jpeg`)**: Scanned photos or non-text PDFs without an embedded character stream.
* **Handwritten Clinical Notes**: Scanned handwritten prescriptions or doctor charts.
* *Handling of Unsupported Files*: When uploaded, the file is safely stored in S3 and its canonical metadata row is created in `medical_documents`. An extraction record is created with `extraction_status = 'UNSUPPORTED'`. The document remains fully accessible to the patient for manual download/viewing, but the inquiry engine treats it as unavailable for textual evidence.

### Interface Decoupling & In-Process Implementation

```text
┌────────────────────────────────────────────────────────┐
│            POST /api/v1/documents Request              │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│              DocumentExtractor Protocol                │
│    extract_text(content: bytes, content_type: str)     │
└───────────────────────────┬────────────────────────────┘
                            │
          ┌─────────────────┴─────────────────┐
          │ (In-Process M3 Implementation)    │ (Future Worker - Post-M3)
          ▼                                   ▼
┌──────────────────────────────┐    ┌───────────────────────────────┐
│     PyPDFExtractor           │    │ Asynchronous Queue Worker     │
│  - in-process text parser    │    │ (Celery / Redis / Background) │
│  - sanitizes whitespace/NUL  │    │ - swappable behind protocol   │
└──────────────────────────────┘    └───────────────────────────────┘
```

1. **Protocol Definition**:
   ```python
   class ExtractionResult(BaseModel):
       status: str  # COMPLETED | FAILED | UNSUPPORTED
       text: str = ""
       method: str
       version: str
       error_message: Optional[str] = None

   class DocumentExtractor(Protocol):
       async def extract_text(
           self, file_bytes: bytes, content_type: str
       ) -> ExtractionResult: ...
   ```
2. **In-Process M3 Execution**:
   - Initial implementation runs in-process using standard Python extraction tooling (`pypdf` for PDF, UTF-8 decoder for text).
   - Sanitization strips null bytes (`\x00`), normalizes line endings, and collapses excessive whitespace.
3. **Decoupling Guarantee**:
   - Calling code interacts strictly through `DocumentExtractor`.
   - A future migration to an asynchronous worker (e.g., Redis queue or Celery task) can be implemented without changing the external API contract of `/documents` or the schema of `document_extractions`.
4. **No Unverified Performance Claims**:
   - No assumptions of sub-100ms execution are baked into system timeouts. The in-process call is bounded by a safe defensive timeout (e.g., 5 seconds). If extraction exceeds the timeout or raises an unhandled error, it fails gracefully (`status = 'FAILED'`) without aborting the upload or failing the HTTP request.

---

## 7. Document-Selection Architecture

> [!IMPORTANT]  
> M3 uses **Deterministic Document Selection**, NOT Retrieval-Augmented Generation (RAG).  
> Scalable semantic retrieval (embeddings, chunking, pgvector) is deferred to Milestone 4.

### Selection Pipeline

```text
User Natural Language Query
           │
           ▼
┌────────────────────────────────────────────────────────┐
│               Query Understanding                      │
│   (backend/app/health/query_understanding.py)          │
│   - Detects domain intent (LABS, REPORTS, CLINICAL)    │
│   - Extracts target entity keywords                    │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│         Deterministic Document Selection Engine        │
│   1. Filter by patient_id (Tenant Isolation)           │
│   2. Filter extraction_status == 'COMPLETED'           │
│   3. Filter document_type matching query intent        │
│      (e.g., query for 'blood test' -> 'LAB_REPORT')    │
│   4. Order by document_date DESC, uploaded_at DESC     │
│   5. Limit to Top-K candidates (K = 1 to 2 documents)  │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│              Evidence Evaluator                        │
│   (backend/app/health/evidence_evaluator.py)           │
│   - Inspects candidate document extracted_text         │
│   - Checks analyte / concept keyword presence          │
│   - Emits: SUFFICIENT | PARTIALLY_SUFFICIENT |         │
│            INSUFFICIENT                                │
└────────────────────────────────────────────────────────┘
```

### Selection Rules
1. **Tenant Isolation**: Only documents where `patient_id == current_patient.id` are selectable.
2. **Status Gate**: Only documents with an associated `DocumentExtraction` where `extraction_status == 'COMPLETED'` and non-empty `extracted_text` are selectable.
3. **Intent-to-Type Mapping**:
   - Queries targeting lab tests, blood work, panels, metabolic markers $\rightarrow$ prioritizes `document_type == 'LAB_REPORT'`.
   - Queries targeting prescriptions, dosages, refills $\rightarrow$ prioritizes `document_type == 'PRESCRIPTION'`.
   - Queries targeting discharge, hospital stays, post-op instructions $\rightarrow$ prioritizes `document_type == 'DISCHARGE_SUMMARY'`.
   - General or unclassified document queries $\rightarrow$ selects across all document types.
4. **Recency Prioritization**:
   - Candidates are sorted by `document_date DESC NULLS LAST`, then by `uploaded_at DESC`.
5. **Bounded Candidate Window**:
   - The selection engine retrieves at most **$K = 1$ to $2$ documents** per inquiry to preserve strict token budget boundaries.

---

## 8. Context & Prompt Boundary

### External Data Minimization vs. Guaranteed De-Identification

> [!CAUTION]  
> The system enforces **data minimization**, NOT guaranteed de-identification.  
> It is technically impossible to guarantee complete de-identification of arbitrary, unstructured medical prose using rule-based sanitization. The architecture makes no false privacy guarantees.

#### What IS Guaranteed
* **System Identifiers Completely Removed**: Database primary keys (`id`, `user_id`, `patient_id`), S3 `storage_key` paths, and internal record identifiers are never transmitted in prompt payloads.
* **Document Minimization**: The model receives only the selected document excerpts necessary for the query, not the patient's entire document history.
* **Deterministic Identifier Stripping**: The context serializer applies regex filters to strip explicitly recognized administrative and institutional patterns before prompt serialization:
  - Medical Record Numbers (MRN / Account Numbers: e.g., `MRN: \d+`).
  - National Identifiers / Social Security Numbers.
  - Institutional billing codes and hospital finance headers.
  - Clinician registration / license numbers.
* **Protected Tenant Boundary**: The canonical document and extracted text remain safely stored inside the patient's private, access-controlled database and object storage boundary.

#### What is NOT Guaranteed
* Complete redaction of incidental personal names, geographical references, or narrative life details embedded naturally within physician consultation notes.
* Protection against third-party LLM data retention if non-enterprise API agreements are used (enterprise zero-data-retention terms remain mandatory per M2 §10).

### Context Representation & Reference Tokenization (`[DOC-N]`)

The in-memory context passed to the gateway is expanded to include document evidence alongside structured records:

```python
class DocumentEvidenceContext(BaseModel):
    document_id: uuid.UUID
    display_name: str
    document_type: str
    document_date: Optional[date] = None
    extracted_excerpt: str  # Minimized excerpt, capped to token budget
```

In `backend/app/health/sanitized_context.py`, document excerpts are formatted using ordinal reference tokens:
```text
=== DOCUMENT EVIDENCE ===
[DOC-1] Document: Comprehensive Metabolic Panel | Date: 2026-08-12 | Type: LAB_REPORT
Content:
SODIUM: 140 mEq/L (136-145)
POTASSIUM: 4.2 mEq/L (3.5-5.0)
CREATININE: 0.9 mg/dL (0.6-1.2)
BUN: 14 mg/dL (7-20)
GLUCOSE: 92 mg/dL (70-99)
```

The serializer maintains a private reference dictionary:
```python
reference_map: dict[str, uuid.UUID] = {
    "REC-1": uuid.UUID("..."),  # Structured condition
    "REC-2": uuid.UUID("..."),  # Structured medication
    "DOC-1": uuid.UUID("..."),  # Canonical MedicalDocument.id
}
```

### Token Budgeting
* **Document Excerpt Limit**: Extracted text per document is deterministically truncated to at most **1,000–1,500 tokens** (approx. 4,000–6,000 characters).
* **Total Context Allocation**: Document context (~1,000–1,500 tokens) + Structured context (~400–800 tokens) + System prompt (~400 tokens) = **Total prompt payload under 2,700 tokens**, guaranteeing fast inference and strict cost control.

---

## 9. Citation & Provenance Architecture

### Reference-Token Reconciliation Pipeline

```text
               LLM Synthesizes Structured Output
               {
                 "answer_text": "Your creatinine was 0.9 mg/dL [1]...",
                 "cited_references": ["DOC-1"]
               }
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 LLM Gateway / API Layer                     │
│  - Receives cited_references: ["DOC-1"]                     │
│  - Translates "DOC-1" -> canonical MedicalDocument.id       │
│    using private server reference_map                       │
│  - Unmapped or hallucinated tokens (e.g. "DOC-9") discarded │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│             Database Canonical Ownership Gate               │
│  - Verifies: MedicalDocument.id exists AND                  │
│              MedicalDocument.patient_id == patient.id       │
│  - Rejects foreign, forged, or unauthenticated UUIDs        │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│             InquiryCitation Response Assembly               │
│  {                                                          │
│    "citation_id": 1,                                        │
│    "entity_type": "DOCUMENT",                               │
│    "record_id": "<MedicalDocument.id>",                     │
│    "label": "Comprehensive Metabolic Panel (2026-08-12)",   │
│    "verification_state": "SOURCE_RECORDED"                  │
│  }                                                          │
└─────────────────────────────────────────────────────────────┘
```

### Evolutionary Pathway Toward Milestone 4

> [!IMPORTANT]  
> The M3 citation contract is deliberately designed so that Milestone 4 (and beyond) can evolve toward:  
> `document → chunk/evidence unit → retrieved passage → citation`  
> without breaking the M3 API contract.

* In M3: `record_id` represents the canonical `MedicalDocument.id`. `entity_type` is `"DOCUMENT"`.
* In M4: When passage-level chunking and vector retrieval are introduced, the citation schema can add optional, non-breaking fields:
  ```python
  class InquiryCitation(BaseModel):
      citation_id: int
      entity_type: str  # "DOCUMENT", "CONDITION", etc.
      record_id: uuid.UUID  # Always the canonical MedicalDocument.id
      label: str
      verification_state: VerificationState
      # Optional M4 evolutionary extensions (nullable in M3):
      chunk_id: Optional[uuid.UUID] = None
      page_number: Optional[int] = None
      passage_text: Optional[str] = None
  ```
  This guarantees that existing frontend citation rendering will continue to resolve to the parent document artifact while allowing rich deep-linking in future phases.

---

## 10. Safety & Clinical Boundary

### Explicit Clinical Boundary: Permitted vs. Prohibited Actions

To uphold the core principles of `SPEC.md §8` and `DESIGN.md §11`, Milestone 3 defines an explicit, non-negotiable clinical boundary:

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                PERMITTED BEHAVIORS                                     │
│  ✓ Quote verbatim or summarize what an uploaded clinical report explicitly records.   │
│  ✓ Explain complex clinical terminology, acronyms, and abbreviations in plain english. │
│  ✓ State recorded laboratory values alongside their documented reference intervals.    │
│  ✓ State that a report marks a specific value as "High", "Low", or "Abnormal".         │
│  ✓ Compare a documented value to the report's published normal reference range.        │
│  ✓ Direct the patient to discuss specific documented findings with their physician.    │
└────────────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                           ▼ STRICT SEPARATION
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                PROHIBITED BEHAVIORS                                    │
│  ✗ NO Diagnosis: Never declare a disease or clinical condition from an abnormal value. │
│  ✗ NO Treatment Advice: Never suggest starting, stopping, or altering medication doses.│
│  ✗ NO Clinical Triage: Never categorize urgency levels or perform triage evaluation.   │
│  ✗ NO Extrapolation: Never infer systemic pathology absent from the document text.     │
│  ✗ NO False Reassurance: Never declare a patient "healthy" based on a partial panel.   │
│  ✗ NO Negative Clinical Claims: State "report does not show", NOT "you do not have".   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### System Prompt Directives & Negative Constraints

The dynamic prompt constructed in the gateway enforces these boundaries via strict negative constraints:
1. *"You are a plain-language medical document explanation assistant. The backend owns evidence truth; you own language synthesis."*
2. *"When explaining lab reports or clinical documents, state the recorded numerical value and the documented reference range. Do not invent ranges."*
3. *"If a value is flagged as abnormal by the laboratory, you may report that the document marks it as abnormal. You MUST NOT diagnose what condition causes this abnormality."*
4. *"Never recommend medication adjustments, lifestyle interventions, or treatments based on lab findings. Always direct the user to review the findings with their doctor."*
5. *"If an analyte or test was not recorded in the document, explicitly state that the document does not contain this information. Do not speculate or extrapolate."*

### Deterministic Safety Guardrail Precedence
* Inquiries describing acute, life-threatening symptoms (e.g., chest pain, stroke symptoms, acute shortness of breath) continue to be intercepted by `evaluate_safety()` **before** document selection or inference.
* Acute emergencies immediately receive `SAFETY_ADVISORY` with **zero LLM network activity**, preserving the locked M1/M2 safety invariant.

---

## 11. Storage Decision

### Authoritative Decision: Option A (`document_extractions` Table)

The system locks **Option A** as the architectural standard:

```sql
CREATE TABLE document_extractions (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL UNIQUE REFERENCES medical_documents(id) ON DELETE CASCADE,
    patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    extracted_text TEXT NOT NULL,
    extraction_status VARCHAR(50) NOT NULL,
    extraction_method VARCHAR(50) NOT NULL,
    extraction_version VARCHAR(50) NOT NULL,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    error_message TEXT NULL
);

CREATE INDEX ix_document_extractions_document_id ON document_extractions(document_id);
CREATE INDEX ix_document_extractions_patient_id ON document_extractions(patient_id);
```

### Justification
1. **Separation of Raw vs. Derived Artifacts**: The file in S3 and its row in `medical_documents` represent the canonical source artifact. The extracted text is a derived, machine-generated product. Separating them prevents derived text failures from corrupting or invalidating the user's primary file catalog.
2. **Database Performance**: Prevents multi-hundred-kilobyte text payloads from polluting the `medical_documents` table pages, keeping standard workspace document listings and pagination fast without requiring SQLAlchemy deferred column loading.
3. **Database Check Constraint Integrity**: Respects migration `0003`, where `medical_documents.verification_state` is constrained to `'PATIENT_REPORTED'`. Derived machine text belongs in an entity that reflects its extracted nature.
4. **Clean M4 Evolution**: When M4 introduces chunking and vector embeddings, `DocumentChunk` can cleanly reference `document_extractions` without requiring a backwards-incompatible table migration.

---

## 12. Proposed Slice Structure

To ensure atomic, testable, and disciplined execution, Milestone 3 is structured into **7 sequential implementation slices**.

> **Boundary Rule**: Upload success $\neq$ extraction success $\neq$ document selection $\neq$ evidence evaluation $\neq$ context serialization $\neq$ LLM synthesis $\neq$ citation reconciliation $\neq$ frontend provenance.

```text
Slice 1: Derived Content Schema & Migration (document_extractions)
   │
   ▼
Slice 2: Pluggable Document Extractor & In-Process PDF/Text Engine
   │
   ▼
Slice 3: Document Upload Integration & Lifecycle Management
   │
   ▼
Slice 4: Document Query Understanding & Evidence Evaluator
   │
   ▼
Slice 5: Deterministic Document Selection & Context Tokenizer ([DOC-N])
   │
   ▼
Slice 6: LLM Gateway Synthesis, Citation Reconciliation & Mock Provider
   │
   ▼
Slice 7: Frontend Provenance Drawer, E2E Integration & Full Regression Suite
```

### Slice Details

* **Slice 1: Derived Content Schema & Migration (`document_extractions`)**
  - Create Alembic migration `0004_add_document_extractions.py`.
  - Implement SQLAlchemy model `DocumentExtraction` in `backend/app/db/models.py`.
  - Add `DocumentExtraction` relationship to `MedicalDocument` (`uselist=False, cascade="all, delete-orphan"`).
  - Implement Pydantic schema `DocumentExtractionResponse` in `backend/app/schemas/document.py`.
  - *Verification*: Migration up/down tests in PostgreSQL; schema validation tests.

* **Slice 2: Pluggable Document Extractor & In-Process PDF/Text Engine**
  - Define `DocumentExtractor` protocol and `ExtractionResult` in `backend/app/health/extraction.py`.
  - Implement `PyPDFExtractor` using `pypdf` for native digital text PDFs.
  - Implement `PlainTextExtractor` for `text/plain` files.
  - Implement text sanitization (collapsing whitespace, stripping null bytes).
  - *Verification*: Unit tests with real text PDFs, empty PDFs, corrupted files, and plain text files proving deterministic extraction and error handling.

* **Slice 3: Document Upload Integration & Lifecycle Management**
  - Integrate extraction into `POST /api/v1/documents` endpoint in `backend/app/api/documents.py`.
  - Decouple upload from extraction: S3 upload and `MedicalDocument` insertion succeed regardless of extraction status.
  - Record extraction results in `document_extractions` (`COMPLETED`, `UNSUPPORTED`, or `FAILED`).
  - Update `GET /api/v1/documents/{id}` to return `extraction_status`.
  - *Verification*: API integration tests asserting file upload succeeds even when extraction encounters an unsupported or corrupted file.

* **Slice 4: Document Query Understanding & Evidence Evaluator**
  - Update `backend/app/health/query_understanding.py` to identify document targets (`QueryDomain.LABS`, `QueryDomain.REPORTS`, `QueryDomain.CLINICAL_DOCUMENTS`).
  - Update `backend/app/health/evidence_evaluator.py` to inspect candidate document text for queried terms and analytes.
  - Implement deterministic evidence status generation (`SUFFICIENT`, `PARTIALLY_SUFFICIENT`, `INSUFFICIENT`) and directives for document evidence.
  - *Verification*: Unit tests evaluating document evidence on sample lab reports and clinical summaries.

* **Slice 5: Deterministic Document Selection & Context Tokenizer (`[DOC-N]`)**
  - Implement deterministic selection service in `backend/app/health/document_selection.py` (filtering by patient, completed status, document type, and recency; bounding to Top-K).
  - Update `backend/app/health/sanitized_context.py` to serialize selected document excerpts with `[DOC-1]`, `[DOC-2]` tokens.
  - Implement data minimization (stripping recognized administrative headers, MRNs, billing patterns).
  - Enforce token budget caps ($\le 1,500$ tokens per document excerpt).
  - *Verification*: Unit tests proving token budget enforcement, administrative identifier stripping, and bidirectional reference map correctness.

* **Slice 6: LLM Gateway Synthesis, Citation Reconciliation & Mock Provider**
  - Update `OpenAIAdapter` dynamic prompt with document evidence block, non-diagnostic constraints, and laboratory explanation rules.
  - Extend server-side citation reconciliation to map `[DOC-N]` tokens back to canonical `MedicalDocument.id`.
  - Extend `MockLLMProvider` with deterministic document-synthesis rules for offline testing.
  - *Verification*: Gateway unit tests verifying prompt assembly, mock synthesis, and citation reconciliation.

* **Slice 7: Frontend Provenance Drawer, E2E Integration & Full Regression Suite**
  - Update `HealthInquiryView.tsx` to render document citation cards (`entity_type: "DOCUMENT"`), displaying document display name, date, type badge, and download trigger.
  - Run full automated comparative evaluation suite (`test_m2_evaluation.py` expanded to document inquiries).
  - Run full backend regression (`pytest`), full frontend regression (`npm test`), and linting (`ruff`, `eslint`).
  - *Verification*: 100% test pass rate across all existing M1/M2 and new M3 test suites.

---

## 13. Acceptance Criteria

### Implementation-Level Acceptance Criteria

1. **Upload & Canonical Preservation**:
   - Uploading a valid document stores the binary in S3/MinIO and creates a `medical_documents` record regardless of extraction outcome.
2. **Extraction Execution & Lifecycle**:
   - Native digital text PDFs and plain text files achieve `extraction_status = 'COMPLETED'` with non-empty `extracted_text`.
3. **Extraction Failure & Unsupported File Resilience**:
   - Image-only PDFs and raster files achieve `extraction_status = 'UNSUPPORTED'`. Corrupted files achieve `extraction_status = 'FAILED'`. In both cases, upload succeeds and the file remains downloadable in the catalog.
4. **Strict Tenant Isolation**:
   - An inquiry by Patient A never selects, evaluates, extracts, cites, or returns text from Patient B's documents under any circumstance.
5. **Deterministic Document Selection**:
   - Inquiries targeting lab reports select exclusively the most recent completed `LAB_REPORT` documents, bounded to a maximum of $K=2$ documents.
6. **Evidence Sufficiency & Absence Honesty**:
   - When a queried analyte (e.g. "cholesterol") is present in the document, evidence is `SUFFICIENT`.
   - When a queried analyte is absent from the document, evidence is `INSUFFICIENT` and the synthesized answer explicitly states the document does not contain it.
7. **Document Reference Tokenization & Minimization**:
   - Prompts sent to external models contain zero internal UUIDs, storage keys, or recognized administrative MRN/account patterns. All document evidence is referenced by ordinal tokens (`[DOC-1]`).
8. **Citation Reconciliation to Canonical Artifact**:
   - 100% of emitted document citations reconcile to a verified `MedicalDocument.id` owned by the authenticated patient. Hallucinated or unmapped tokens are stripped.
9. **Deterministic Safety Precedence**:
   - Inquiries describing acute emergency symptoms immediately short-circuit to `SAFETY_ADVISORY` with **zero LLM network calls** and zero tokens spent, even if an uploaded document is referenced.
10. **Clinical Boundary Adherence**:
    - The synthesized response never declares a diagnosis, never prescribes or modifies treatments, and never assigns a triage urgency score.
11. **Offline Deterministic Mock Provider Parity**:
    - When `LLM_PROVIDER=mock`, the entire inquiry flow succeeds offline with 100% deterministic test reproducibility.
12. **Preservation of M1/M2 Invariants**:
    - 100% pass rate maintained on all existing M1 structured inquiry and M2 live gateway regression tests.

---

## 14. Explicit Non-Goals

The following capabilities are explicitly excluded from Milestone 3:
* **NO Vector Databases or `pgvector`**: No vector extensions or semantic vector search.
* **NO Text Embeddings**: No embedding model calls or vector indexing pipelines.
* **NO Semantic Vector Retrieval or Chunk Ranking**: Retrieval uses deterministic metadata/intent/recency rules only.
* **NO Optical Character Recognition (OCR)**: Scanned image documents are stored safely but marked `UNSUPPORTED` for text extraction.
* **NO Multi-Turn Conversational Memory**: No chat sessions, conversation threads, or multi-turn dialogue history (Milestone 5).
* **NO Streaming Responses (SSE)**: Synchronous request/response preserved.
* **NO Autonomous Agents or Tool Calling**: The LLM performs pure language synthesis.
* **NO Proactive Monitoring or Trend Alerts**: Background report scanning is deferred to Phase 3.
* **NO Clinical Decision Support (CDS)**: No drug-interaction engines, clinical scoring, or physician advisory systems.
* **NO Automatic Mutation of Structured Clinical Records**: Document findings are **never** automatically inserted into `conditions` or `medications` tables without explicit user review and confirmation.

---

## 15. Deferred Decisions

The following architectural and implementation decisions are intentionally deferred to future milestones:

| Decision | Deferred To | Rationale |
| :--- | :--- | :--- |
| **Vector DB / pgvector Strategy** | Milestone 4 | Scalable vector search requires chunking strategies and embedding pipelines that build upon M3's extraction foundation. |
| **Chunking Strategy (Fixed vs Semantic)** | Milestone 4 | Bounded document extraction suffices for M3's deterministic selection without introducing premature chunk infrastructure. |
| **PDF Viewport Deep-Linking & Bounding Boxes** | Post-M5 (UI Enhancement) | Requires PDF.js visual coordinates and bounding box serialization, which adds visual polish without changing evidence truth. |
| **Asynchronous Extraction Worker (Celery/Redis)** | Post-M3 Scaling | In-process extraction is reliable for M3's volume. Decoupled protocol allows drop-in replacement when background queues are introduced. |
| **Multi-Turn Conversation Storage Schema** | Milestone 5 | Multi-turn state modeling belongs in the dialogue milestone. |

---

## 16. Risks & Unknowns

| Risk / Unknown | Impact | Mitigation Strategy |
| :--- | :--- | :--- |
| **PDF Layout & Table Extraction Variance** | Dense multi-column lab tables may lose formatting when extracted as flat text. | `pypdf` extraction handles basic tables; prompt instruct model to interpret line-delimited key-value lab records. Complex layout parsing reserved for M4. |
| **Prompt Injection via Uploaded Documents** | Malicious text in a PDF could attempt to instruct the LLM to ignore system safety rules. | The system prompt strictly frames document contents within a delimited, non-executable data block (`=== DOCUMENT EVIDENCE ===`) with explicit instructions to treat all text inside as passive evidence. |
| **Provider Content Moderation False Positives** | Mentioning sensitive clinical conditions in documents might trigger OpenAI safety refusals. | M2's locked safety refusal interceptor catches provider refusals and falls back to deterministic evidence directives without crashing. |
| **Token Budget Saturation on Large Documents** | Extremely long documents could exceed context limits. | Hard character cap (4,000–6,000 chars / ~1,000–1,500 tokens) deterministically truncates document context before prompt serialization. |
| **Patient Misunderstanding of Abnormal Flags** | Patients seeing "High" flags on benign variations may panic. | Prompts mandate that the model frame findings neutrally and explicitly advise discussing results with the ordering physician. |

---

## 17. Final Architecture Decisions Table

| Decision Area | Locked Architecture Decision | Primary Architectural Rationale |
| :--- | :--- | :--- |
| **Milestone Purpose** | **Medical Document Understanding & Content Grounding** | Bridges Phase 1 file upload to Phase 2 grounded inquiry without premature RAG. |
| **Retrieval Architecture** | **Deterministic Document Selection** (Intent + Metadata + Recency) | Eliminates vector database complexity in M3; sets a firm foundation for M4. |
| **Derived Content Storage** | **Option A: Dedicated `document_extractions` table** | Decouples raw artifact from derived text; fast catalog queries; clean M4 evolution. |
| **Supported Formats** | **Native Digital PDF (`application/pdf`) and Plain Text (`text/plain`)** | Delivers reliable text extraction while deferring complex OCR image parsing. |
| **Extraction Lifecycle** | **Decoupled execution behind `DocumentExtractor` protocol** | Upload success is independent of extraction success; protocol is swappable with async worker. |
| **Data Minimization** | **Deterministic stripping of internal UUIDs and administrative headers** | Minimizes unnecessary PHI exposure while explicitly avoiding false de-identification claims. |
| **Citation Scheme** | **`[DOC-N]` reconciled server-side to canonical `MedicalDocument.id`** | Extends M2 reference-token model; guarantees citation integrity to genuine uploaded file. |
| **Clinical Safety Boundary** | **Plain-language explanation of documented facts; strictly NO diagnosis or CDS** | Strict alignment with `SPEC.md §8` and `DESIGN.md §11`. |
| **Emergency Safety** | **Deterministic pre-flight interceptor (`evaluate_safety`)** | Acute symptom queries bypass document extraction and LLM inference with zero network calls. |
| **Testing & CI/CD** | **`MockLLMProvider` deterministic parity** | 100% offline test suite execution and verification in CI/CD without paid APIs. |

---

> **Read-Only Verification Complete**: The architecture specification for Milestone 3 is locked. No implementation code has been modified, no database migrations applied, and no commits created. Implementation must await explicit authorization to proceed to Slice 1.
