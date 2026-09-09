# Personal Healthcare Intelligence — Roadmap

## 1. Purpose

This roadmap defines the phased evolution of the Personal Healthcare Intelligence product.

`SPEC.md` defines what and why.

`DESIGN.md` defines the overall system design.

This document defines **what we build next and why**, without prescribing detailed implementation steps.

Each phase must have its own phase specification containing its scope, milestones, acceptance criteria, and validation requirements.

---

# 2. Product Evolution

The product evolves through five major stages:

```text
Personal Health Foundation
          ↓
Personal Health Intelligence
          ↓
Proactive Health Intelligence
          ↓
Care Navigation
          ↓
Clinical Intelligence
```

Each stage must establish a meaningful product capability before the next stage begins.

---

# Phase 1 — Personal Health Foundation

## Goal

Create a trusted personal health space where users can bring together and organize their important health information.

## Core capabilities

* User identity and secure access.
* Personal health profile.
* Conditions, symptoms, medications, allergies, and health information.
* Medical document upload and storage.
* Health events.
* Chronological health timeline.
* Source/provenance information.
* Secure user-level data isolation.

## Milestone

> **A user can securely establish and view their own health story in one place.**

## Not included

AI health chat, advanced RAG, proactive insights, wearables, EHR integrations, doctor discovery, appointments, and clinical decision support.

---

# Phase 2 — Personal Health Intelligence

## Goal

Make the system understand the user's health context and provide personalized health intelligence.

## Core capabilities

* Personal health chat.
* Context-aware retrieval.
* Health-history summarization.
* Medical document understanding.
* Report comparison.
* Cross-time reasoning.
* Medication and condition understanding.
* Personalized health explanations.
* Source-grounded answers.
* Persistent health memory.
* Uncertainty-aware responses.
* Core health-safety behavior.

## Milestone

> **A user can ask about their health and receive answers based on their own history rather than generic medical information.**

---

# Phase 3 — Proactive Health Intelligence

## Goal

Move from answering questions to helping users notice and manage meaningful changes.

## Core capabilities

* Health trend detection.
* Relevant change detection.
* Personalized health insights.
* Follow-up prompts.
* User-defined health goals.
* Monitoring of selected health measurements.
* Context-aware reminders.
* Event-triggered health intelligence.

## Milestone

> **The system can recognize meaningful developments in a user's health context and proactively surface useful information.**

The product should avoid unnecessary alerts and speculative recommendations.

---

# Phase 4 — Care Navigation

## Goal

Help users move from understanding their health to taking the appropriate next step.

## Core capabilities

* Care-seeking guidance.
* Appropriate escalation guidance.
* Primary-care and specialist discovery.
* Provider matching based on the user's needs and context.
* Appointment workflows.
* Relevant health-history preparation for visits.
* Controlled sharing of relevant health information.
* Follow-up care support.

## Milestone

> **A user can move from “I understand what is happening” to “I know what to do next and how to access the appropriate care.”**

This phase should build on personal health intelligence rather than becoming a standalone healthcare marketplace.

---

# Phase 5 — Clinical Intelligence

## Goal

Extend the personal health intelligence layer into clinician-facing workflows.

## Core capabilities

* Longitudinal patient summaries.
* Clinician-ready health context.
* Relevant history and trends.
* Patient-generated information for clinical encounters.
* Evidence-grounded clinical considerations.
* Clinical decision support.
* Clinician review and confirmation.
* Patient-clinician information continuity.

## Milestone

> **The patient's longitudinal health context can help clinicians understand the patient faster and make better-informed decisions.**

The clinician remains the final decision-maker for diagnosis and treatment.

---

# 3. Cross-Phase Principles

Every phase must preserve the following principles:

### Personal context first

The product should become increasingly useful because it understands the individual user.

### Longitudinal understanding

Health information should retain its temporal context.

### Source awareness

The system must distinguish source information from patient-reported information and AI-derived information.

### Safety

Healthcare safety is a system behavior, not merely a disclaimer.

### Human control

The user controls their health information and important healthcare decisions.

### Incremental development

Each phase should deliver a usable product capability before expanding scope.

### Test continuously

Meaningful changes must be validated before proceeding to additional functionality.

---

# 4. Phase Progression

The product should progress according to this dependency:

```text
PHASE 1
Reliable personal health context
        ↓
PHASE 2
AI understands personal context
        ↓
PHASE 3
AI proactively identifies meaningful changes
        ↓
PHASE 4
AI helps navigate appropriate care
        ↓
PHASE 5
Personal health intelligence becomes clinician intelligence
```

Later phases must build on the capabilities established earlier rather than replacing them.

---

# 5. Scope Discipline

A feature should enter the roadmap only when it strengthens the core product thesis:

> **Use personal health context to help people understand, manage, and navigate their healthcare.**

Features that do not materially contribute to this goal should remain outside the roadmap unless the product strategy is explicitly changed.

---

# 6. Current Development State

**Current phase: Phase 1 — Personal Health Foundation**

Only the current phase should be actively implemented.

The next phase should begin only after the current phase meets its defined acceptance criteria and its test suite is passing.
