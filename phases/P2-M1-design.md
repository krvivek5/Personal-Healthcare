# Phase 2 — Milestone 1: Technical Design

> **Status**: COMPLETE & LOCKED (2026-09-14)  
> **All Slices (1–7)**: LOCKED  

## 1. Design Goal

The technical goal of Milestone 1 (M1) is to build the minimal, robust, end-to-end service and API pipeline for **Structured Personal Health Inquiry**.

Specifically, M1 must solve:
1. **Authenticated Context Assembly**: Fetching and assembling an authenticated user's structured health records across Phase 1 relational tables (`health_profiles`, `conditions`, `medications`, `allergies`, `symptoms`, `patient_goals`, and `timeline`) within a safe database-session lifecycle.
2. **Grounded Inference with Boundary Enforcement**: Sending the inquiry and assembled context to a language model with strict prompt boundaries:
   - Patient-specific factual assertions must be grounded *exclusively* in the supplied structured records.
   - General medical knowledge is permitted *only* for natural language comprehension and predefined safety guardrails, and must not be presented as patient-specific fact.
3. **Server-Owned Evidence Sufficiency**: Establishing evidence truth on the backend. The backend owns whether a patient-specific record or field exists; the model is responsible for language understanding and response synthesis.
4. **Data-Faithful Temporal Discrimination**: Distinguishing between active/current items and historical/discontinued/resolved records based strictly on schema attributes without clinical over-interpretation.
5. **Predefined Pattern-Based Safety Guardrails**: Recognizing acute symptom patterns deterministically and returning a standardized non-diagnostic safety advisory, without performing clinical triage, clinical severity scoring, or medical diagnosis.
6. **Structured Provenance Tracking**: Associating factual claims in the response with concrete structured record identifiers (`entity_type`, `record_id`, `label`, `verification_state`), explicitly distinguishing server-verified citation validity from semantic claim grounding.
7. **Strict Tenant Isolation**: Ensuring zero cross-tenant data leakage by enforcing authenticated `user_id` $\to$ `patient_id` scoping at every step of retrieval, inference, and citation validation.

M1 achieves this without requiring document OCR, PDF parsing, text chunking, embeddings, vector databases, multi-turn agent frameworks, or clinical decision engines.

---

## 2. Existing Phase 1 Interfaces and Data

The M1 design builds directly upon existing, verified Phase 1 models, service layers, and authorization mechanisms:

### 2.1 Database Models (`backend/app/db/models.py`)
All health data is partitioned by `patient_id` (UUID foreign key referencing `patients.id` with `CASCADE` delete):

| Model | Table | Key Fields Relevant to Inquiry | Temporal Fields | Provenance Fields |
| :--- | :--- | :--- | :--- | :--- |
| `Patient` | `patients` | `id`, `user_id` | `created_at`, `updated_at` | N/A |
| `HealthProfile` | `health_profiles` | `date_of_birth`, `biological_sex`, `height_cm`, `blood_group`, `notes` | `updated_at` | N/A |
| `Condition` | `conditions` | `name`, `status` (`active` \| `resolved`), `is_chronic`, `notes` | `started_at`, `ended_at`, `recorded_at` | `source_type`, `source_id`, `verification_state` |
| `Medication` | `medications` | `name`, `dosage`, `frequency`, `status` (`active` \| `stopped`), `as_needed`, `notes` | `started_at`, `ended_at`, `recorded_at` | `source_type`, `source_id`, `verification_state` |
| `Allergy` | `allergies` | `allergen`, `reaction`, `severity` (`mild` \| `moderate` \| `severe` \| `life_threatening`), `notes` | `recorded_at` *(No status or end date)* | `source_type`, `source_id`, `verification_state` |
| `Symptom` | `symptoms` | `name`, `severity` (`mild` \| `moderate` \| `severe`), `notes` | `started_at`, `ended_at`, `recorded_at` | `source_type`, `source_id`, `verification_state` |
| `PatientGoal` | `patient_goals` | `description`, `status` (`active` \| `achieved` \| `abandoned`), `target_date`, `notes` | `recorded_at` | `source_type`, `source_id`, `verification_state` |
| `MedicalDocument` | `medical_documents` | `file_name`, `display_name`, `document_type`, `file_size_bytes`, `notes` | `document_date`, `uploaded_at` | `source_type`, `verification_state` |

*(Note: In M1, `MedicalDocument` file contents and internal `storage_key` are explicitly out of scope. Document text extraction and RAG are excluded).*

### 2.2 Health Service Layer (`backend/app/health/`)
Phase 1 encapsulates queries behind async service functions that accept `(db: AsyncSession, patient_id: uuid.UUID)`:
* `get_health_profile(db, patient_id)` (`app.health.profile`)
* `get_conditions(db, patient_id)` (`app.health.conditions`)
* `get_medications(db, patient_id)` (`app.health.medications`)
* `get_allergies(db, patient_id)` (`app.health.allergies`)
* `get_symptoms(db, patient_id)` (`app.health.symptoms`)
* `get_goals(db, patient_id)` (`app.health.goals`)
* `get_timeline(db, patient_id)` (`app.health.timeline`) — dynamically synthesizes timeline events with `event_state` (`current` | `historical` | `neutral`).
* `get_or_create_patient(db, user_id)` (`app.health.patient`) — bridges Supabase JWT `user_id` to database `patient_id`.

### 2.3 Authentication & User Context (`backend/app/core/auth.py`)
* `get_current_user` validates the Supabase ES256 Bearer JWT against project JWKS and returns an `AuthenticatedUser(id=..., email=..., is_anonymous=..., role=...)`.

### 2.4 Frontend Architecture (`frontend/src/`)
* API client: `frontend/src/lib/api.ts` provides typed fetch wrappers passing `Authorization: Bearer <token>`.
* Workspace container: `frontend/src/components/WorkspaceView.tsx` manages session state, loading, and tab/section rendering.

---

## 3. Query Flow

The end-to-end request flow for an inquiry is structured as follows:

```
[User Query: "What active medications am I taking?"]
                       │
                       ▼
         1. Authentication & Tenant Binding
      - Extract Bearer JWT (FastAPI Depends)
      - Decode & verify claims (sub = user_id)
      - Resolve patient = get_or_create_patient(db, user_id)
                       │
                       ▼
         2. Predefined Safety Pattern Recognition
      - Scan query against predefined acute symptom patterns
      - If matched: flag safety state to attach fixed advisory
      - Strictly no clinical triage or severity assessment
                       │
                       ▼
       3. Structured Context Retrieval & Assembly
      - Execute patient-scoped structured queries (session-safe)
      - Compile in-memory structured context bundle
      - Map data-faithful temporal representations
                       │
                       ▼
         4. Query Understanding (Inquiry Target)
      - Interpret natural-language query into minimal InquiryTarget
      - Identifies target domain/entity, requested attributes, temporal scope, and intent
      - Pure language interpretation; no clinical reasoning or diagnostic logic
                       │
                       ▼
         5. Server-Side Evidence Evaluation
      - Backend evaluates InquiryTarget against patient's actual structured records
      - Authoritatively evaluates record existence, field presence/null state, and temporal state
      - Establishes authoritative evidence status (SUFFICIENT / PARTIAL / INSUFFICIENT)
      - Constrains model generation with verified factual boundaries
                       │
                       ▼
         6. Grounded Inference & Response Synthesis
      - Provide system prompt: strict grounding boundary & evidence constraint
      - Provide structured context bundle + user query + backend evidence directives
      - LLM generates plain-language answer and references supporting citations
                       │
                       ▼
         7. Citation Validity Verification
      - Server validates that cited record IDs exist and belong to user
      - Strip or reject any invalid or cross-tenant citation
      - Document semantic entailment boundary
                       │
                       ▼
         8. Final Response Serialization
      - Construct HealthInquiryResponse (answer, evidence_status, citations, safety)
      - Return HTTP 200 JSON payload to client
```

### Distinction Between Deterministic Logic and Model Behavior

| Component | Responsibility | Nature | Implementation Mechanism |
| :--- | :--- | :--- | :--- |
| **Auth & Isolation** | Validating credentials and scoping data to `patient_id` | **Deterministic** | JWT verification + SQL `WHERE patient_id = :id` |
| **Context Retrieval** | Fetching structured records from database tables | **Deterministic** | Session-safe calls via existing Phase 1 SQLAlchemy services |
| **Temporal Representation** | Mapping record state based strictly on schema fields | **Deterministic** | Data-faithful field rules (no clinical extrapolation) |
| **Safety Pattern Recognition** | Recognizing acute symptom phrases | **Deterministic** | Predefined pattern catalog triggering fixed advisory |
| **Query Understanding** | Translating query phrasing into conceptual `InquiryTarget` | **Model-dependent** | General LLM language comprehension and intent mapping |
| **Evidence Truth** | Evaluating `InquiryTarget` against records for existence, nulls, and evidence status | **Deterministic (Backend)** | Server-side inspection of retrieved record set and fields |
| **Response Synthesis** | Formulating plain-language answer within evidence boundary | **Model-dependent** | Grounded prompt-constrained generation |
| **Citation Validity** | Verifying cited records exist and belong to the patient | **Deterministic (Backend)** | Set verification against retrieved patient record IDs |

---

## 4. Structured Context Model

To supply the language model with an unambiguous representation of the user's structured data, M1 uses an in-memory context serializer that compiles Phase 1 models into a standardized JSON representation.

No new database tables or persistent storage are introduced.

### Domain Representation

```json
{
  "profile": {
    "date_of_birth": "1985-04-12",
    "biological_sex": "male",
    "blood_group": "O+",
    "height_cm": 178.0,
    "notes": "No personal notes"
  },
  "conditions": [
    {
      "id": "c1a2b3c4-...",
      "name": "Asthma",
      "status": "active",
      "is_chronic": true,
      "started_at": "2021-03-15",
      "ended_at": null,
      "temporal_state": "current",
      "verification_state": "PATIENT_REPORTED",
      "notes": "Triggered by cold air"
    }
  ],
  "medications": [
    {
      "id": "m1a2b3c4-...",
      "name": "Lisinopril",
      "dosage": "10mg",
      "frequency": "Once daily",
      "status": "active",
      "as_needed": false,
      "started_at": "2023-01-10",
      "ended_at": null,
      "temporal_state": "current",
      "verification_state": "SOURCE_RECORDED",
      "notes": null
    },
    {
      "id": "m2b3c4d5-...",
      "name": "Amoxicillin",
      "dosage": "500mg",
      "frequency": "Three times daily",
      "status": "stopped",
      "as_needed": false,
      "started_at": "2023-06-01",
      "ended_at": "2023-06-10",
      "temporal_state": "historical",
      "verification_state": "PATIENT_REPORTED",
      "notes": "10-day course completed"
    }
  ],
  "allergies": [
    {
      "id": "a1a2b3c4-...",
      "allergen": "Penicillin",
      "reaction": "Hives and swelling",
      "severity": "severe",
      "recorded_at": "2022-05-14T10:30:00Z",
      "temporal_state": "recorded_entry",
      "verification_state": "PATIENT_REPORTED",
      "notes": "Reaction in childhood"
    }
  ],
  "symptoms": [
    {
      "id": "s1a2b3c4-...",
      "name": "Dry Cough",
      "severity": "mild",
      "started_at": "2024-02-01",
      "ended_at": null,
      "temporal_state": "ongoing",
      "verification_state": "PATIENT_REPORTED",
      "notes": "Worse in evenings"
    }
  ],
  "goals": [
    {
      "id": "g1a2b3c4-...",
      "description": "Lower resting heart rate below 70 bpm",
      "status": "active",
      "target_date": "2024-12-31",
      "temporal_state": "current"
    }
  ],
  "recent_timeline_events": [
    {
      "event_date": "2023-06-10",
      "event_type": "MEDICATION_STOPPED",
      "event_state": "historical",
      "title": "Amoxicillin",
      "source_type": "MEDICATION",
      "source_id": "m2b3c4d5-..."
    }
  ]
}
```

---

## 5. Context Retrieval Strategy

### Evaluation of Options for M1

1. **Option A: Query-Routed Deterministic Domain Filtering**
   - *Concept*: Inspect user query with keywords (e.g., "medication", "drug" $\to$ query only `medications`).
   - *Limitation*: Highly brittle. A question like "Does my blood pressure medicine cause my cough?" spans both `medications` and `symptoms`. Routing misclassifications silently starve the model of necessary context.
2. **Option B: Vector Search / Embedding RAG**
   - *Concept*: Chunk records, generate embeddings, store in a vector database, and retrieve top-$k$.
   - *Limitation*: Unnecessary architectural complexity for structured relational data, non-deterministic recall, cannot reliably establish negative record absence, and introduces dependencies explicitly deferred by the Phase 2 charter.
3. **Option C: Direct Structured Bundle Assembly (Selected for M1)**
   - *Concept*: Query the structured domain tables for the authenticated `patient_id` directly to assemble a complete representation of the selected structured domains.
   - *Advantage*: Provides complete retrieval of the patient's structured health records for M1, eliminates query-routing failure, ensures negative lookups (confirming an entity does not exist) are reliable, and introduces no external vector dependencies.

### Database Session Execution Strategy
In SQLAlchemy, concurrent execution of multiple queries across a single shared `AsyncSession` is unsafe. Therefore, the context assembly service will perform reads sequentially or via a scoped multi-entity loader within the existing database session lifecycle:
* Load `HealthProfile`, `conditions`, `medications`, `allergies`, `symptoms`, `patient_goals`, and timeline events sequentially using the established service functions.
* The exact query grouping and session lifecycle will be verified during implementation without inventing artificial performance benchmarks.

---

## 6. Temporal State Resolution

Temporal state must be resolved using actual Phase 1 schema attributes rather than clinical heuristics. Each record is tagged deterministically before model serialization:

| Domain | Phase 1 Schema Fields | Rule for `current` / Active | Rule for `historical` / Inactive | Data-Faithful Semantic Constraint |
| :--- | :--- | :--- | :--- | :--- |
| **Conditions** | `status: str`, `ended_at: Optional[date]` | `status == "active"` AND `ended_at is None` | `status == "resolved"` OR `ended_at is not None` | Based strictly on recorded `status` and `ended_at`. |
| **Medications** | `status: str`, `ended_at: Optional[date]` | `status == "active"` AND (`ended_at is None` OR `ended_at >= today`) | `status == "stopped"` OR (`ended_at is not None` AND `ended_at < today`) | Distinguishes current regimen from stopped/past medication. |
| **Symptoms** | `started_at`, `ended_at: Optional[date]` | `ended_at is None` (`ongoing`) | `ended_at is not None` (`resolved`) | `ended_at` absence indicates ongoing symptom report. |
| **Allergies** | `recorded_at: datetime` | *N/A (Recorded Entry)* | *N/A (Recorded Entry)* | **Data-Faithful Rule**: The Phase 1 schema contains no `status` or resolution date. An allergy is represented strictly as a recorded entry at `recorded_at`. The system must **not** clinically assume active permanence or infer resolution. |
| **Goals** | `status: str` | `status == "active"` | `status in ("achieved", "abandoned")` | Based strictly on recorded `status`. |
| **Timeline** | `event_state: str` | `event_state == "current"` | `event_state == "historical"` | Synthesized by Phase 1 timeline service (`neutral` preserved for dated records). |

---

## 7. Evidence Sufficiency

### Core Principle
> **"The backend owns evidence truth; the LLM owns language synthesis."**

The model must never be the authoritative decision-maker on whether a patient-specific record or fact exists in the database. Instead, the architecture establishes an explicit boundary:

$$\text{User Question} \longrightarrow \text{Query Understanding} \longrightarrow \text{Structured Inquiry Target} \longrightarrow \text{Server-Side Evidence Evaluation} \longrightarrow \text{Grounded Response Synthesis}$$

### 7.1 Query-Understanding Contract (`InquiryTarget`)

The model interprets natural-language phrasing into a minimal conceptual `InquiryTarget` containing only what is necessary for the backend to evaluate evidence against the database:

```python
class InquiryTarget(BaseModel):
    target_domain: Optional[str] = None  # e.g. "medications", "conditions", "allergies", "profile", "symptoms", "goals"
    target_entity: Optional[str] = None  # e.g. "Lisinopril", "Asthma", "Penicillin", "blood_group"
    requested_attributes: list[str] = []  # e.g. ["dosage", "frequency"], ["started_at"], ["blood_group"]
    temporal_scope: str = "all"  # "current" | "historical" | "all"
    question_intent: str = "QUERY"  # "VERIFY_PRESENCE" | "GET_ATTRIBUTE" | "LIST_ITEMS" | "QUERY"
```

#### Boundary Rules:
* **Language Interpretation (Model)**: The model maps user phrasing (e.g., *"What blood pressure medication do I take and what's my dose?"*) to an `InquiryTarget(target_domain="medications", requested_attributes=["name", "dosage"], temporal_scope="current", question_intent="LIST_ITEMS")`.
* **Evidence Authority (Server)**: The backend validates the `InquiryTarget` against the authenticated patient's actual structured records and remains authoritative over:
  - **Record existence**: Whether matching records exist in the database.
  - **Field presence / null state**: Whether the requested attributes are populated or `null` in the record.
  - **Temporal state**: Whether matching records are active or historical according to schema attributes.
  - **Evidence status**: The backend deterministically assigns `SUFFICIENT`, `PARTIALLY_SUFFICIENT`, or `INSUFFICIENT`.
* **Strictly Non-Clinical**: This contract strictly avoids clinical reasoning, diagnosis, treatment logic, triage, or medical decision-making. It functions solely as a structured bridge between natural-language comprehension and relational database truth.

### 7.2 Server-Owned Evidence States

1. **`SUFFICIENT`**:
   - The user's inquiry concerns entities or attributes that are affirmatively present and populated in the structured records.
   - *Example*: User asks *"What is my dosage of Lisinopril?"* and context contains `Lisinopril` with `dosage="10mg"`.
2. **`PARTIALLY_SUFFICIENT`**:
   - The requested entity exists, but specific queried attributes are `null` or unrecorded in the schema.
   - *Example*: User asks *"When was my asthma diagnosed and what clinic diagnosed it?"* Records contain `Asthma` with `started_at="2021-03-15"`, but the database contains no clinic field. The backend recognizes the missing field and enforces that the answer reports the date while explicitly stating the clinic is unrecorded.
3. **`INSUFFICIENT`**:
   - The requested domain is empty, or the specific entity asked about is absent from the user's records.
   - *Example 1*: User asks *"What is my blood type?"* and `health_profile.blood_group` is `null`. The backend identifies that `blood_group` is missing.
   - *Example 2*: User asks *"Do I have a peanut allergy?"* and `allergies` contains zero records matching peanuts.
   - *Rule*: The system must **never** turn absence of evidence into a clinical or negative patient fact. It must never state *"You do not have a peanut allergy"*. The backend enforces the formulation: *"Your health records do not contain any recorded allergy to peanuts."*

### 7.3 Backend Enforcement Mechanism
- The backend evaluates the `InquiryTarget` against the patient's records to establish the factual baseline.
- If a target domain is empty, a queried entity is missing, or an attribute is null, the backend injects an explicit evidence directive into the prompt: e.g., `Evidence Notice: blood_group is NULL. You must state that the user's records do not contain a blood type.`
- The final `evidence_status` enum in the API response contract is deterministically governed by the server's evaluation of the user's records.

---

## 8. Provenance Contract

### Distinguishing Citation Validity from Claim Grounding

The design explicitly differentiates two distinct layers of provenance:

1. **Citation Validity (Server-Enforced Deterministically)**:
   - Verifies that every citation emitted in the response points to a `record_id` that actually exists in the database, belongs to the authenticated patient, and matches the declared `entity_type`.
   - Any citation referencing a non-existent ID or an ID belonging to another user is rejected or stripped server-side.
2. **Claim Grounding (Prompt-Enforced & Evaluation-Validated)**:
   - Ensures that the natural-language claim made in the text is factually supported by the attributes of the cited record (e.g., claiming "Lisinopril 10mg" is supported by a medication record with that dosage).
   - *M1 Pragmatic Boundary*: M1 does not introduce an automated theorem-proving or NLI (Natural Language Inference) semantic entailment engine. Instead, claim grounding is constrained by strict prompt instructions, low-temperature generation, and offline test-suite evaluations.
   - *Documented Limitation*: Server-side citation validation confirms record ownership and existence, but does not mathematically prove semantic entailment in real time.

### Provenance Object Schema

```python
class InquiryCitation(BaseModel):
    citation_id: int  # Sequential reference number matching inline tags [cit:1]
    entity_type: str  # CONDITION | MEDICATION | ALLERGY | SYMPTOM | GOAL | PROFILE | TIMELINE_EVENT
    record_id: uuid.UUID  # Primary key UUID of the database record
    label: str  # Human-readable label: e.g. "Medication: Lisinopril 10mg"
    verification_state: str  # PATIENT_REPORTED | SOURCE_RECORDED
```

### Inline Citation Format
In the generated markdown answer, claims will reference citations using bracketed tokens, e.g.:
> *"You have a recorded diagnosis of Asthma [cit:1] and are currently taking Lisinopril 10mg once daily [cit:2]."*

### Client Integration
The frontend can parse `[cit:N]` tags to render interactive provenance badges (using the existing `ProvenanceBadge.tsx` component in `frontend/src/components/`), enabling users to inspect the underlying record.

---

## 9. Safety Guardrail Boundary

The safety layer is a protective guardrail, **not** a clinical triage engine.

### Core Architectural Separation
The design strictly separates:
* **Predefined Acute-Symptom Pattern Recognition** (Deterministic keyword and regex matching)
FROM
* **Clinical Interpretation, Severity Assessment, Triage, Diagnosis, or Treatment Decisions** (Strictly Prohibited)

### Invariant Prohibitions
1. **No Clinical Triage**: The system will not classify or sort users into emergency triage tiers (e.g., ESI level, urgency categories).
2. **No Severity Scoring**: The system will not calculate or display clinical risk scores.
3. **No Diagnosis**: The system will not interpret symptoms or issue diagnostic conclusions.
4. **No Treatment Decisions**: The system will never recommend starting, stopping, or altering medications or therapies.

### Safety Flow

```
[User Query]
     │
     ▼
[Predefined Pattern Recognition]
(Deterministic scan for acute presentation phrases:
 e.g. crushing chest pain, sudden unilateral weakness,
 severe respiratory distress, acute anaphylaxis signs)
     │
     ├─── If Matched ───► [Attach Fixed, Non-Diagnostic Safety Advisory]
     │                    - Advises seeking professional medical care
     │                    - Safety flag set to triggered=True
     │                    - Constrains model against clinical speculation
     │
     └─── If No Match ──► [Standard Grounded Inquiry Flow]
```

### Fixed Safety Advisory
When a pattern is triggered, a conservative, standardized advisory is returned:
> *"⚠️ Safety Notice: Your inquiry mentions symptoms that may require prompt medical evaluation. Please seek professional medical care. If you believe this may be an emergency, contact your local emergency services. This system does not assess symptom severity, perform clinical triage, or provide medical diagnoses."*

This fixed advisory strictly avoids automated urgency classification or clinical grading. It operates solely as a predefined conservative safety notice triggered by pattern recognition.

---

## 10. Response Contract

The API endpoint will be exposed at `POST /api/v1/health-inquiry`.

### Request Schema

```python
class HealthInquiryRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=2,
        max_length=1000,
        description="The user's natural language health question."
    )
```

### Response Schema

```python
class EvidenceStatus(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    PARTIALLY_SUFFICIENT = "PARTIALLY_SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"


class InquiryCitation(BaseModel):
    citation_id: int
    entity_type: str
    record_id: uuid.UUID
    label: str
    verification_state: str


class SafetyGuardrailState(BaseModel):
    triggered: bool
    advisory_message: Optional[str] = None


class HealthInquiryResponse(BaseModel):
    query: str
    answer: str
    evidence_status: EvidenceStatus
    citations: list[InquiryCitation]
    safety: SafetyGuardrailState
    generated_at: datetime
```

---

## 11. Tenant Isolation

Tenant isolation is guaranteed by construction through existing Phase 1 authorization patterns:

1. **Authentication Dependency**:
   - The route depends on `current_user: AuthenticatedUser = Depends(get_current_user)`.
   - Rejects unauthenticated requests with HTTP 401.
2. **Identity Bridge**:
   - Maps `current_user.id` to `patient = await get_or_create_patient(db, current_user.id)`.
   - The resulting `patient.id` is the immutable tenant key for all subsequent operations.
3. **Database Query Isolation**:
   - Every fetch operation strictly filters by `Model.patient_id == patient.id`.
   - No cross-patient queries exist.
4. **Context Boundary**:
   - Only records returned from the patient-scoped queries are serialized into the model prompt.
5. **Post-Generation Citation Validation**:
   - Before returning the response, the backend verifies that every `record_id` in `citations` exists in the set of IDs retrieved for that `patient_id`.
   - Any foreign ID is stripped immediately, preventing cross-tenant leakage even in the event of model hallucination.

---

## 12. Evaluation Strategy

To ensure implementation readiness and prevent regressions, M1 requires automated validation across 7 core test categories:

| Category | Test Objective | Representative Test Scenario |
| :--- | :--- | :--- |
| **1. Grounding & Entailment** | Personal assertions are supported by existing database records | User asks *"What conditions do I have?"* $\to$ response includes only Asthma, matching `conditions` record. |
| **2. Hallucination Prevention** | System does not fabricate unrecorded values | User asks *"What is my dosage of Lisinopril?"* when dosage field is null $\to$ response states dosage is not specified; does not guess standard 10mg. |
| **3. Citation Validity** | Returned citation IDs match authoritative DB records | Response asserts Lisinopril $\to$ `citations` contains exact UUID of user's `Medication` record with `entity_type="MEDICATION"`. |
| **4. Temporal Correctness** | Correct discrimination of active vs stopped/resolved | User asks *"What medications am I taking?"* $\to$ lists Lisinopril (active), omits or explicitly qualifies Amoxicillin (stopped in past). |
| **5. Insufficient Evidence** | Absent records are acknowledged as unrecorded | User asks *"What is my cholesterol level?"* (no lab records exist) $\to$ `evidence_status="INSUFFICIENT"`, answer states records contain no cholesterol data. |
| **6. Safety Boundary** | Acute symptoms trigger safety advisory without triage | User asks *"Severe chest pain and jaw pain, should I take aspirin?"* $\to$ `safety.triggered=True`, fixed safety advisory returned; zero triage tiers, urgency scores, or treatment recommendations. |
| **7. Tenant Isolation** | Zero data accessible across different user accounts | User A has diabetes record; User B has no records. User B queries *"Do I have diabetes?"* $\to$ User B receives insufficient evidence response, zero mention of User A's data. |

---

## 13. Technical Decisions

### Decision 1: Direct Context Bundle vs Vector Retrieval (RAG)
* **Decision**: Assemble structured records directly into an in-memory context bundle for M1.
* **Rationale**: Direct structured assembly provides complete retrieval of the selected structured domains for the authenticated patient in M1, eliminates query-routing errors, and avoids premature vector dependencies.
* **Alternatives Considered**: pgvector embeddings over structured records; keyword query router.
* **Why Preferred**: Vector indexing is unnecessary for structured records and cannot reliably prove negative absence; query routing is brittle.

### Decision 2: Server-Owned Evidence Truth
* **Decision**: The backend evaluates record presence and field completeness; the LLM is constrained by backend-determined evidence boundaries.
* **Rationale**: The language model is not an authoritative database engine. If a field or record is missing, the backend must guarantee this absence is treated as unrecorded, preventing the model from hallucinating or asserting negative clinical facts.
* **Alternatives Considered**: Allowing the LLM to freely determine evidence sufficiency.
* **Why Preferred**: LLM evidence categorization is non-deterministic and prone to over-interpreting absence of evidence.

### Decision 3: Data-Faithful Allergy Representation
* **Decision**: Allergies are represented strictly as recorded observations at `recorded_at` without inventing clinical active/resolved temporal states.
* **Rationale**: The Phase 1 schema does not contain an active/resolved status or end date for allergies. Transforming database absence into clinical permanence would violate data faithfulness.
* **Alternatives Considered**: Defaulting all allergies to "active".
* **Why Preferred**: Reflects the actual schema truthfully without clinical overreach.

### Decision 4: Citation Validity Verification (Pragmatic Provenance)
* **Decision**: Enforce citation validity deterministically server-side, while validating claim grounding through prompt constraints and test evaluations.
* **Rationale**: Provides verifiable provenance links without building a complex real-time semantic entailment engine in M1.
* **Alternatives Considered**: Real-time NLI claim verification.
* **Why Preferred**: An NLI engine is computationally heavy and outside M1 scope.

### Decision 5: Predefined Pattern Recognition for Safety Guardrails
* **Decision**: Trigger safety advisories via deterministic pattern recognition of acute symptoms, delivering a fixed non-diagnostic advisory.
* **Rationale**: Guarantees safety guardrail activation without introducing clinical triage, severity scoring, or medical diagnosis.
* **Alternatives Considered**: LLM-based triage or clinical classification.
* **Why Preferred**: Violates the Phase 2 charter safety boundaries.

---

## 14. Explicit Non-Goals

For complete clarity, Milestone 1 explicitly excludes:
* **Medical-Document Content Retrieval**: No parsing, reading, chunking, or querying of uploaded document files or images.
* **OCR & PDF Extraction**: No text extraction pipelines.
* **Embeddings & Vector Databases**: No vector stores, embedding models, or vector similarity search.
* **Multi-Turn Conversational Memory**: No conversational dialogue history, session threads, or conversational memory stores.
* **Autonomous Agents & Tool Execution**: No background agents, tool calling, or multi-agent orchestration.
* **Proactive Monitoring**: No scheduled checks, automated push notifications, or anomaly alerts (Phase 3).
* **Wearable Integrations**: No Apple Health, Google Fit, or continuous IoT streaming.
* **Clinical Decision Support (CDS)**: No clinical guideline matching, drug-drug interaction engines, or diagnostic suggestions.
* **Autonomous Actions**: No booking appointments, emailing clinics, or transmitting data.
* **External Medical Web Search**: No live web search.

---

## 15. Implementation Readiness

### 15.1 Locked Decisions
- [x] Scope of personal health context is strictly Phase 1 structured relational records.
- [x] Medical document file/text contents are completely excluded from M1.
- [x] Direct structured bundle assembly provides complete retrieval of selected structured domains.
- [x] Backend owns evidence truth; LLM owns language synthesis.
- [x] Allergies are represented data-faithfully as recorded point-in-time entries.
- [x] Provenance citation validity is verified deterministically server-side.
- [x] Safety guardrail uses predefined pattern recognition with a fixed non-diagnostic advisory (not a clinical triage engine).
- [x] Tenant isolation is enforced via Supabase JWT `user_id` $\to$ `patient_id` binding.

### 15.2 Implementation-Dependent Decisions Requiring Clarification
1. **Database Session Query Execution Pattern**: Determining whether structured reads are performed via sequential async queries or a unified query helper to ensure `AsyncSession` safety without session concurrency conflicts.
2. **LLM Provider Choice for Development**: Which provider/model API key will be configured in `.env` for development and manual testing (e.g., OpenAI, Anthropic, or Gemini)?
3. **Frontend UI Placement**: Determining whether the inquiry interface is placed as a top-level search/query bar inside `WorkspaceView.tsx` or as a distinct section within the workspace layout.

### 15.3 Dependencies & Blockers
* **No Blockers**: All database models, migrations, auth dependencies, and service layers required for M1 already exist and are tested in the Phase 1 codebase.

### 15.4 Recommended Implementation Order
1. **Inquiry Schemas (`backend/app/schemas/inquiry.py`)**: Define `HealthInquiryRequest`, `HealthInquiryResponse`, `InquiryCitation`, and `EvidenceStatus`.
2. **Context Assembly Service (`backend/app/health/inquiry_context.py`)**: Implement session-safe service to gather and serialize patient structured data with data-faithful temporal tags.
3. **Query Understanding & Evidence Evaluation Logic (`backend/app/health/inquiry_evidence.py`)**: Implement `InquiryTarget` schema contract and backend evaluation for record presence, temporal scope, and null fields.
4. **Safety Rule Engine (`backend/app/health/safety_guardrails.py`)**: Implement predefined acute pattern recognition and fixed advisory messages.
5. **Inference Provider Interface (`backend/app/core/llm.py`)**: Implement protocol, prompt template, and mock provider for unit tests.
6. **API Endpoint (`backend/app/api/inquiry.py`)**: Wire query flow into `POST /api/v1/health-inquiry` with tenant isolation and citation validation.
7. **Backend Test Suite (`backend/tests/api/test_inquiry.py`)**: Validate all 7 evaluation categories with automated tests.
8. **Frontend API Client & Component (`frontend/src/lib/api.ts`, `frontend/src/components/HealthInquiryView.tsx`)**: Expose the single-turn query form and render grounded answers with provenance badges and safety notices.
