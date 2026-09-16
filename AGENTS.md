# AGENTS.md — Project Instructions

## 1. Purpose

This file contains the persistent rules for all coding agents working on this project.

Agents must follow:

```text
docs/SPEC.md     → Product intent
docs/DESIGN.md   → System design
docs/ROADMAP.md  → Product phases
phases/phase-XX.md → Current implementation scope
AGENTS.md   → Rules for working on the project
```

When documents conflict, higher-level product intent takes precedence.

---

# 2. Product Alignment

Always build toward the Personal Healthcare Intelligence vision defined in `SPEC.md`.

Do not turn the product into:

* A generic medical chatbot.
* An autonomous doctor.
* An autonomous diagnosis or treatment system.
* An unrelated healthcare marketplace.
* A collection of disconnected health utilities.

Every feature should have a clear connection to the current product phase.

---

# 3. Scope Discipline

Work only on the current phase and milestone.

Do not:

* Implement future-phase features early.
* Add speculative features.
* Introduce unnecessary infrastructure.
* Over-engineer for hypothetical scale.
* Change product scope without explicit instruction.

When a future capability needs architectural consideration, create the smallest compatible foundation without implementing the capability itself.

---

# 4. Product Before Technology

Make product requirements and acceptance criteria the primary source of truth.

Choose the simplest reliable technical solution that satisfies them.

Technology should serve the product—not dictate the product.

---

# 5. Health Data Principles

Treat health information as sensitive data.

Always preserve, where applicable:

* Ownership.
* Source/provenance.
* Time context.
* Data integrity.
* User authorization.

Do not silently transform AI-generated information into confirmed medical facts.

Distinguish between:

```text
Source information
Patient-reported information
Clinician-confirmed information
AI-derived information
Uncertain information
```

---

# 6. AI Safety Principles

AI must not be treated as an autonomous medical authority.

The system should:

* Represent uncertainty clearly.
* Avoid unsupported diagnostic certainty.
* Avoid autonomous treatment decisions.
* Escalate potentially urgent situations appropriately.
* Ground important health-related responses in relevant information.
* Preserve source attribution where applicable.

Safety must be implemented through system behavior, not only prompts or disclaimers.

---

# 7. Development Workflow

For every meaningful change:

```text
Understand
   ↓
Implement the smallest useful change
   ↓
Run relevant tests
   ↓
Fix failures
   ↓
Run regression tests
   ↓
Review behavior
   ↓
Continue
```

Never accumulate multiple untested changes.

Do not proceed with known failing tests unless explicitly instructed.

---

# 8. Testing Requirements

Tests are part of the implementation, not a final step.

At minimum, test:

* Core domain behavior.
* Authentication and authorization.
* User data isolation.
* Health-data integrity.
* Important AI behavior.
* Safety boundaries.
* Error and failure cases.

Every bug discovered should be evaluated for an appropriate regression test.

---

# 9. Code Quality

Prefer:

* Small, understandable modules.
* Clear naming.
* Explicit boundaries.
* Minimal dependencies.
* Reusable domain logic.
* Consistent formatting and linting.
* Simple implementations over clever abstractions.

Avoid premature abstraction and unnecessary complexity.

---

# 10. Data & Privacy

Never expose personal health information unnecessarily.

Do not place sensitive health information in:

* Debug logs.
* Error messages visible to unauthorized users.
* Test fixtures committed without appropriate protection.
* Telemetry or analytics without a valid purpose.

Authorization must be enforced at the data boundary, not merely in the UI.

---

# 11. Changes to Architecture or Product

Before making a change that materially affects architecture, data models, product behavior, or safety:

1. Check `SPEC.md`.
2. Check `DESIGN.md`.
3. Check the active phase specification.
4. Prefer a backward-compatible, minimal change.
5. Document significant deviations.

Do not silently redefine product requirements through code.

---

# 12. Agent Reporting

At the end of each milestone, report:

```text
Implemented
Tests run
Test results
Files/components changed
Specification deviations
Known risks or remaining issues
```

Do not claim a feature is complete unless its acceptance criteria are satisfied.

---

# 13. Definition of Done

A feature is done only when:

* It satisfies the current phase requirements.
* Relevant tests pass.
* Regression tests pass.
* Security/privacy expectations are satisfied.
* No known critical issue remains.
* The implementation does not violate the product specification.

---

# 14. Final Rule

> **Build only what is needed now, preserve the architecture needed for what comes next, and never sacrifice safety, data integrity, or product clarity for implementation convenience.**
