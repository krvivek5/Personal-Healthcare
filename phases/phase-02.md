# Phase 2 — Personal Health Intelligence

## 1. Goal

Enable the system to understand an individual's personal health context and deliver personalized, source-grounded health intelligence in response to user questions.

---

## 2. Core Patient Problem

When patients have health questions, they face an unhelpful binary:
1. **Generic search tools and general AI chatbots**, which lack any awareness of the individual's specific health history, active medications, known allergies, past diagnoses, or verified records.
2. **Fragmented personal medical documents and clinical reports**, which are dense, technical, and difficult for patients to synthesize or interpret across time on their own.

As a result, patients struggle to connect their day-to-day health questions to their actual longitudinal health history, leaving them uncertain about what their records actually show versus what is unverified or unknown.

---

## 3. Product Promise

> **"When you ask a question about your health, the system responds using your personal health context—grounded in your records and reported history—helping you understand your health story with provenance, clarity, and explicit boundaries around what is known and unknown."**

The system answers from the patient's own history, not from detached, generic medical generalizations.

---

## 4. First Capability: Grounded Health Inquiry

The primary capability introduced in Phase 2 is an interactive inquiry experience:

* **User asks a health-related question**: The user can ask questions in natural language regarding their symptoms, medications, lab trends, conditions, timeline events, or overall health history.
* **System understands the user's available health context**: The system interprets the question in the context of the user's personal health data established in Phase 1 (demographics, conditions, medications, allergies, symptoms, timeline events, and uploaded medical documents).
* **Response is grounded in that context**: Responses are anchored in the user's actual health data, referencing the relevant context rather than generating generic or ungrounded responses.
* **Evidence and context discrimination**: The system explicitly and reliably distinguishes:
  * **Patient-reported information**: Data recorded directly by the user (e.g., self-reported symptoms, notes, or entries).
  * **Document-backed information**: Facts and findings supported by uploaded source documents (e.g., lab reports, discharge summaries, prescriptions).
  * **Historical vs. current context**: Previous conditions, stopped medications, or historical test results versus active conditions, current medications, and ongoing concerns.
  * **Insufficient evidence**: Explicitly acknowledging when available records lack sufficient data to answer the inquiry, avoiding extrapolation or speculative guessing.

---

## 5. Core Product Principles

1. **Context Over Generality**: Personalized health intelligence requires grounding in the patient's individual history; generic health advice is insufficient.
2. **Provenance and Traceability**: Health insights must remain connected to their origin, whether derived from an uploaded clinical document or a patient-reported log.
3. **Truthful Evidence Hierarchy**: The system must never blur the distinction between patient-recalled information and clinically verified records.
4. **Honesty About Uncertainty**: Clearly stating that information is absent or evidence is inconclusive is a first-class feature of the system.
5. **Comprehension, Not Prescription**: The product serves to enhance patient understanding, self-advocacy, and informed doctor-patient conversations, not to bypass professional clinical care.

---

## 6. Initial Safety Boundary

The system operates strictly within an informational, explanatory, and contextualization boundary:

* **Prioritize**:
  * Longitudinal understanding and historical timeline synthesis.
  * Plain-language explanation of clinical terminology, lab results, and report contents.
  * Contextualization of current inquiries against documented past events.
  * Explicit communication of uncertainty, data gaps, and evidence limits.
  * **Safety Guardrails**: Promptly advising the user to seek professional medical care if their inquiry describes potentially acute symptoms, without attempting to formally evaluate or triage the severity of their condition.
* **Strict Safety Boundaries**:
  * **No clinical triage**: The system does not perform clinical triage, assign definitive triage categories, or replace clinical intake workflows.
  * **No diagnosis**: The system does not determine diagnoses or issue definitive clinical conclusions.
  * **No treatment decisions**: The system does not determine, prescribe, modify, initiate, or discontinue treatments, therapies, or medication regimens.

---

## 7. Future Capability & Architecture Boundaries

### Foundational Architecture to Be Designed During Phase 2
- Retrieval and grounding architecture
- Personal health context representation
- Longitudinal health memory

These are considered foundational to the long-term Personal Health Intelligence system. Their specific technical architecture is intentionally not prescribed by this product charter and will be determined during Phase 2 implementation planning.

### Future Product Capabilities
- Agents and orchestration
- Proactive monitoring
- Wearable and continuous health-data integration
- Autonomous actions such as appointment booking or external communication

These are part of the longer-term product direction but are outside the initial Grounded Health Inquiry capability.

### Advanced Clinical Capability
- Clinical decision support

This is a future capability with substantially higher clinical, evidence, safety, and regulatory requirements and is outside the initial Phase 2 scope.

---

## 8. Milestone Roadmap & Implementation Status

### Milestone 1: Structured Personal Health Inquiry — COMPLETE & LOCKED
* **Status**: **COMPLETE & LOCKED** (2026-09-14)
* **Scope**: Smallest vertical slice enabling authenticated health question answering strictly grounded in Phase 1 structured personal health data, preserving structured provenance, respecting temporal state (historical vs. current), acknowledging evidence gaps, and upholding core deterministic safety guardrails.
* **Slices Completed & Locked**:
  * **Slice 1: Inquiry Schemas & Contracts** (`backend/app/schemas/inquiry.py`, `backend/tests/test_inquiry_schema.py`) — **LOCKED**
  * **Slice 2: Structured Context Assembly Service** (`backend/app/health/inquiry_context.py`, `backend/tests/test_inquiry_context.py`) — **LOCKED**
  * **Slice 3: Query Understanding & Evidence Evaluator** (`backend/app/health/query_understanding.py`, `backend/app/health/evidence_evaluator.py`, `backend/tests/test_inquiry_evidence.py`) — **LOCKED**
  * **Slice 4: Inference Provider Interface & Mock Provider** (`backend/app/core/llm.py`, `backend/tests/test_llm_provider.py`) — **LOCKED**
  * **Slice 5: Deterministic Safety Guardrail Engine** (`backend/app/health/safety_guardrails.py`, `backend/tests/test_safety_guardrails.py`) — **LOCKED**
  * **Slice 6: End-to-End API Integration & Tenant Scoping** (`backend/app/api/health_inquiry.py`, `backend/tests/test_health_inquiry_api.py`) — **LOCKED**
  * **Slice 7: Frontend Health Inquiry UI & Citations** (`frontend/src/components/HealthInquiryView.tsx`, `frontend/src/lib/api.ts`, `frontend/src/components/WorkspaceView.tsx`, `frontend/src/components/HealthInquiryView.test.tsx`) — **LOCKED**

### Intentionally Deferred Capabilities (Deferred to M2+)
As established in the formal Milestone 1 completion review, the following capabilities are explicitly deferred from M1 and will be introduced in subsequent milestones:
1. **Live LLM Provider Integration & Dynamic Prompt Synthesis (Milestone 2)**:
   - Connection to production LLM provider APIs (e.g., OpenAI, Anthropic, Gemini).
   - Dynamic prompt generation, token budgeting, and real-time inference.
   - Streaming answer synthesis with latency controls.
2. **Medical-Document Text Extraction & Unstructured RAG (Milestones 3 & 4)**:
   - Document text extraction, OCR, and PDF parsing.
   - Document chunking, text embeddings, and vector index retrieval (pgvector).
   - Synthesis grounded across both unstructured documents and structured records.
3. **Multi-Turn Conversational Memory & Dialogue Context (Milestone 5)**:
   - Tracking multi-turn dialogue history and session state.
   - Conversational context accumulation and context window compression.
4. **Interactive Provenance Click-Through & Viewport Deep-Linking**:
   - Interactive deep links from inline citation tags/badges to source document viewports or clinical record drawers.
5. **Real-Time NLI Semantic Entailment Engine**:
   - Automated natural language inference (NLI) model verifying semantic claim entailment in real time (M1 enforces citation validity deterministically server-side).

