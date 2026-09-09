# Phase 1 — Personal Health Foundation Implementation Plan

This plan outlines the approach for executing the work defined in `phases/phase-01.md`. Our objective is to build a secure, foundational personal health space without yet introducing the AI chat components.

## Scope Discipline
- **Build only what Phase 1 requires.**
- **Do not implement future-phase functionality.**
- **Prefer simple, reversible technical decisions.**
- **Avoid premature infrastructure and abstraction.**
- **Preserve the domain foundations needed for future Personal Health Intelligence.**

## AI Boundary
- **Do not implement** AI chat, RAG, vector search, personal health AI memory, proactive insights, or clinical decision support in Phase 1.
- Phase 1 establishes the trustworthy health-data foundation that Phase 2 will build intelligence on top of.

## Project Structure
We will maintain a simple repository structure without monorepo frameworks (like Turborepo):
```
/
├── frontend/ (React, TypeScript, Vite)
├── backend/  (FastAPI, Python)
├── docs/
└── phases/
```

## Mandatory Development Loop
Every meaningful code change must follow this loop. Do not wait until the end of a milestone to test everything. **Every mini-feature must include the creation or update of its relevant automated tests as part of the same change.**
1. Implement the smallest meaningful change
2. Run focused tests
3. Fix failures
4. Run regression tests
5. Review behavior
6. Proceed

---

## Proposed Changes

### Milestone 1 — Project Foundation

#### WHAT
Create the application foundation and establish the project structure.

#### WHY
We need a stable base before introducing health-data functionality.

#### Lightweight Implementation Direction
- **Frontend:** Initialize a lightweight web frontend using React, TypeScript, and Vite. This serves as a thin reference client for exercising the backend and validating product workflows. Keep important business logic in the backend.
- **Backend:** Initialize FastAPI with Python.
- **Database / Infrastructure:** Set up PostgreSQL. Use Docker only where it simplifies local development. Do not introduce Redis or `pgvector`.
- **Formatting/Linting:** Configure standard formatting (Ruff for Python linting and formatting, ESLint/Prettier for Frontend).

#### Acceptance Criteria
- Application runs locally.
- Codebase has clear module boundaries (`frontend/`, `backend/`, `docs/`, `phases/`).
- Basic development and test commands work.
- Linting/formatting is configured.
- Environment configuration is documented.

#### Tests Required Before Proceeding
- Automated test suites (Vitest for frontend, Pytest for backend) can be executed successfully on the baseline codebase.

---

### Milestone 2 — Progressive Identity & User Isolation

#### WHAT
Users can immediately access and use their personal health workspace via an anonymous authenticated session, access only their own user-scoped data, and progressively convert to a permanent account without losing their existing account identity.

#### WHY
User isolation is a foundational requirement, not a later enhancement. At the same time, an anonymous-first approach removes upfront friction by granting immediate product access, while ensuring the user's account identity persists seamlessly when they convert to a permanent account for recovery or cross-device access.

#### Lightweight Implementation Direction
- **Anonymous Authentication:** On app launch, if no valid session exists, establish an anonymous session via Supabase Auth (`signInAnonymously()`).
- **Abuse Protection:** Anonymous sign-in must include appropriate abuse protection (for example CAPTCHA and/or rate limiting where required). Do not build a large anti-abuse system in Phase 1.
- **Backend Identity Validation:** The FastAPI backend must independently validate the JWT token (verifying signature, expiration, and user identity claims) via a dependency (`get_current_user`). The frontend is never a security boundary.
- **Identity Distinction:** Differentiate between anonymous and permanent identities where appropriate (e.g., tracking `is_anonymous` status).
- **Progressive Account Conversion:** Use Supabase's supported anonymous-to-permanent identity linking/conversion flow. The original authenticated `user_id` must remain unchanged, preserving account-level data continuity.
- **User Isolation:** Every protected query and mutation derives ownership strictly from the authenticated identity, ensuring an anonymous user can only access their own data, and data created anonymously remains isolated and accessible after conversion.

#### Acceptance Criteria
- Opening the application automatically establishes an anonymous authenticated session if none exists.
- The user can immediately enter the product and reach the personal health workspace without an upfront registration wall.
- Authenticated requests (both anonymous and permanent) are validated by the backend.
- Progressive account conversion preserves the original authenticated `user_id` with no loss of existing account-scoped data. The user-to-patient association will be established and validated in Milestone 3.
- Strict data isolation is enforced across all users (Anonymous User A cannot access Anonymous User B's data; Permanent User A cannot access Permanent User B's data).
- Unauthenticated and unauthorized requests are rejected (401/403).
- Session clearing behavior:
  - Permanent users can sign out normally.
  - Anonymous users must not be led to believe their anonymous workspace is recoverable after sign-out or session loss.
  - Any app-provided action that clears an anonymous session must require explicit user intent and warn that the anonymous workspace cannot be recovered. Unintentional external session loss (such as browser storage clearing) cannot be prevented.
  - If a new anonymous session is created afterward, it must receive a new isolated identity.

#### Tests Required Before Proceeding
- Anonymous session initialization and backend token verification.
- User isolation boundaries (Anonymous User A vs Anonymous User B; Permanent User A vs Permanent User B).
- Progressive account conversion verifying identity continuity (Anonymous session → `user_id` A → convert to permanent identity → `user_id` remains A). Actual health-data ownership continuity will be tested in Milestone 3 after the patient model exists.
- Rejection of expired, malformed, or missing authentication tokens.
- Explicit session clearing and verification that subsequent anonymous sessions are assigned distinct, isolated identities.

---

### Milestone 3 — Personal Health Profile

#### WHAT
Allow the user to create and manage their basic health profile.

#### WHY
This is the first representation of the individual's personal health context.

#### Lightweight Implementation Direction
- **Health Data Model:** Use structured PostgreSQL tables establishing clear domain concepts, rather than storing everything as unstructured text:
  - `users` (represents application/account identity)
  - `patients` (represents the healthcare identity/subject. They may initially have a one-to-one relationship with `users`, but the concepts should remain distinguishable)
  - `health_profiles`
  - `conditions`
  - `symptoms` / health concerns
  - `medications`
  - `allergies`
  - `patient_goals`
- Health-domain entities should be associated with a patient, and every backend query/mutation must enforce the authenticated user's authorization to that patient.
- Design health entities so provenance can be attached without restructuring the domain model later; full provenance behavior is implemented and validated in Milestone 6.
- Preserve temporal information where relevant (`started_at`, `ended_at`, `recorded_at`, `event_date`).
- Build standard CRUD REST endpoints in the backend and corresponding UI in the frontend.

#### Acceptance Criteria
- A user can add, view, edit, and remove (where appropriate) health information.
- Changes persist correctly across sessions.
- A user only sees information associated with their account.

#### Tests Required Before Proceeding
- Health-data CRUD operations.
- User isolation (again) after introducing health-data storage.
- Database constraints and temporal field validation.

---

### Milestone 4 — Medical Documents

#### WHAT
Allow users to upload, securely store, and retrieve medical documents.

#### WHY
Medical documents are one of the primary sources for the future Personal Health Model. The original document must remain available as evidence.

#### Lightweight Implementation Direction
- Use **S3-compatible object storage** for document blobs.
- Create a `documents` table in PostgreSQL to store metadata (e.g., document name, type, upload time, patient_id / patient ownership).
- **Do not** build sophisticated medical-document AI extraction in Phase 1. Focus purely on secure upload, storage, retrieval, patient ownership, and metadata.

#### Acceptance Criteria
- A user can upload a document.
- Stored documents can be retrieved and viewed.
- The original uploaded document remains retrievable as the authoritative source artifact.
- Documents are properly tied to their patient (cannot access documents belonging to another user's patient).
- Documents can be removed where supported.
- Storage failures must fail safely without leaving inconsistent document metadata.

#### Tests Required Before Proceeding
- Patient-level document ownership and secure access.
- File validation (handling invalid uploads safely).
- Safe handling of storage failures without leaving inconsistent metadata.

---

### Milestone 5 — Health Timeline

#### WHAT
Create a chronological representation of meaningful health events.

#### WHY
The product is intended to understand a person's health over time.

#### Lightweight Implementation Direction
- Create a `timeline_events` or `health_events` domain concept to track significant patient-health events.
- **Do not** infer clinical dates from document contents in Phase 1. Health events should use explicitly available dates, such as dates manually entered by the user or known from structured metadata. Document-content extraction belongs to Phase 2.
- **Do not** introduce event sourcing, event buses, or complex event architectures. The Phase 1 requirement is simply to represent meaningful health events with patient ownership, event date, type, and optional source, then display them chronologically.
- Avoid duplicate timeline events when the same underlying health event is created or updated.

#### Acceptance Criteria
- Meaningful patient-health events can be represented chronologically.
- Events contain relevant clinical dates (`event_date`).
- Events can be linked to their source where applicable.
- Historical events remain distinguishable from current state.

#### Tests Required Before Proceeding
- Timeline ordering (verify correct chronological ordering).
- Data retrieval across different temporal milestones.

---

### Milestone 6 — Provenance & Data Integrity

#### WHAT
Establish a clear distinction between where health information originated.

#### WHY
The future AI must know whether information is directly provided by the patient, recorded in a source document, or confirmed professionally to prevent epistemic drift.

#### Lightweight Implementation Direction
- Introduce explicit provenance fields to health data tables:
  - `source_type`
  - `source_id` (should reference another system entity when applicable, but may be null for directly patient-reported information)
  - `verification_state`
- Initial `source_type`s should include: `PATIENT_REPORTED`, `SOURCE_DOCUMENT`, `CLINICIAN_CONFIRMED`. PATIENT_REPORTED and SOURCE_DOCUMENT are active Phase 1 source types. CLINICIAN_CONFIRMED is reserved for future clinician workflows and must not trigger implementation of clinician functionality in Phase 1.
- Leave room for future AI-derived information, but **do not** implement AI-derived health memory in Phase 1.
- Never silently treat AI-generated or inferred information as confirmed medical information.

#### Acceptance Criteria
- Important health records identify their source when applicable.
- The system correctly handles and stores provenance metadata during CRUD operations.

#### Tests Required Before Proceeding
- Provenance preservation (metadata is correctly saved and retrieved, never silently overwritten).
- Data integrity validation across various source types.
- After Milestone 6 passes, run the complete backend and frontend regression suites before declaring Phase 1 complete.
