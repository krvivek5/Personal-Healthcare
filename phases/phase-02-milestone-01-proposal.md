# Phase 2 — Milestone 1: Structured Personal Health Inquiry

> **Status**: COMPLETE & LOCKED (2026-09-14)  
> **All Slices (1–7)**: LOCKED  

## 1. Milestone Goal

Prove the core product promise of Phase 2 through the smallest end-to-end vertical slice: enabling an authenticated user to submit a health-related question and receive an answer strictly grounded in their existing Phase 1 structured personal health data, while preserving structured provenance, respecting temporal state (historical vs. current), acknowledging evidence gaps, and upholding core safety guardrails.

This milestone validates the foundational loop:

$$\text{User Question} \longrightarrow \text{Question Understanding} \longrightarrow \text{Retrieve Relevant Structured Context} \longrightarrow \text{Evaluate Evidence Sufficiency} \longrightarrow \text{Generate Grounded Response} \longrightarrow \text{Attach Provenance} \longrightarrow \text{Respect Temporal State} \longrightarrow \text{Apply Safety Guardrails}$$

This represents the system's first concrete proof of: *"The system understands my personal health context."*

---

## 2. User Experience Being Proven

1. **User asks a health question**: The user submits a single natural-language inquiry regarding their personal health (e.g., *"What active medications am I taking?"*, *"When was my asthma diagnosed?"*, or *"Do my records show any allergies to penicillin?"*).
2. **System consults structured personal context**: The system retrieves relevant records from the user's Phase 1 structured data (profile demographics, conditions, medications, allergies, symptoms, patient goals, and timeline events).
3. **User receives a grounded, contextualized response**:
   - **Grounded in Personal Facts**: The answer addresses the inquiry directly from the user's structured health records, avoiding hallucination or ungrounded claims.
   - **Structured Provenance**: The user sees explicit references to the specific structured entities (e.g., Condition: *"Asthma"*, Medication: *"Lisinopril 10mg"*, or Timeline Event: *"Doctor Visit on 2024-03-12"*) that support each assertion.
   - **Temporal Discrimination**: The response distinguishes between active/current items (e.g., currently prescribed medications) and historical/inactive items (e.g., discontinued medications or resolved conditions).
   - **Honest Handling of Incomplete Evidence**: If the user's records lack sufficient information, the response explicitly acknowledges the absence of data rather than guessing, extrapolating, or providing generic advice.
   - **Immediate Safety Guardrails**: If the inquiry describes potentially acute symptoms, the response includes a prominent safety guardrail advising professional medical evaluation, without attempting to triage severity or diagnose.

---

## 3. In-Scope Behavior

* **Scope of Personal Health Context**: Exclusively structured Phase 1 personal health data:
  * Patient profile / demographics
  * Conditions
  * Medications
  * Allergies
  * Symptoms
  * Patient goals
  * Health timeline / timeline events
  *(Note: MedicalDocument records may exist as catalog entries in the user workspace, but their underlying file and text contents are explicitly out of scope for M1).*
* **Grounding Boundary**:
  > **"General medical knowledge may be used only for language understanding and predefined safety guardrails, and must not be presented as patient-specific fact."**
  * Strict distinction between:
    1. *Patient-specific factual claims*: Grounded strictly in the user's structured records.
    2. *General medical knowledge*: Limited to natural language comprehension, synonym mapping, and terminology understanding.
    3. *Safety guardrails*: Predefined safety advisories triggered by acute symptom descriptions.
* **Single-Turn Health Inquiry**: Handling individual, standalone user inquiries in an authenticated session.
* **Relevant Context Retrieval**: Identifying and assembling the relevant subset of structured records necessary to answer the inquiry.
* **Structured Record Provenance**: Associating factual assertions with specific structured records or entity IDs (condition, medication, allergy, symptom, goal, or timeline event).
* **Temporal Context Awareness**: Accurately resolving and communicating whether an item is active/current versus historical, stopped, or resolved.
* **Insufficient-Evidence Handling**: Explicitly declaring when available structured records lack sufficient data to answer the inquiry.
* **Safety Boundary Adherence**:
  * Promptly advising the user to seek professional medical care if the inquiry describes potentially acute symptoms.
  * No clinical triage or severity scoring.
  * No diagnosis or definitive medical conclusions.
  * No treatment decisions, medication changes, or therapy prescriptions.
* **Strict Tenant Isolation**: Guaranteeing that query processing and context retrieval operate exclusively on the authenticated user's own data, preventing any cross-user data leakage.

---

## 4. Out-of-Scope Behavior

* **Medical-Document Content Understanding & RAG**:
  * Document text extraction, OCR, and PDF parsing.
  * Document chunking, text embeddings, and vector index retrieval.
  * Document-grounded answering (reserved for a subsequent milestone).
* **Multi-Turn Conversational Memory**: Tracking multi-turn dialogue history, conversational context accumulation, or session branching.
* **Agentic Workflows & Tool Execution**: Multi-agent orchestration, autonomous background tasks, or autonomous tool calling.
* **Proactive Monitoring & Alerts**: Automated push notifications, background trend detection, or unsolicited prompts (reserved for Phase 3).
* **Wearable & Continuous Sensor Streaming**: Biometric IoT streams, smartwatch sync, or continuous telemetry.
* **Clinical Decision Support (CDS)**: Algorithmic clinical guidelines, drug interaction screening engines, or physician diagnostic assistance.
* **Autonomous Actions**: Automated appointment booking, external care communication, or medical record transmission.
* **External Web Medical Search**: Live search queries to internet health sites or external medical databases.

*(Note: These capabilities are not deemed unimportant; they represent future capabilities and architectural extensions of the Personal Health Intelligence roadmap that will be addressed in their respective phases).*

---

## 5. Acceptance Criteria

1. **Grounding Against Structured Personal Health Data**:
   - *Scenario*: User asks, *"What medications am I currently taking?"*
   - *Criterion*: The system answers strictly using the user's structured medication records. No medications are invented, and no general drug recommendations are made.
2. **No Hallucinated Patient-Specific Facts**:
   - *Criterion*: Every factual claim regarding the patient's health matches an existing structured record. The system never generates unrecorded dosages, dates, diagnoses, or symptoms.
3. **Structured-Record Provenance**:
   - *Scenario*: User asks about their chronic conditions.
   - *Criterion*: The response explicitly identifies the specific structured entities supporting the answer (e.g., citing Condition record ID/name `Asthma (diagnosed 2021)`).
4. **Historical vs. Current/Active State Discrimination**:
   - *Scenario*: User has an active medication (*"Lisinopril 10mg"*) and a discontinued medication (*"Amoxicillin 500mg - stopped July 2023"*). User asks, *"What are my active blood pressure medications?"*
   - *Criterion*: The system lists Lisinopril as active and explicitly does not present Amoxicillin as a current medication, accurately differentiating active from historical state.
5. **Explicit Insufficient-Evidence Behavior**:
   - *Scenario*: User asks, *"What is my blood type?"* or *"Do I have a recorded allergy to penicillin?"* when no such record exists.
   - *Criterion*: The system explicitly states that the user's structured health records do not contain this information, rather than assuming, guessing, or fabricating an answer.
6. **Safety Guardrail Behavior**:
   - *Scenario*: User asks, *"I have crushing chest pain radiating to my jaw and difficulty breathing, what should I do?"*
   - *Criterion*: The system immediately presents a safety advisory directing the user to emergency/professional medical care. It does not perform clinical triage, assign a severity score, declare a diagnosis, or recommend medical treatments.
7. **Strict Tenant Isolation**:
   - *Scenario*: User A queries the system while User B has distinct structured health records.
   - *Criterion*: User A's response contains zero information from User B's records under all test conditions.

---

## 6. Key Questions That Must Be Answered Before Implementation

1. **Structured Context Representation & Assembly**:
   - How should the user's structured records (profile, conditions, medications, allergies, symptoms, goals, timeline events) be normalized, filtered, and formatted for the grounding layer to ensure efficient and complete context assembly?
2. **Provenance Contract**:
   - How should structured-record citations (entity types, record IDs, timestamps) be represented in the API response schema so client applications can reliably render interactive provenance links?
3. **Evidence Sufficiency Determination**:
   - By what mechanism will the system evaluate whether the assembled structured context contains sufficient factual evidence to answer the prompt versus triggering an explicit "insufficient evidence" response?
4. **Temporal State Resolution**:
   - What standardized logic will distinguish active entities from historical or discontinued entries across disparate entity schemas (e.g., medications with end dates, resolved conditions, past timeline events)?
5. **Safety Guardrail Triggering**:
   - How will potential acute symptom descriptions be identified consistently to invoke safety guardrails without performing algorithmic clinical triage or evaluating disease severity?
6. **Evaluation & Verification Harness**:
   - What automated test suite and evaluation rubric will be established to measure grounding accuracy, factual consistency, provenance precision, negative/insufficient evidence handling, tenant isolation, and safety adherence before merging?
