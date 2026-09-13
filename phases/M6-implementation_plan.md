# Milestone 6 Implementation Plan — Provenance & Data Integrity

> **Status: LOCKED** (Architecture, data contracts, and implementation specifications finalized and approved)

## 1. Goal / Scope

Establish explicit, verifiable data provenance and integrity across all personal health records in the system, distinguishing information origin from epistemic verification status to prevent epistemic drift in downstream reasoning (`docs/SPEC.md §9`, `docs/DESIGN.md §14`).

**Entity Scope**:
- Clinical Health Entities: `conditions`, `symptoms`, `medications`, `allergies`
- Patient Goals: `patient_goals`
- Medical Documents: `medical_documents`

---

## 2. Canonical Provenance Contract

The provenance model enforces two distinct classifications:

1. **`source_type` (Origin Classification)**: Indicates where the information originated.
   - **Type**: `VARCHAR(50)` / Pydantic enum `HealthSourceType`.
   - **Active Phase 1 Values**:
     - `PATIENT_REPORTED`: Provided directly by the patient via UI entry.
     - `SOURCE_DOCUMENT`: Originated from or is explicitly linked to an uploaded medical document.
   - **Reserved Value**:
     - `CLINICIAN_CONFIRMED`: Structural enumeration room for future clinician workflows (cannot be asserted by clients in Phase 1).

2. **`source_id` (Source Link)**:
   - **Type**: `UUID`, nullable. Foreign key referencing `medical_documents(id)` with `ON DELETE SET NULL`.
   - Represents the active link to the source artifact. Exists only on clinical health entities and `patient_goals`.

3. **`verification_state` (Epistemic / Verification Classification)**: Indicates verification status.
   - **Type**: `VARCHAR(50)` / Pydantic enum `VerificationState`.
   - **Authority**: Strictly **server-owned and response-only in Phase 1**. Clients cannot submit or alter this field.
   - **Active Phase 1 Values (Server-Derived)**:
     - `PATIENT_REPORTED`: Derived automatically when `source_type == PATIENT_REPORTED`.
     - `SOURCE_RECORDED`: Derived automatically when `source_type == SOURCE_DOCUMENT`.
   - **Reserved Values**:
     - `CLINICIAN_CONFIRMED`, `AI_DERIVED`, `UNCERTAIN`: Structural room only. Cannot be asserted by clients in Phase 1.

---

## 3. Entity Scope

### Clinical Entities (`conditions`, `symptoms`, `medications`, `allergies`) & `patient_goals`
- **Database Columns**: `source_type VARCHAR(50) NOT NULL DEFAULT 'PATIENT_REPORTED'`, `source_id UUID NULL REFERENCES medical_documents(id) ON DELETE SET NULL`, `verification_state VARCHAR(50) NOT NULL DEFAULT 'PATIENT_REPORTED'`. Indexed on `source_id`.
- **API Input Contract (Create & Update)**:
  - May accept `source_type` and `source_id`.
  - MUST NOT accept `verification_state`. Any payload containing `verification_state` returns **HTTP 422 Unprocessable Entity**.
- **API Output Contract**: Exposes `source_type`, `source_id`, and `verification_state`.

### Medical Documents (`medical_documents`)
- **Database Columns**: `source_type VARCHAR(50) NOT NULL DEFAULT 'PATIENT_REPORTED'`, `verification_state VARCHAR(50) NOT NULL DEFAULT 'PATIENT_REPORTED'`. No `source_id` column exists (no document-to-document chains).
- **Database Invariants**: Enforced via PostgreSQL `CHECK` constraints:
  - `CHECK (source_type = 'PATIENT_REPORTED')`
  - `CHECK (verification_state = 'PATIENT_REPORTED')`
- **API Input Contract (Create/Upload & Update)**:
  - MUST NOT accept `source_type`, `source_id`, or `verification_state`.
  - Any attempt to provide any of these provenance fields deterministically returns **HTTP 422 Unprocessable Entity** (no silent ignore behavior).
  - `documents.py` is explicitly excluded from generic provenance input rules.
- **API Output Contract**: Exposes `source_type` and `verification_state` only. No `source_id` is exposed.

---

## 4. Integrity Invariants

1. **Database-Level Constraints (PostgreSQL)**:
   - Use `VARCHAR(50)` columns with explicit `CHECK` constraints (no native PostgreSQL ENUMs).
   - Clinical tables & `patient_goals`:
     - `CHECK (source_type IN ('PATIENT_REPORTED', 'SOURCE_DOCUMENT', 'CLINICIAN_CONFIRMED'))`
     - `CHECK (verification_state IN ('PATIENT_REPORTED', 'SOURCE_RECORDED', 'CLINICIAN_CONFIRMED', 'AI_DERIVED', 'UNCERTAIN'))`
   - `medical_documents`:
     - `CHECK (source_type = 'PATIENT_REPORTED')`
     - `CHECK (verification_state = 'PATIENT_REPORTED')`
   - Foreign keys: `source_id` references `medical_documents(id)` with `ON DELETE SET NULL`.

2. **Centralized Validation Architecture**:
   - Validation and derivation logic is centralized in `backend/app/health/provenance.py` via `validate_and_resolve_provenance()`.
   - All clinical services (`conditions.py`, `symptoms.py`, `medications.py`, `allergies.py`) and `goals.py` delegate to this helper to eliminate logic duplication.

3. **Client Input Validation Rules (Clinical & Goals)**:
   - **`PATIENT_REPORTED`**: `source_id` must be `None`. Providing a non-null `source_id` returns **HTTP 422 Unprocessable Entity**.
   - **`SOURCE_DOCUMENT`**: `source_id` is required. If missing or null returns **HTTP 422 Unprocessable Entity**.
   - **Source Document Existence & Ownership**: Referenced document must exist and belong to the authenticated patient. Nonexistent `source_id` or cross-patient `source_id` deterministically returns **HTTP 422 Unprocessable Entity**.
   - **Reserved States Anti-Tampering**: Supplying `source_type == CLINICIAN_CONFIRMED` or any reserved verification state (`CLINICIAN_CONFIRMED`, `AI_DERIVED`, `UNCERTAIN`) returns **HTTP 422 Unprocessable Entity**.
   - **Verification State Anti-Tampering**: Supplying `verification_state` on Create or Update returns **HTTP 422 Unprocessable Entity** (explicitly rejected, never silently stripped).

4. **Atomic Provenance Update Rules**:
   - **Neither provenance field provided**: When updating a clinical record without `source_type` or `source_id` in the payload, the helper bypasses new-pair validation entirely and preserves existing provenance values. Updates to non-provenance clinical fields (`name`, `notes`, `status`, etc.) never alter provenance.
   - **Either provenance field provided**: For updates, validate the effective source_type/source_id pair formed from supplied values combined with existing values for omitted provenance fields. Any partial, contradictory, or invalid pair (e.g. setting `source_type = SOURCE_DOCUMENT` with `source_id = null`, or providing `source_id` with `PATIENT_REPORTED`) returns **HTTP 422 Unprocessable Entity**.

---

## 5. Document Deletion / Detached Source Semantics

When an uploaded `MedicalDocument` referenced by clinical entities is deleted:

1. **Database Foreign Key Action**:
   - `ON DELETE SET NULL` automatically updates referencing rows, setting `source_id = NULL`.
2. **Provenance Metadata Preservation**:
   - `source_type` remains `SOURCE_DOCUMENT` (preserving the origin classification).
   - `verification_state` remains `SOURCE_RECORDED` (preserving epistemic integrity).
   - The entity is **never** automatically downgraded or converted to `PATIENT_REPORTED`.
   - `source_id` represents the *current link* to the artifact, which is now severed.
3. **Subsequent Clinical Updates (Detached Source Lifecycle)**:
   - When updating non-provenance fields (e.g. `notes`, `status`, `name`) on an entity where `source_id == NULL` and `source_type == SOURCE_DOCUMENT`:
     - Because neither `source_type` nor `source_id` is passed in the update payload, the validation helper bypasses new-pair validation.
     - The update **MUST succeed (HTTP 200 OK)**.
     - Existing state is preserved: `source_type = SOURCE_DOCUMENT`, `source_id = NULL`, `verification_state = SOURCE_RECORDED`.
4. **Frontend UX Handling**:
   - Valid link (`source_id` present): Displays "Source Document" badge and a clickable link to view the document.
   - Detached link (`source_id == null`): Displays "Source Document" badge with **no broken link** (no link rendered, no error shown).

---

## 6. Implementation Sequence

### M6-1: Database Schema & Models
- Create Alembic migration `backend/alembic/versions/0003_add_provenance_and_integrity.py`:
  - Add `source_id` (FK `medical_documents.id` ON DELETE SET NULL) and `verification_state` to `conditions`, `symptoms`, `medications`, `allergies`.
  - Add `source_type`, `source_id`, `verification_state` to `patient_goals`.
  - Add `verification_state` to `medical_documents` (no `source_id`).
  - Add PostgreSQL `CHECK` constraints on `VARCHAR(50)` columns for canonical `source_type` and `verification_state` across all tables.
  - Add dedicated `CHECK` constraints on `medical_documents` locking `source_type = 'PATIENT_REPORTED'` and `verification_state = 'PATIENT_REPORTED'`.
  - Add indexes on `source_id` columns.
- Update SQLAlchemy ORM models in `backend/app/db/models.py`.

### M6-2: Domain Schemas & Contracts
- Create `backend/app/schemas/provenance.py` with `HealthSourceType` and `VerificationState` enums.
- Update Pydantic schemas in `condition.py`, `symptom.py`, `medication.py`, `allergy.py`, `goal.py`:
  - Create/Update schemas accept `source_type` and `source_id`; explicitly reject `verification_state` with HTTP 422.
  - Response schemas include `source_type`, `source_id`, `verification_state`.
- Update `backend/app/schemas/document.py`:
  - Create/Update schemas explicitly reject `source_type`, `source_id`, and `verification_state` with HTTP 422.
  - Response schemas include `source_type` and `verification_state` only (no `source_id`).

### M6-3: Shared Service Layer Integrity
- Implement `validate_and_resolve_provenance()` in `backend/app/health/provenance.py`.
- Refactor CRUD operations in `conditions.py`, `symptoms.py`, `medications.py`, `allergies.py`, `goals.py` to use the shared helper.
- Enforce server derivation, anti-tampering, patient isolation, atomic update validation, and detached source bypass.

### M6-4: API Endpoints & Route Handlers
- Update route handlers in `backend/app/api/`:
  - `conditions.py`, `symptoms.py`, `medications.py`, `allergies.py`, `goals.py`: accept provenance parameters on Create/Update, reject client `verification_state` with HTTP 422, return provenance metadata.
  - `documents.py`: strictly reject `source_type`, `source_id`, and `verification_state` with HTTP 422 on upload and update endpoints; return responses with `source_type` and `verification_state` only.

### M6-5: Frontend Client & Provenance UI
- Update `frontend/src/lib/api.ts` with provenance types.
- Update clinical list components (`ConditionsList`, `SymptomsList`, `MedicationsList`, `AllergiesList`, `GoalsList`) to render provenance badges (`Patient Reported` vs `Source Document`). Render document link only when `source_id` is non-null.
- Update creation forms to support two explicit paths:
  - Patient Reported: document selector is hidden/not required.
  - Source Document: document selector is shown and required.

### M6-6: Milestone 6 & Full Phase 1 Regression
- Execute backend `pytest` and frontend `npm run test` suites across all Phase 1 milestones (M1–M6).
- Perform end-to-end manual verification.

---

## 7. Acceptance Criteria

- [ ] **Database Constraints**: All clinical tables and `patient_goals` enforce canonical `source_type` and `verification_state` via PostgreSQL `CHECK` constraints on `VARCHAR(50)` columns.
- [ ] **Medical Document Invariants**: `medical_documents` database constraints enforce `source_type = 'PATIENT_REPORTED'` and `verification_state = 'PATIENT_REPORTED'`. No `source_id` column exists on `medical_documents`.
- [ ] **Medical Document API Invariant**: Upload and update endpoints for `medical_documents` deterministically reject `source_type`, `source_id`, or `verification_state` with HTTP 422 (no silent ignore). Responses expose `source_type` and `verification_state` only.
- [ ] **Server-Owned Verification State**: Clients cannot submit or alter `verification_state`. Any Create/Update payload containing `verification_state` returns HTTP 422.
- [ ] **Server Derivation**: Server derives `PATIENT_REPORTED` -> `PATIENT_REPORTED` and `SOURCE_DOCUMENT` -> `SOURCE_RECORDED`.
- [ ] **Patient Isolation & Source Validation**: Nonexistent `source_id` or cross-patient `source_id` deterministically returns HTTP 422.
- [ ] **Invalid Source Pairing**: `PATIENT_REPORTED` with non-null `source_id` returns HTTP 422. `SOURCE_DOCUMENT` without `source_id` returns HTTP 422.
- [ ] **Reserved States**: Client payloads asserting `CLINICIAN_CONFIRMED`, `AI_DERIVED`, or `UNCERTAIN` return HTTP 422.
- [ ] **Atomic Provenance Updates**: Omitting provenance fields preserves existing values. Partial or inconsistent provenance updates return HTTP 422.
- [ ] **Detached Source Lifecycle**: Deleting a source document sets `source_id = NULL` via `ON DELETE SET NULL`, preserving `source_type = SOURCE_DOCUMENT` and `verification_state = SOURCE_RECORDED`. Non-provenance updates to detached entities succeed (HTTP 200) and preserve detached state.
- [ ] **Centralized Architecture**: Validation helper in `backend/app/health/provenance.py` is reused across all clinical services and `patient_goals`.
- [ ] **Frontend Presentation**: Visual badges display provenance. Clickable link rendered if `source_id` is present; badge without broken link rendered if `source_id` is null. Forms require document selection for Source Document only.
- [ ] **Regression Clean**: All previous M1–M5 tests continue to pass without regressions.

---

## 8. Backend Test Matrix

### 1. Database & Migrations (`tests/test_schema_migration.py`, `tests/test_postgresql_validation.py`)
- **Migration Cleanliness**: Migration `0003_add_provenance_and_integrity.py` applies and downgrades cleanly.
- **Column Verification**: Verify `source_id` and `verification_state` exist on clinical tables; `source_type`, `source_id`, `verification_state` on `patient_goals`; `verification_state` on `medical_documents` (no `source_id`).
- **Referential Integrity**: FK `source_id` references `medical_documents.id` with `ON DELETE SET NULL`.
- **CHECK Constraint Enforcement**: Direct SQL insert of invalid string for `source_type` or `verification_state` on clinical tables raises DB integrity error.
- **Medical Document DB Invariants**: Direct SQL insert/update on `medical_documents` with `source_type != 'PATIENT_REPORTED'` or `verification_state != 'PATIENT_REPORTED'` raises DB integrity error.

### 2. Parametrized Shared Contract (`tests/test_provenance_shared_contract.py`)
Parametrized across all 5 health domain entities (`Condition`, `Symptom`, `Medication`, `Allergy`, `PatientGoal`):
- **Default Create**: Creation without provenance defaults to `source_type = "PATIENT_REPORTED"`, `source_id = None`, `verification_state = "PATIENT_REPORTED"`.
- **Valid Source Linking**: Creation with valid owned document sets `source_type = "SOURCE_DOCUMENT"`, `source_id = Doc.id`, derives `verification_state = "SOURCE_RECORDED"`.
- **Nonexistent Document**: Linking to nonexistent UUID returns **HTTP 422**.
- **Cross-Patient Isolation**: Linking to a document owned by another patient returns **HTTP 422**.
- **Invalid Patient-Reported Payload**: `source_type = "PATIENT_REPORTED"` with non-null `source_id` returns **HTTP 422**.
- **Reserved States Input**: Payload with `source_type = "CLINICIAN_CONFIRMED"` or any reserved verification state returns **HTTP 422**.
- **Non-Provenance Update**: Updating clinical fields (`notes`, `status`) without provenance fields preserves existing provenance.
- **Atomic Inconsistent Update**: Updating with partial/inconsistent provenance (e.g. setting `source_type = "SOURCE_DOCUMENT"` without `source_id`) returns **HTTP 422**.
- **Document Deletion Handling**: Deleting the linked `MedicalDocument` sets `source_id = None`, while preserving `source_type = "SOURCE_DOCUMENT"` and `verification_state = "SOURCE_RECORDED"`.
- **Detached Source Non-Provenance Update**: On an entity with `source_type = "SOURCE_DOCUMENT"` and `source_id = None` (deleted document), a clinical update (`PATCH {"notes": "Updated", "status": "resolved"}`) succeeds (**HTTP 200**) and preserves `source_type = "SOURCE_DOCUMENT"`, `source_id = None`, `verification_state = "SOURCE_RECORDED"`.
- **Detached Source Inconsistent Update**: On a detached entity, explicitly sending `{"source_type": "SOURCE_DOCUMENT", "source_id": None}` returns **HTTP 422**.

### 3. Anti-Tampering Suite (`tests/test_provenance_anti_tampering.py`)
Tested across Create and Update endpoints for all clinical entities and patient goals:
- `POST` payload containing `verification_state` returns **HTTP 422**.
- `PATCH`/`PUT` payload containing `verification_state` returns **HTTP 422**.
- Rejection is explicit and deterministic: verification_state tampering must be rejected with HTTP 422 regardless of whether the remaining request payload is otherwise valid or invalid.

### 4. Medical Documents Suite (`tests/test_medical_documents_provenance.py`)
- **Default Provenance**: Uploaded document has `source_type = "PATIENT_REPORTED"` and `verification_state = "PATIENT_REPORTED"`.
- **No source_id**: Schema and endpoint do not accept or expose `source_id`.
- **Deterministic Input Rejection**: Upload or update payload containing `source_type`, `source_id`, or `verification_state` deterministically returns **HTTP 422** (no silent ignore).
- **No Document Chains**: Document cannot reference another document as a source.
- **DB Invariant Enforcement**: Direct DB write with invalid provenance fails CHECK constraint.

---

## 9. Frontend Test Matrix

### Component Tests (`frontend/src/tests/ClinicalLists.test.tsx`, `frontend/src/tests/ConditionsList.test.tsx`)
- **Badge Rendering**:
  - `source_type: "PATIENT_REPORTED"` renders "Patient Reported" badge.
  - `source_type: "SOURCE_DOCUMENT"` with valid `source_id` renders "Source Document" badge and clickable link.
  - `source_type: "SOURCE_DOCUMENT"` with `source_id: null` renders "Source Document" badge with **no broken link**.
- **Conditional Document Selector**:
  - Selecting "Patient Reported" hides/disables document selector.
  - Selecting "Source Document" displays document selector and enforces selection.
- **Form Payload Validation**:
  - Submitting with document selected sends `source_type: "SOURCE_DOCUMENT"` and `source_id`.
  - Submitting as patient-reported sends `source_type: "PATIENT_REPORTED"` and `source_id: null`.
  - Form payload never includes `verification_state`.

---

## 10. Final Manual E2E Verification

1. **Upload Document**: Upload a medical document PDF (e.g. "Lab_Report_2026.pdf").
2. **Create Linked Entity**: In Conditions form, select "Source Document", choose "Lab_Report_2026.pdf", add condition "Hypertension" -> verify "Source Document" badge and working document link.
3. **Create Patient-Reported Entity**: Select "Patient Reported" (document selector hidden), add symptom "Headache" -> verify "Patient Reported" badge.
4. **Edit Linked Entity**: Edit "Hypertension" notes -> verify notes update and provenance/link remain intact.
5. **Timeline View**: Check Timeline -> verify events render chronologically with clean source links.
6. **Delete Document**: Delete "Lab_Report_2026.pdf" in Documents tab -> reload Conditions tab -> verify "Hypertension" remains with `source_type = SOURCE_DOCUMENT`, `source_id = null`, `verification_state = SOURCE_RECORDED`, and **no broken link**.
7. **Edit Detached Entity**: Edit "Hypertension" notes after document deletion -> verify update succeeds (HTTP 200), notes are updated, and detached provenance is preserved.
8. **Patient Isolation**: Log in as a separate user -> verify zero visibility of User 1's documents, conditions, or provenance links.

---

## 11. Explicit Non-Goals / Boundaries

| Category | DO | DO NOT |
|---|---|---|
| **Database Constraints** | Use `VARCHAR(50)` with PostgreSQL `CHECK` constraints on all tables for canonical values; enforce `source_type = 'PATIENT_REPORTED'` and `verification_state = 'PATIENT_REPORTED'` specifically on `medical_documents`. | **DO NOT** use PostgreSQL native ENUM types. |
| **Verification State Authority** | Server derives verification state (`PATIENT_REPORTED` or `SOURCE_RECORDED`). Expose as response-only. Reject any client payload containing `verification_state` with HTTP 422. | **DO NOT** allow client payloads to submit or alter `verification_state`, and **DO NOT** rely on implicit field dropping. |
| **Medical Document API Inputs** | Deterministically reject with HTTP 422 any attempt to supply `source_type`, `source_id`, or `verification_state` in Create or Update payloads for `medical_documents`. | **DO NOT** include `documents.py` in generic provenance acceptance, and **DO NOT** silently ignore input provenance fields on medical documents. |
| **Provenance Updates & Detached Sources** | Enforce atomic provenance updates when provenance fields are provided (require complete valid pair; partial/inconsistent updates return HTTP 422). Bypass validation when provenance fields are omitted, preserving detached source states (`source_id = NULL`). | **DO NOT** allow partial provenance updates that leave `source_type` and `source_id` in conflict, and **DO NOT** reject clinical updates on detached source entities. |
| **Reserved States** | Classify `CLINICIAN_CONFIRMED`, `AI_DERIVED`, and `UNCERTAIN` as reserved states in Phase 1 (client assertion rejected with HTTP 422). | **DO NOT** implement clinician workflows, confirmation, AI derivation, OCR, RAG, embeddings, or inference. |
| **Cross-Patient Linking** | Reject cross-patient document linking deterministically with HTTP 422. | **DO NOT** return ambiguous status codes (e.g. 403 vs 422). |
| **Validation Architecture** | Centralize shared provenance validation in `backend/app/health/provenance.py` and reuse across all clinical domains and goals. | **DO NOT** duplicate validation logic across service files. |
| **Document Deletion** | Clear `source_id` to `NULL` via `ON DELETE SET NULL`, keeping `source_type == SOURCE_DOCUMENT` and `verification_state == SOURCE_RECORDED`. | **DO NOT** automatically convert `SOURCE_DOCUMENT` to `PATIENT_REPORTED` on document deletion. |
| **Frontend Presentation** | Display badge + document link for valid `source_id`; display badge without broken link when `source_id = null`. | **DO NOT** invent a new provenance classification or show broken links. |
| **Document Schema Scope** | Keep `source_type` and `verification_state` on `medical_documents` locked to `PATIENT_REPORTED` (non-editable in Phase 1). | **DO NOT** add `source_id` to `medical_documents` or invent document-to-document chains. |
| **Frontend Form UX** | Require document selector only when `SOURCE_DOCUMENT` is selected; omit/hide for `PATIENT_REPORTED`. | **DO NOT** show an arbitrary, indiscriminate document selector for every form. |
| **Milestones & Architecture** | Preserve existing M1–M5 contracts, Supabase auth, and local stack. | **DO NOT** break existing timeline contracts, alter auth flow, or introduce external queue/ledger infrastructure. |
