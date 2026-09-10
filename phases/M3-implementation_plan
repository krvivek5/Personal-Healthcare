# Milestone 3 — Personal Health Profile

## Context & Foundation

Milestone 2 is **implemented and locked**. It delivered:

- **`AuthenticatedUser`** — backend identity model extracted from verified ES256 JWT (`user_id`, `email`, `is_anonymous`)
- **`get_current_user`** — FastAPI dependency that enforces JWT validation on every protected endpoint
- **Anonymous-first session** — frontend `AuthContext` auto-establishes an anonymous Supabase session on first visit; the user reaches the workspace immediately with no registration wall
- **Progressive conversion** — user can attach email/password to their anonymous identity without changing `user_id`; the same authenticated identity persists after conversion
- **User isolation** — enforced on all protected endpoints; proven via the in-memory `_workspace_store` (explicitly marked for replacement in M3)
- **Test infrastructure** — `conftest.py`, mock JWKS client, `create_test_token()` helper, and a full isolation and token-validation test suite

Milestone 3 must build the first real health-data layer **on top of** that identity foundation. Every health entity must be owned by a patient, and every patient must be linked to the `user_id` established in Milestone 2.

---

## WHAT

Introduce the **Personal Health Profile** — the first persistent, structured health-data model. Users can create and manage:

| Domain | Entity | Notes |
|---|---|---|
| Identity bridge | `patients` table | Links `user_id` (auth) → patient record |
| Demographic context | `health_profiles` table | Basic demographics attached to a patient |
| Clinical entities | `conditions` | Diagnosed or reported conditions |
| Clinical entities | `symptoms` | Ongoing or historical concerns |
| Clinical entities | `medications` | Current and past medications |
| Clinical entities | `allergies` | Drug, food, environmental allergies |
| Goals | `patient_goals` | User-defined health goals |

Backend CRUD REST endpoints for all entities, with a minimal React frontend that exercises them.

---

## WHY

This is the first representation of the individual's personal health context. Without a structured patient record and health entities, there is nothing for the Phase 2 AI to reason about. The health data model established here must be correct by design — ownership, temporal context, and provenance hooks — because every later milestone builds on it.

Specifically this milestone:
- Completes the **user → patient identity bridge** that Milestone 2 deferred
- Creates the **structured truth layer** described in `DESIGN.md §4.2`
- Establishes **temporal fields** (`started_at`, `ended_at`, `recorded_at`) needed for the health timeline in Milestone 5
- Creates **provenance column stubs** (`source_type`) as directed by `phase-01-implementation_plan.md §Milestone 3` — full provenance behavior is Milestone 6

---

## Open Questions

> [!IMPORTANT]
> No blocking open questions, but the following design decisions are embedded in this plan and should be acknowledged before execution begins.

1. **One-to-one patient model**: This plan creates a single `Patient` per user (enforced by a `UNIQUE(user_id)` constraint). The SPEC and DESIGN note that user ↔ patient may eventually be one-to-many (e.g., caregivers). The constraint keeps M3 simple and correct; removing it later is a non-breaking migration. **This is the recommended approach.**

2. **Patient auto-creation**: When an authenticated user first reaches a health endpoint, their patient record is auto-created if it doesn't exist (`get_or_create_patient`). This eliminates a separate "create profile" step and matches the anonymous-first flow from M2.

3. **Provenance stubs in M3**: Per the phase-01 plan, health entities should be designed so provenance can be attached without restructuring later. This plan adds a `source_type` column (PostgreSQL `ENUM` or `VARCHAR`) defaulting to `PATIENT_REPORTED` on all clinical tables. Full provenance (source_id, verification_state) is Milestone 6.

---

## Proposed Changes

### Backend — Database Layer

The backend currently has no PostgreSQL tables. Milestone 3 introduces the schema.

---

#### [NEW] `backend/app/db/base.py`
SQLAlchemy async engine and session factory using the existing `DATABASE_URL` from `config.py`.

#### [NEW] `backend/app/db/models.py`
SQLAlchemy ORM models for all M3 entities:

```
Patient
  id          UUID PK
  user_id     UUID UNIQUE NOT NULL  ← links to Supabase auth user_id (UUID format)
  created_at  TIMESTAMPTZ DEFAULT NOW()
  updated_at  TIMESTAMPTZ DEFAULT NOW()

HealthProfile
  id              UUID PK
  patient_id      UUID FK → Patient.id NOT NULL UNIQUE  ← one profile per patient
  date_of_birth   DATE nullable
  biological_sex  VARCHAR nullable
  height_cm       NUMERIC nullable
  blood_group     VARCHAR nullable
  notes           TEXT nullable
  created_at      TIMESTAMPTZ
  updated_at      TIMESTAMPTZ

Condition
  id           UUID PK
  patient_id   UUID FK → Patient.id NOT NULL
  name         VARCHAR NOT NULL
  status       VARCHAR NOT NULL  (active | resolved)
  is_chronic   BOOLEAN DEFAULT FALSE
  started_at   DATE nullable
  ended_at     DATE nullable
  recorded_at  TIMESTAMPTZ DEFAULT NOW()
  notes        TEXT nullable
  source_type  VARCHAR DEFAULT 'PATIENT_REPORTED'
  created_at   TIMESTAMPTZ
  updated_at   TIMESTAMPTZ

Symptom
  id           UUID PK
  patient_id   UUID FK → Patient.id NOT NULL
  name         VARCHAR NOT NULL
  severity     VARCHAR nullable  (mild | moderate | severe)
  started_at   DATE nullable
  ended_at     DATE nullable
  recorded_at  TIMESTAMPTZ DEFAULT NOW()
  notes        TEXT nullable
  source_type  VARCHAR DEFAULT 'PATIENT_REPORTED'
  created_at   TIMESTAMPTZ
  updated_at   TIMESTAMPTZ

Medication
  id           UUID PK
  patient_id   UUID FK → Patient.id NOT NULL
  name         VARCHAR NOT NULL
  dosage       VARCHAR nullable
  frequency    VARCHAR nullable
  status       VARCHAR NOT NULL  (active | stopped)
  as_needed    BOOLEAN DEFAULT FALSE
  started_at   DATE nullable
  ended_at     DATE nullable
  recorded_at  TIMESTAMPTZ DEFAULT NOW()
  notes        TEXT nullable
  source_type  VARCHAR DEFAULT 'PATIENT_REPORTED'
  created_at   TIMESTAMPTZ
  updated_at   TIMESTAMPTZ

Allergy
  id              UUID PK
  patient_id      UUID FK → Patient.id NOT NULL
  allergen        VARCHAR NOT NULL
  reaction        VARCHAR nullable
  severity        VARCHAR nullable  (mild | moderate | severe | life_threatening)
  recorded_at     TIMESTAMPTZ DEFAULT NOW()
  notes           TEXT nullable
  source_type     VARCHAR DEFAULT 'PATIENT_REPORTED'
  created_at      TIMESTAMPTZ
  updated_at      TIMESTAMPTZ

PatientGoal
  id           UUID PK
  patient_id   UUID FK → Patient.id NOT NULL
  description  TEXT NOT NULL
  status       VARCHAR  (active | achieved | abandoned)
  target_date  DATE nullable
  recorded_at  TIMESTAMPTZ DEFAULT NOW()
  notes        TEXT nullable
  created_at   TIMESTAMPTZ
  updated_at   TIMESTAMPTZ
```

**Design notes:**
- `Patient.user_id` is typed as PostgreSQL `UUID` (with `UNIQUE` + `NOT NULL`), matching the UUID format of Supabase authenticated `sub` for stronger database integrity.
- All FKs reference `Patient.id`, never `user_id` directly. The authorization layer resolves `user_id → patient_id` at the boundary.
- `health_profiles` has a `UNIQUE(patient_id)` constraint enforcing at most one profile per patient.
- `Condition.status` is lifecycle state (`active` | `resolved`), while `is_chronic` (boolean) captures condition chronicity separately.
- `Medication.status` is lifecycle state (`active` | `stopped`), while `as_needed` (boolean) captures usage pattern (PRN) separately.
- `weight_kg` is intentionally absent from `health_profiles`. Weight is time-varying; storing it as a mutable profile field would silently discard longitudinal history. A dated health-measurement concept will be introduced in a future milestone.
- `source_type` stub is present on all clinical tables. In M3, `PATIENT_REPORTED` is the only active source type. `SOURCE_DOCUMENT` is reserved for Milestone 4. `CLINICIAN_CONFIRMED` is reserved for future clinician workflows and must not be exposed through any M3 API or UI.
- `started_at` / `ended_at` / `recorded_at` preserve temporal context for M5 (Health Timeline).

#### [NEW] `backend/alembic/`
Initialise Alembic in the backend and create a single initial migration that creates all M3 tables. Alembic is the migration mechanism for this project; do not use `create_all` or raw SQL scripts as an alternative.

---

### Backend — Domain / Service Layer

#### [NEW] `backend/app/health/patient.py`
`get_or_create_patient(user_id, db_session) → Patient`

This is the **user → patient identity bridge**. Resolve or create the user's patient identity before accessing patient-scoped health resources. Returns the existing patient for the user, or creates one atomically if none exists. This is where the M2 `user_id` becomes a patient record.

#### [NEW] `backend/app/health/` (per-domain service modules)
Prefer simple, domain-specific service functions for each entity (e.g., `conditions.py`, `medications.py`). Introduce shared abstractions only when behaviour is genuinely repetitive and the abstraction improves clarity — not speculatively. All operations accept a `patient_id` and never accept a raw `user_id`.

---

### Backend — API Endpoints

All routers require `get_current_user` and resolve patient ownership before touching data.

Authorization pattern for every endpoint:
```
user = get_current_user(...)         # JWT validation (M2)
patient = get_or_create_patient(user.id, db)  # identity bridge
# all queries/mutations scoped to patient.id
```

#### [NEW] `backend/app/api/patients.py`
```
GET  /api/v1/patients/me           → patient identity + health_profile summary
```

#### [NEW] `backend/app/api/health_profile.py`
```
GET  /api/v1/health-profile        → fetch own health profile
PUT  /api/v1/health-profile        → create or update health profile (upsert)
```

#### [NEW] `backend/app/api/conditions.py`
```
GET    /api/v1/conditions          → list own conditions
POST   /api/v1/conditions          → add condition
GET    /api/v1/conditions/{id}     → get condition
PATCH  /api/v1/conditions/{id}     → update condition
DELETE /api/v1/conditions/{id}     → remove condition
```

#### [NEW] `backend/app/api/symptoms.py`
```
GET    /api/v1/symptoms
POST   /api/v1/symptoms
GET    /api/v1/symptoms/{id}
PATCH  /api/v1/symptoms/{id}
DELETE /api/v1/symptoms/{id}
```

#### [NEW] `backend/app/api/medications.py`
```
GET    /api/v1/medications
POST   /api/v1/medications
GET    /api/v1/medications/{id}
PATCH  /api/v1/medications/{id}
DELETE /api/v1/medications/{id}
```

#### [NEW] `backend/app/api/allergies.py`
```
GET    /api/v1/allergies
POST   /api/v1/allergies
GET    /api/v1/allergies/{id}
PATCH  /api/v1/allergies/{id}
DELETE /api/v1/allergies/{id}
```

#### [NEW] `backend/app/api/goals.py`
```
GET    /api/v1/goals
POST   /api/v1/goals
GET    /api/v1/goals/{id}
PATCH  /api/v1/goals/{id}
DELETE /api/v1/goals/{id}
```

#### [MODIFY] `backend/app/main.py`
Register all new routers.

---

### Backend — Tests

Extend the existing test suite in `backend/tests/`.

#### [NEW] `backend/tests/test_patients.py`
- Patient auto-creation on first access
- Same user always resolves to the same patient
- Patient is not accessible cross-user

#### [NEW] `backend/tests/test_health_profile.py`
- Get empty profile (returns default/null fields)
- Create/update profile fields
- Changes persist (re-fetch returns updated values)
- Cross-user isolation: User B cannot read User A's profile

#### [NEW] `backend/tests/test_conditions.py`
- CRUD lifecycle: create → read → update → delete
- List returns only own conditions
- Cross-user isolation (403 on direct access to another user's condition)
- `started_at`, `ended_at`, `recorded_at` fields stored and returned correctly
- `source_type` defaults to `PATIENT_REPORTED`
- Invalid `status` value returns 422

#### [NEW] `backend/tests/test_symptoms.py`
- Same CRUD + isolation pattern as conditions
- Temporal field correctness

#### [NEW] `backend/tests/test_medications.py`
- CRUD + isolation + temporal fields

#### [NEW] `backend/tests/test_allergies.py`
- CRUD + isolation

#### [NEW] `backend/tests/test_goals.py`
- CRUD + isolation + status validation

#### [MODIFY] `backend/tests/test_auth.py`
- Add integration-level M3 identity continuity test verifying full health-data continuity:
  1. Anonymous identity auto-establishes session
  2. Patient record auto-created via `get_or_create_patient` on first endpoint access
  3. User creates at least one health entity (e.g. condition or medication)
  4. Anonymous identity is converted to a permanent account
  5. Confirm same `user_id` persists after conversion
  6. Confirm same `patient_id` resolves after conversion
  7. Confirm previously created health entity remains accessible under the permanent account
  *(Must be an integration-level test exercising the actual database and API stack, not merely a mocked unit test).*

---

### Frontend — Health Profile UI

The frontend should exercise all M3 endpoints to validate the full user experience. Keep it functional — this is not an aesthetic milestone.

#### [MODIFY] `frontend/src/lib/api.ts` (or create if not exists)
Typed API client wrapping `fetch` calls to the backend. Attaches Supabase `access_token` as `Bearer` header on every request. Centralizes backend URL.

#### [NEW] `frontend/src/components/HealthProfileView.tsx`
Patient identity summary + demographics form. Fields: date of birth, biological sex, blood group, height (`height_cm`). Do not include a weight field — weight is time-varying and absent from `health_profiles` by design. Do not include a provenance/source selector — `source_type` is set server-side to `PATIENT_REPORTED` for all M3-created data and is not exposed in the UI.

#### [NEW] `frontend/src/components/ConditionsList.tsx`
List view + add/edit/remove for conditions.

#### [NEW] `frontend/src/components/SymptomsList.tsx`
List view + add/edit/remove for symptoms.

#### [NEW] `frontend/src/components/MedicationsList.tsx`
List view + add/edit/remove for medications.

#### [NEW] `frontend/src/components/AllergiesList.tsx`
List view + add/edit/remove for allergies.

#### [NEW] `frontend/src/components/GoalsList.tsx`
List view + add/edit/remove for patient goals.

#### [MODIFY] `frontend/src/App.tsx`
Wire up new health profile components into the main workspace view, gated behind the existing auth session.

---

### Frontend — Tests

#### [MODIFY] `frontend/src/App.test.tsx` and/or new test files
- Health profile form renders and submits correctly (mock API)
- Each health entity list renders add/edit/remove controls
- Authorization header is included in API calls (verify token is attached)
- Correct loading/error states are displayed

---

## Acceptance Criteria

Mirroring `PHASE-01.md §Milestone 3`:

| # | Criterion |
|---|---|
| AC-1 | A user can add a condition, symptom, medication, allergy, and goal. |
| AC-2 | A user can view all health entities associated with their account. |
| AC-3 | A user can edit any of their health entities. |
| AC-4 | A user can remove health entities where appropriate. |
| AC-5 | Health data changes persist correctly across sessions (stored in PostgreSQL). |
| AC-6 | A user only sees information associated with their own patient record. |
| AC-7 | A user's anonymous session data (patient + health entities) remains accessible after progressive conversion to a permanent account. |
| AC-8 | `source_type` field is stored on all clinical entities and defaults to `PATIENT_REPORTED`. Only `PATIENT_REPORTED` is exposed through M3 APIs and UI; other source types are not surfaced. |
| AC-9 | Temporal fields (`started_at`, `ended_at`, `recorded_at`) are stored and retrieved correctly. |
| AC-10 | Unauthorized access to any health entity returns 403 (not 404, not 200). |

---

## Mini-Feature Sequence

Build in this order. Each mini-feature must have its tests written and passing before the next begins.

```
1. Database connection & SQLAlchemy session
2. ORM models (all tables in one migration)
3. Patient auto-creation (get_or_create_patient)
4. Health Profile endpoint (GET + PUT /health-profile)
5. Conditions CRUD
6. Symptoms CRUD
7. Medications CRUD
8. Allergies CRUD
9. Goals CRUD
10. Frontend API client
11. Health Profile UI
12. Clinical entity list UIs (conditions, symptoms, medications, allergies, goals)
13. Wire into App.tsx
```

---

## Tests Required After Each Mini-Feature

| Mini-Feature | Required Tests |
|---|---|
| 1. DB connection | Session factory creates connection; session is closed after request |
| 2. ORM models | Alembic migration applies successfully; expected tables and constraints exist; FK constraints are enforced; source_type default is correct. |
| 3. Patient auto-creation | First call creates patient; second call returns same patient; cross-user isolation |
| 4. Health Profile endpoints | GET returns empty profile; PUT creates/updates; cross-user isolation |
| 5. Conditions | Full CRUD lifecycle; temporal fields; isolation; invalid status → 422 |
| 6. Symptoms | Full CRUD lifecycle; temporal fields; isolation |
| 7. Medications | Full CRUD lifecycle; temporal fields; status transitions; isolation |
| 8. Allergies | Full CRUD lifecycle; severity enum; isolation |
| 9. Goals | Full CRUD lifecycle; status validation; isolation |
| 10. Frontend API client | Bearer header is attached; errors propagated correctly |
| 11–13. UI components | Form submission triggers correct API calls; list renders data; error state shown |

---

## Milestone-Level Validation

Before declaring Milestone 3 complete:

1. **Run full backend test suite** (`pytest backend/tests/`) — all tests must pass, including inherited M2 auth tests.
2. **Run full frontend test suite** (`npm run test` in `frontend/`) — all tests must pass.
3. **Verify the deferred M2 acceptance criterion**: anonymous user creates health data → converts to permanent account → health data remains accessible under the same `user_id`.
4. **Manually verify** via the frontend: add at least one condition, symptom, medication, allergy, and goal; reload the page; confirm data persists.
5. **Verify isolation manually**: confirm that a different authenticated user cannot reach the first user's health data.
6. **No known critical failures** remain before proceeding to Milestone 4.

---

## Explicit Boundaries

### DO in Milestone 3

- Introduce PostgreSQL tables for all entities listed above
- Implement standard CRUD REST endpoints
- Enforce patient-level authorization on every endpoint
- Add `source_type` stub column (M6 will add full provenance)
- Add temporal fields (`started_at`, `ended_at`, `recorded_at`)
- Write automated tests for all domain behavior and isolation

### DO NOT in Milestone 3

- Introduce pgvector or vector indexes (Phase 2)
- Implement document upload or storage (Milestone 4)
- Implement health timeline events (Milestone 5)
- Implement full provenance (source_id, verification_state) (Milestone 6)
- Introduce AI, RAG, embeddings, or chat (Phase 2)
- Introduce Redis, background workers, or queues
- Introduce clinician workflows
- Build a multi-patient (caregiver) model
- Introduce complex UI frameworks or design libraries — keep UI functional
- Expose a provenance/source selector in any UI — `source_type` is always `PATIENT_REPORTED` for M3-created data and must not be settable by the user

---

## Verification Plan

### Automated Tests

```bash
# Backend
cd backend
pytest tests/ -v

# Frontend
cd frontend
npm run test
```

### Manual Verification Checklist

```
□ Application starts (frontend + backend + PostgreSQL)
□ Anonymous session auto-established on first visit
□ Health Profile form: fill demographics → save → reload → data persists
□ Conditions: add → verify listed → edit → verify updated → delete → verify gone
□ Medications: same lifecycle
□ Symptoms: same lifecycle
□ Allergies: same lifecycle
□ Goals: same lifecycle
□ Convert anonymous to permanent → all health data still visible
□ Second browser (different user) cannot access first user's data
□ Backend linting passes: ruff check backend/
□ Frontend linting passes: npm run lint in frontend/
```
