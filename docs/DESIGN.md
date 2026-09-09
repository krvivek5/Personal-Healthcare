# Personal Healthcare Intelligence — Design

## 1. Purpose

This document defines **how the product described in `SPEC.md` should be designed and implemented**.

`SPEC.md` defines **what and why**.

`DESIGN.md` defines **how** the system should realize that product vision.

This document should remain technology-aware but implementation-detail-light enough that individual tasks can evolve without changing the product architecture.

---

## 2. Design Principles

### Personal context first

The system should reason primarily from the user's own health context rather than treating every interaction as an isolated medical question.

### Structured truth + unstructured evidence

Structured health information should be the foundation of the personal health model, while original medical documents remain available as supporting evidence.

### Longitudinal by design

Health information must retain temporal context so the system can understand what changed, when it changed, and how different events relate.

### Traceable AI

Important AI-generated statements should be grounded in identifiable patient information or trusted medical knowledge sources.

### Explicit uncertainty

The system must distinguish known information, patient-reported information, AI inference, and uncertainty.

### Safety before convenience

Healthcare safety decisions must not depend entirely on unconstrained language-model behavior.

### Human control

The patient controls their data and care decisions. Clinicians remain responsible for diagnosis and treatment decisions.

### Modular before distributed

Start with a modular system with clear domain boundaries. Introduce distributed infrastructure only when scale or reliability genuinely requires it.

---

# 3. High-Level Architecture

```text
                    CLIENT APPLICATION
                           │
                           ▼
                    API / APPLICATION
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
     Health Data       AI Experience    Care / Safety
      Services           Services         Services
          │                │                │
          └────────────────┼────────────────┘
                           ▼
                  PERSONAL HEALTH MODEL
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
        Structured      Documents      Timeline
          Health          & Evidence
             │             │             │
             └─────────────┼─────────────┘
                           ▼
                    AI CONTEXT ENGINE
                           │
       ┌───────────────────┼───────────────────┐
       ▼                   ▼                   ▼
 Context Retrieval    Medical Knowledge    Safety Layer
       │                   │                   │
       └───────────────────┼───────────────────┘
                           ▼
                    LLM / AI Reasoning
                           │
                           ▼
                 Grounded AI Response
```

The architecture is centered on the **Personal Health Model**, not the chat interface.

---

# 4. Major System Components

## 4.1 Identity & Access

Responsible for:

* User authentication.
* Patient identity.
* Session management.
* Authorization.
* Consent and access control.
* User-controlled data sharing.

All health information must belong to an identifiable user/patient context and must never be retrieved without authorization.

---

## 4.2 Health Data Service

Responsible for managing structured health information.

Core domains:

* Conditions.
* Symptoms.
* Medications.
* Allergies.
* Procedures.
* Encounters.
* Lab results.
* Vitals.
* Health measurements.
* Goals.
* Lifestyle information.
* External health data.

This service represents **what the system knows about the person** in structured form.

---

## 4.3 Document Service

Responsible for medical documents and other source material.

Supported initial inputs:

* PDF reports.
* Prescriptions.
* Diagnostic reports.
* Discharge summaries.
* Medical images/documents where extraction is feasible.
* Other patient-provided medical records.

The original source must remain preserved.

Every extracted fact should retain a relationship to its originating document and relevant location where possible.

---

## 4.4 Clinical Information Extraction

Transforms documents and patient-provided information into structured health entities.

Example:

```text
Document
   ↓
Extracted information
   ↓
Clinical entities
   ↓
Normalized entities
   ↓
Patient health model
```

Extraction must not silently convert uncertain information into confirmed medical facts.

---

## 4.5 Personal Health Model

The Personal Health Model is the central domain model.

It combines:

```text
Patient Profile
+ Conditions
+ Symptoms
+ Medications
+ Allergies
+ Investigations
+ Encounters
+ Measurements
+ Documents
+ Health Events
+ Goals
+ Patient observations
```

The model must support temporal relationships.

Example:

```text
Medication A
started → 2026-04
changed → 2026-06
stopped → 2026-08
```

rather than storing only:

```text
Medication A = inactive
```

---

# 5. Health Timeline

All meaningful health events should contribute to a unified timeline.

Examples:

```text
2026-03-10  Symptom reported
2026-03-18  Doctor consultation
2026-03-20  Medication started
2026-04-02  Lab test
2026-05-15  Medication changed
2026-06-10  Follow-up consultation
```

The timeline should become the temporal backbone of the personal health model.

---

# 6. Personal Health Memory

The memory system should not be a single undifferentiated vector store.

It should contain multiple forms of memory.

### Profile Memory

Relatively stable information:

```text
Age
Allergies
Known conditions
Long-term medications
Preferences
```

### Event Memory

Time-bound health events:

```text
Symptoms
Visits
Tests
Treatments
Medication changes
```

### Interaction Memory

Important information learned directly from conversations:

```text
Patient reports
Concerns
Goals
Questions
Observed changes
```

### Derived Memory

AI-generated observations:

```text
Possible trend
Potential relationship
Unresolved question
Suggested follow-up
```

Derived memory must always preserve its source, timestamp, confidence, and status.

AI inference must never overwrite source truth.

---

# 7. Retrieval Architecture

The AI context engine should use **hybrid retrieval**, not vector search alone.

A request should be resolved through a combination of:

```text
User question
      ↓
Intent / information need
      ↓
Relevant health entities
      ↓
Temporal filtering
      ↓
Structured database retrieval
      ↓
Document retrieval
      ↓
Timeline retrieval
      ↓
Relevant interaction memory
      ↓
External medical knowledge when necessary
      ↓
Context assembly
```

The final context passed to the model should contain the smallest useful set of relevant information rather than the patient's entire history.

---

# 8. AI Orchestration

The AI layer should be treated as an orchestration pipeline rather than a single prompt.

```text
User input
   ↓
Request classification
   ↓
Safety classification
   ↓
Context retrieval
   ↓
Clinical / health reasoning
   ↓
Evidence grounding
   ↓
Response generation
   ↓
Response safety validation
   ↓
Final response
```

The system should support different request classes such as:

```text
Health explanation
Record summarization
Report comparison
Medication understanding
History questions
Trend questions
General health education
Care navigation
Potentially urgent concern
```

Different classes may use different retrieval and safety policies.

---

# 9. AI Context Contract

The model should receive explicit context categories.

```text
PATIENT FACTS
PATIENT-REPORTED
CLINICAL RECORD EVIDENCE
TIMELINE
RELEVANT PREVIOUS CONTEXT
EXTERNAL MEDICAL KNOWLEDGE
UNCERTAINTIES
SAFETY SIGNALS
```

The model should not need to infer the provenance of information from raw text.

---

# 10. Grounding & Source Attribution

Important health-related responses should be grounded in source information where applicable.

For example:

```text
Claim
 ↓
Source
 ├── Lab report
 ├── Prescription
 ├── Encounter
 ├── Patient statement
 └── External medical reference
```

The product should support source references that allow the user to understand why an answer was generated.

---

# 11. Safety Architecture

Safety must exist outside the generation prompt.

```text
                User Request
                     ↓
              Risk Classification
                     ↓
       ┌─────────────┼─────────────┐
       ▼             ▼             ▼
     Low           Elevated       High
       │             │             │
       ▼             ▼             ▼
    Normal       Cautious       Escalation
    response      response       guidance
```

The safety system should be able to:

* Detect potentially urgent situations.
* Prevent unsafe treatment instructions.
* Avoid unsupported diagnostic certainty.
* Recognize missing critical information.
* Escalate to appropriate professional care when necessary.
* Override ordinary generation behavior when safety policies require it.

Safety-critical rules should be deterministic or policy-controlled wherever practical.

---

# 12. Clinical Decision Support Boundary

Clinical decision support is a future capability built on top of the same Personal Health Model.

The architecture should therefore support:

```text
Patient Context
      ↓
Relevant Evidence
      ↓
AI Clinical Analysis
      ↓
Possible considerations
      ↓
Evidence / rationale
      ↓
Clinician review
      ↓
Clinician decision
```

The system must never assume that an AI-generated clinical consideration is an established diagnosis or treatment decision.

---

# 13. Data Architecture

A relational system should be the source of truth for structured health information.

Core conceptual entities:

```text
User
Patient
HealthProfile

Condition
Symptom
Medication
Allergy
Procedure

Encounter
LabResult
Vital
HealthMeasurement

Document
DocumentSource
DocumentChunk

HealthEvent
TimelineEvent
PatientGoal

Conversation
Message
Memory
Insight

Consent
DataAccess
AuditEvent
```

Documents remain in durable object storage, while extracted/normalized information is stored in the health model.

Semantic retrieval indexes are derived data, not the primary source of truth.

---

# 14. Provenance Model

Every clinically meaningful piece of information should have provenance.

Conceptually:

```text
Health Fact
 ├── source_type
 ├── source_id
 ├── observed_at
 ├── recorded_at
 ├── confidence
 ├── status
 └── verification_state
```

Possible verification states:

```text
SOURCE_RECORDED
PATIENT_REPORTED
AI_DERIVED
CLINICIAN_CONFIRMED
UNCERTAIN
```

This prevents AI-generated information from becoming indistinguishable from medical records.

---

# 15. Conversation Architecture

The conversational interface is a consumer of the Personal Health Model.

A conversation should not become the patient's source of truth by itself.

Important information learned during conversation should be promoted into patient memory only through an explicit classification process.

```text
Conversation
     ↓
Candidate information
     ↓
Classification
     ↓
Patient-reported / observation / goal / question
     ↓
Memory
```

Temporary conversational context should remain separate from persistent health facts.

---

# 16. Proactive Intelligence

Proactive features should be event-driven rather than continuously generating arbitrary advice.

Potential triggers:

```text
New report uploaded
New health measurement
Medication change
Upcoming appointment
Significant timeline change
User-defined goal
Repeated symptom report
```

The system evaluates whether the new event is meaningful before generating an insight.

The system should avoid notification fatigue and should not generate speculative health alerts without sufficient relevance.

---

# 17. Privacy & Security

Health information must be treated as highly sensitive.

The design should enforce:

* Strong authentication.
* Authorization at every protected data boundary.
* Encryption in transit and at rest.
* Minimal data access.
* Explicit consent for external sharing.
* Complete auditability of sensitive operations.
* User-controlled deletion/export where required.
* Separation of tenant/user data.
* Safe handling of model prompts and logs.
* No unnecessary exposure of health information to third-party services.

Sensitive health information should not appear in ordinary application logs.

---

# 18. Auditability

Important system actions should produce audit events.

Examples:

```text
Document uploaded
Record created
Record modified
Data accessed
Consent granted
Consent revoked
AI insight generated
Health data shared
User data deleted
```

Audit records should preserve enough information to understand **what happened, when, and under whose authorization**.

---

# 19. External Data Integrations

The architecture should expose a normalized internal health-data model.

External sources should map into that model rather than becoming independent representations inside the application.

Conceptually:

```text
ABDM / Hospital / Lab / Wearable / Manual Entry
                    ↓
              Integration Layer
                    ↓
             Normalized Health Model
```

This allows future integrations without changing the core product model.

---

# 20. Technology Direction

The initial implementation should favor a simple, production-capable stack.

Suggested direction:

```text
Client
    React Native / Web

Backend
    Python + FastAPI

Primary Database
    PostgreSQL

Semantic Retrieval
    PostgreSQL + vector capability

Object Storage
    S3-compatible storage

Background Processing
    Redis + worker system

AI
    LLM API with structured-output capability

Authentication
    Managed or standards-based authentication

Observability
    Application logs + metrics + AI tracing
```

The exact technologies may change without changing the architectural principles defined in this document.

---

# 21. Deployment Philosophy

The first production version should use a **modular monolith** with clear domain boundaries.

Logical modules:

```text
identity
health
documents
timeline
memory
ai
safety
care
consent
audit
```

Each module should have explicit responsibilities and interfaces.

The system should be designed so modules can later be extracted into services without redesigning the domain model.

---

# 22. Reliability & Failure Handling

The system must assume that external dependencies can fail.

Examples:

```text
LLM unavailable
Document extraction fails
External health integration unavailable
Vector retrieval fails
Database temporarily unavailable
```

Failure behavior should degrade safely.

For example:

> If AI reasoning fails, the user should still be able to access their underlying health records.

AI must never become the only copy of a user's health information.

---

# 23. AI Evaluation

The AI system should be evaluated independently from normal software tests.

Evaluation should cover:

```text
Grounding
Factual accuracy
Source attribution
Context relevance
Personalization
Temporal reasoning
Uncertainty handling
Safety
Hallucination rate
Clinical escalation behavior
```

Evaluation datasets should include representative patient scenarios and difficult edge cases.

Safety failures should carry substantially higher severity than ordinary answer-quality failures.

---

# 24. Design Boundary

This design intentionally does **not** define:

* Exact UI layouts.
* Individual API endpoints.
* Exact database migrations.
* Specific model/provider selection.
* Detailed prompts.
* Exact cloud infrastructure.
* Individual implementation tasks.

Those belong in implementation plans, task specifications, and code.

The purpose of this document is to provide the architectural **north star** for those decisions.

---

# 25. End-to-End System

The intended end state is:

```text
              USER
               │
               ▼
        Health Information
               │
       ┌───────┴────────┐
       ▼                ▼
 Structured Data     Documents
       │                │
       └───────┬────────┘
               ▼
       PERSONAL HEALTH MODEL
               │
       ┌───────┼────────┐
       ▼       ▼        ▼
    Timeline  Memory  Evidence
       │       │        │
       └───────┼────────┘
               ▼
        CONTEXT ENGINE
               │
       ┌───────┼────────┐
       ▼       ▼        ▼
     AI      Safety   Knowledge
   Reasoning  Layer    Sources
       │       │        │
       └───────┼────────┘
               ▼
       PERSONALIZED RESPONSE
               │
       ┌───────┼─────────┐
       ▼       ▼         ▼
   Understand  Insight   Navigate
               │
               ▼
        Professional Care
```

## Architectural Principle

> **The system should not be built around the chatbot. It should be built around the Personal Health Model, with AI acting as the intelligence layer over that model.**

That principle should govern all subsequent implementation decisions.
