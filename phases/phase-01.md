# Phase 1 — Personal Health Foundation

## Purpose

Build the foundational personal health experience that allows a user to create, store, and review their own health context in one place.

This phase establishes the foundation on which future AI health intelligence will operate.

The goal is **not** to build the complete AI healthcare companion yet.

---

# 1. WHAT We Are Building

A secure personal health space where a user can:

1. Create an account.
2. Create and maintain a basic personal health profile.
3. Enter important health information.
4. Upload medical documents.
5. View their health information in an organized way.
6. See a chronological view of important health events.
7. Clearly understand where each piece of health information came from.

At the end of Phase 1, the user should already have a useful **personal health record foundation**, even without AI chat.

---

# 2. WHY We Are Building It

Our product is not fundamentally a chatbot.

The core product is a **Personal Health Intelligence** system that becomes useful because it understands the individual's health context over time.

Therefore, before adding sophisticated AI, we need reliable personal health context.

The Phase 1 outcome should be:

> **“My important health information is organized in one place, and I can see my health story over time.”**

This creates the foundation for the next phase:

> Personal Health Data → Personal Health Model → AI Understanding.

---

# 3. Phase Boundary

## IN

* Authentication
* User/patient profile
* Basic health information
* Conditions
* Medications
* Allergies
* Symptoms / health concerns
* Health events
* Medical document upload
* Document metadata
* Basic extraction/storage where practical
* Source/provenance information
* Health timeline
* Secure user-specific data access
* Automated tests

## OUT

Do not implement these in Phase 1:

* AI health chat
* Advanced RAG
* Personalized AI reasoning
* Proactive health insights
* Wearable integrations
* EHR/EMR integrations
* ABDM integration
* Doctor marketplace
* Appointment booking
* Clinical decision support
* Autonomous diagnosis
* Autonomous treatment recommendations

Do not expand Phase 1 into these areas unless explicitly requested.

---

# 4. Core Product Concepts

The system should establish these concepts from the beginning.

## Patient

The person whose health information is being managed.

## Health Information

Examples:

* Conditions
* Symptoms
* Medications
* Allergies
* Health measurements
* Health concerns
* Important medical events

## Medical Document

Examples:

* Lab report
* Prescription
* Diagnostic report
* Discharge summary
* Medical record

The original document should remain available as the source material.

## Health Event

A meaningful event associated with a point or period in time.

Examples:

* Symptom started
* Doctor visit
* Medication started
* Medication stopped
* Lab test
* Diagnosis recorded

## Source

Every important health fact should have an identifiable origin where possible.

Possible origins include:

* Patient entered
* Uploaded document
* Imported record
* Clinician confirmed

The system must not treat AI-generated information as equivalent to source medical information.

---

# 5. Milestones

## Milestone 1 — Project Foundation

### WHAT

Create the application foundation and establish the project structure.

### WHY

We need a stable base before introducing health-data functionality.

### Acceptance Criteria

* Application runs locally.
* Codebase has clear module boundaries.
* Basic development and test commands work.
* Linting/formatting is configured.
* Environment configuration is documented.
* Automated test suite can be executed successfully.

### Validation

Run the project and test suite before continuing.

**Do not proceed if the baseline is broken.**

---

# Milestone 2 — Progressive Identity & User Isolation

### WHAT

Users can immediately begin using the product via an anonymous authenticated session, access only their own user-scoped workspace, and later progressively convert to a permanent account without losing their existing account identity.

### WHY

User isolation is a foundational requirement, not a later enhancement. At the same time, an anonymous-first approach reduces initial friction by granting immediate product access, while preserving the user's account identity seamlessly when they eventually choose to create a permanent account for recovery or cross-device access.

### Acceptance Criteria

* Opening the application establishes an anonymous authenticated session automatically if no active session exists.
* The user can immediately enter the product and reach the personal health workspace without an upfront registration wall.
* Authenticated requests (both anonymous and permanent) are protected and validated by the backend.
* Progressive account conversion uses Supabase's supported anonymous-to-permanent identity linking/conversion flow. The original authenticated `user_id` is preserved with no loss of existing account-scoped data. The user-to-patient association will be established and validated in Milestone 3.
* User isolation is strictly enforced: one user cannot access another user's data (whether anonymous or permanent).
* Unauthorized and unauthenticated access is rejected.
* Session clearing behavior:
  - Permanent users can sign out normally.
  - Anonymous users must not be led to believe their anonymous workspace is recoverable after sign-out or session loss.
  - Any app-provided action that clears an anonymous session must require explicit user intent and warn that the anonymous workspace cannot be recovered. Unintentional external session loss (such as browser storage clearing) cannot be prevented.
  - If a new anonymous session is created afterward, it must receive a new isolated identity.
* Anonymous sign-in must include appropriate abuse protection (for example CAPTCHA and/or rate limiting where required). Do not build a large anti-abuse system in Phase 1.
* Tests cover anonymous session establishment, backend token verification, user isolation, and progressive account conversion preserving the user identity.

### Validation

Test at minimum:

```text
Anonymous session → user_id A
→ convert to permanent identity
→ user_id remains A

Anonymous User A → can access Anonymous User A data
Anonymous User B → can access Anonymous User B data
Anonymous User A → cannot access Anonymous User B's data
Permanent User A → cannot access Permanent User B's data
Unauthenticated user → cannot access protected data
```

Do not continue until these tests pass.

---

# Milestone 3 — Personal Health Profile

### WHAT

Allow the user to create and manage their basic health profile.

Initial information may include:

* Basic demographics
* Conditions
* Allergies
* Medications
* Symptoms / ongoing concerns
* Health goals where appropriate

### WHY

This is the first representation of the individual's personal health context.

### Acceptance Criteria

A user can:

* Add health information.
* View health information.
* Edit health information.
* Remove health information where appropriate.
* See information associated only with their account.

Health information should have clear status/source information where applicable.

### Validation

Test:

```text
Create → Read → Update → Delete
```

for supported health entities.

Test user isolation again after introducing health-data storage.

---

# Milestone 4 — Medical Documents

### WHAT

Allow users to upload and securely store medical documents.

Initial target:

* PDF
* Common document formats supported by the chosen product approach

Store useful metadata such as:

* Document name
* Type
* Upload time
* Owner
* Source/status

### WHY

Medical documents are one of the primary sources from which the future Personal Health Model will be built.

The original document must remain available as evidence.

### Lightweight HOW Guidance

Treat the original document as source material.

Do not make extracted text or embeddings the authoritative health record.

### Acceptance Criteria

A user can:

* Upload a document.
* See uploaded documents.
* Access their own documents.
* Remove documents where supported.
* Not access another user's documents.

### Validation

Test:

```text
Upload succeeds
Stored document can be retrieved
Correct user ownership is enforced
Unauthorized access fails
Invalid uploads are handled safely
```

Test after each meaningful document-processing change.

---

# Milestone 5 — Health Timeline

### WHAT

Create a chronological representation of meaningful health events.

Examples:

```text
2026-03-10
Symptom reported

2026-04-02
Blood test

2026-04-10
Medication started

2026-05-18
Doctor visit
```

### WHY

The product is intended to understand a person's health **over time**.

A timeline is therefore part of the product foundation, not merely a future UI feature.

### Lightweight HOW Guidance

Health events should retain meaningful dates and source information.

Avoid storing only the current state when historical changes are important.

### Acceptance Criteria

* Events can be created.
* Events contain relevant dates.
* Events can be linked to their source where applicable.
* Events can be displayed chronologically.
* Historical events remain distinguishable from current state.

### Validation

Create a test patient history containing multiple events at different dates and verify correct ordering and retrieval.

---

# Milestone 6 — Provenance & Data Integrity

### WHAT

Establish a clear distinction between where health information originated.

At minimum support concepts equivalent to:

```text
PATIENT_REPORTED
SOURCE_DOCUMENT
CLINICIAN_CONFIRMED
```

AI-derived states may be introduced later, but the model should leave room for them.

### WHY

The future AI must know whether information is:

* directly provided by the patient,
* recorded in a source document,
* confirmed professionally,
* or later inferred by AI.

This prevents epistemic drift.

### Acceptance Criteria

Important health records identify their source when applicable.

The system does not silently convert inferred or extracted information into confirmed medical facts.

### Validation

Test creation of health information from different sources and verify source metadata is preserved.

---

# 6. Definition of Done

Phase 1 is complete only when all of the following are true:

### Product

* User can create an account.
* User can create and maintain a personal health profile.
* User can add important health information.
* User can upload medical documents.
* User can view their health information.
* User can view a chronological health timeline.
* Health information retains source/provenance information.

### Security

* Authentication works.
* Authorization works.
* User data isolation works.
* Unauthorized health-data access is rejected.

### Engineering

* Automated tests exist for important domain behavior.
* Tests pass.
* No known critical failures remain.
* Code is organized around clear product domains.
* The application runs reliably in the intended development environment.

---

# 7. Mandatory Development Loop

Every mini-feature must follow this loop:

```text
Understand requirement
        ↓
Implement smallest useful change
        ↓
Run relevant tests
        ↓
Fix failures
        ↓
Run broader regression tests
        ↓
Review behavior
        ↓
Proceed to next change
```

Never accumulate multiple untested features before validation.

After every meaningful code change:

1. Run the smallest relevant test set.
2. Fix failures before continuing.
3. Run the broader test suite at milestone boundaries.
4. Do not mark a milestone complete while tests are failing.

---

# 8. Product-Manager Guidance

Prefer the simplest implementation that satisfies the acceptance criteria.

Do not over-engineer Phase 1.

Do not introduce infrastructure, abstractions, services, integrations, or AI capabilities merely because they may be useful in the future.

However, avoid decisions that make the future Personal Health Model, timeline, provenance, or AI context layer difficult to build.

When uncertain, preserve the product boundary and choose the simplest reversible decision.

---

# 9. Expected End State

At the end of Phase 1:

```text
                    USER
                     │
                     ▼
             PERSONAL HEALTH SPACE
                     │
       ┌─────────────┼─────────────┐
       ▼             ▼             ▼
   Health Data    Documents     Timeline
       │             │             │
       └─────────────┼─────────────┘
                     ▼
             PERSONAL HEALTH
                 FOUNDATION
```

This phase does **not** need to demonstrate sophisticated AI.

It needs to establish trustworthy personal health context.

The next phase will build intelligence on top of this foundation.

---

# 10. Agent Operating Rule

Before implementing anything:

1. Read `docs/SPEC.md`.
2. Read `docs/DESIGN.md`.
3. Read this phase specification.
4. Implement only the current milestone.
5. Test immediately after meaningful changes.
6. Do not expand scope without explicit instruction.
7. At the end of the milestone, report:

   * What was implemented.
   * What was tested.
   * Test results.
   * Any deviations from the specification.
   * Any unresolved risks.

Do not begin the next milestone until the current milestone satisfies its acceptance criteria.
