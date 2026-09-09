## 1. Product Definition — LOCKED

### Working product thesis

> **Build a personal health intelligence layer for patients that unifies their health information, develops a longitudinal understanding of their health, and uses AI to help them understand, manage, and navigate their healthcare.**

### Initial target user

**Adults managing ongoing, recurring, or multiple health problems.**

Examples:

* chronic pain
* diabetes / hypertension
* recurring gastrointestinal problems
* thyroid conditions
* post-surgery recovery
* multiple medications
* patients seeing multiple doctors
* patients carrying reports across hospitals

This is a better initial **wedge [word: narrow entry point into a larger market]** than “everyone interested in health.”

Why? A healthy user may ask the AI two questions a month. A patient managing a complex health situation has a persistent problem worth solving.

---

# 2. The Core User Problem

Today:

```text
Hospital A
   ↓
Lab reports
   ↓
Doctor B
   ↓
Prescription
   ↓
Hospital C
   ↓
Another report
   ↓
Patient's memory
   ↓
Google / ChatGPT
```

The patient is effectively the integration layer.

Our product changes this:

```text
             ┌── Medical Records
             ├── Lab Reports
             ├── Prescriptions
             ├── Doctor Notes
Patient ────►├── Symptoms
             ├── Medications
             ├── Lifestyle
             ├── Wearables
             └── Patient Observations
                       │
                       ▼
              PERSONAL HEALTH MODEL
                       │
                       ▼
                AI HEALTH ENGINE
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
      Understand     Monitor      Navigate
```

The **personal health model** is the heart of the product.

---

# 3. What We Are Actually Building

Think of the system as four products stacked together.

### Layer 1 — Personal Health Record

The patient brings data into Galen.

V1:

* PDF reports
* prescriptions
* diagnostic reports
* discharge summaries
* uploaded medical documents
* manually entered conditions
* medications
* symptoms
* allergies
* appointments
* health measurements

Later:

* ABDM-connected records
* hospital integrations
* labs
* pharmacies
* wearables
* glucose / BP devices

India already has a consent-based digital health interoperability direction through ABDM, including health-record exchange and PHR/health-locker capabilities. ABDM explicitly states that records remain with originating providers while the network facilitates sharing with patient consent. ([Ayushman Bharat Digital Mission][1])

So our architecture should make **consent and provenance [word: traceable origin/history of information] first-class concepts**, rather than treating them as future compliance work.

---

# 4. Layer 2 — Personal Health Memory

This is where we differentiate.

Do **not** build:

```text
PDF → embeddings → chatbot
```

That is insufficient.

Build a structured longitudinal model.

For example:

```text
Patient
│
├── Demographics
├── Conditions
│   ├── Hypertension
│   └── Low back pain
│
├── Symptoms
│   ├── Pain
│   └── Fatigue
│
├── Medications
│   ├── Drug A
│   └── Drug B
│
├── Investigations
│   ├── Blood test
│   └── MRI
│
├── Encounters
│   ├── Doctor A
│   └── Hospital B
│
├── Treatments
├── Allergies
├── Procedures
├── Lifestyle
├── Wearables
├── Goals
│
└── Timeline
    ├── 2026-01-12
    ├── 2026-03-04
    ├── 2026-05-21
    └── 2026-08-19
```

Every important fact should have metadata:

```text
fact
source
timestamp
confidence
patient_confirmed
clinician_confirmed
```

This allows us to distinguish:

> **What the patient said**

from

> **What the document says**

from

> **What the AI inferred**

from

> **What a clinician confirmed**

That distinction will eventually become one of our strongest trust mechanisms.

---

# 5. Layer 3 — AI Health Intelligence

The AI is not simply “chat.”

It performs several jobs.

### Understand

> “Explain my latest blood report.”

### Summarize

> “What has happened with my health over the last year?”

### Connect information

> “Could my current medication be relevant to the symptoms I've been experiencing?”

### Compare

> “What changed between my January and August reports?”

### Prepare

> “What should I tell my doctor at my appointment?”

### Monitor

> “My blood pressure has been increasing. Is that something I should pay attention to?”

### Navigate

> “Given my history, what kind of doctor would typically evaluate this?”

The system should always distinguish:

```text
Known
│
├── Directly documented
├── Patient reported
└── Clinically established

AI interpretation
│
├── Possible
├── Relevant
└── Uncertain

Action
│
├── Self-management information
├── Monitor
├── Contact clinician
└── Urgent care
```

---

# 6. Layer 4 — Care Navigation

This should come **after** personal health intelligence.

Eventually:

```text
Health concern
      ↓
Understand context
      ↓
Determine appropriate next step
      ↓
Primary doctor / specialist
      ↓
Find provider
      ↓
Appointment
      ↓
Share relevant history
      ↓
Follow-up
```

This is where your earlier idea about doctor recommendations and appointments fits.

But notice the sequence:

**Intelligence first → action second.**

Not:

**Marketplace first → intelligence later.**

---

# 7. V1 — What We Build

I would lock V1 to this:

## “Know Me”

A patient can create a health profile, upload their medical documents, and interact with an AI that understands the accumulated health context.

### V1 capabilities

**1. Patient profile**

```text
Name
Age
Sex
Conditions
Allergies
Medications
Health goals
```

**2. Medical document ingestion**

```text
PDF
Image
Prescription
Lab report
Discharge summary
Medical report
```

Pipeline:

```text
Upload
 ↓
Document classification
 ↓
Text/data extraction
 ↓
Clinical entity extraction
 ↓
Normalization
 ↓
Validation
 ↓
Store
 ↓
Add to patient timeline
```

**3. Personal health timeline**

Example:

```text
Aug 2026
  New blood test

Jul 2026
  Doctor visit
  Medication changed

May 2026
  MRI

Mar 2026
  Symptoms started
```

**4. Personal health chat**

The AI retrieves from:

```text
Structured patient data
+
Relevant medical documents
+
Timeline
+
Previous confirmed facts
+
General medical knowledge
```

**5. Personalized answers**

The system should explicitly reference the patient's own data where relevant.

Example:

> “Your July report showed X. Your August report shows Y. That is a change worth discussing with your doctor.”

That is much more valuable than:

> “Generally, X can be caused by Y.”

---

# 8. What V1 Must NOT Do

Lock these out.

### No autonomous diagnosis

Do not position:

> “You have disease X.”

Instead:

> “These findings can be associated with several conditions. A clinician would need to evaluate them in context.”

### No autonomous treatment

Do not:

> “Stop medication X.”

Instead:

> “Do not change prescribed medication without discussing it with your clinician.”

### No pretending to be a physician

The system is a **health intelligence companion**, not an AI doctor.

### No giant healthcare marketplace

No insurance marketplace, pharmacy marketplace, hospital marketplace, etc.

### No 100-device wearable integration

Start with the core health-data problem.

---

# 9. The AI Architecture

I would deliberately avoid building a complicated multi-agent architecture initially.

Use a **modular monolith**.

Your engineering stack can be:

```text
Mobile/Web
   │
   ▼
FastAPI Backend
   │
   ├── Auth
   ├── Patient Profile
   ├── Documents
   ├── Timeline
   ├── Medications
   ├── Health Data
   ├── AI Chat
   └── Audit
        │
        ▼
   AI Orchestrator
        │
        ├── Query Understanding
        ├── Patient Context Retrieval
        ├── Clinical Data Retrieval
        ├── Document Retrieval
        ├── Reasoning
        ├── Safety Validation
        └── Response Generation
        │
        ▼
PostgreSQL
   ├── Structured health data
   ├── timeline
   ├── users
   ├── medications
   ├── conditions
   └── audit records

Object Storage
   └── Original medical documents

Vector Index
   └── Searchable document chunks
```

For your development style, something like:

**Expo/React Native + FastAPI + PostgreSQL + pgvector + object storage + Redis/background jobs + LLM API**

is sufficient for V1.

Do not introduce Kubernetes, microservices, Kafka, multiple databases, graph databases, or elaborate agent frameworks yet.

---

# 10. The Critical Retrieval Architecture

This is particularly important.

When the patient asks:

> “Why am I feeling more tired recently?”

we should **not** perform only semantic vector search.

The system should perform:

```text
Question
   ↓
Intent detection
   ↓
Relevant patient entities
   ↓
Temporal filtering
   ↓
Structured retrieval
   ↓
Document retrieval
   ↓
Timeline retrieval
   ↓
Relevant previous conversation
   ↓
AI reasoning
```

For example:

```text
Medications
Recent lab values
Recent symptoms
Recent encounters
Lifestyle changes
Patient-reported observations
```

Then the LLM generates the response.

This makes the system **context-aware**, rather than merely RAG-enabled.

---

# 11. Personal Health Memory Architecture

I recommend four memory types.

### A. Profile Memory

Stable information.

```text
Age
Allergies
Known conditions
Long-term medications
```

### B. Timeline Memory

Time-dependent events.

```text
2026-05-14 MRI
2026-06-03 medication changed
2026-07-11 symptom worsened
```

### C. Episodic Memory

Interactions with the AI.

```text
Patient reported increasing pain.
Patient expressed concern about medication.
Patient wants to improve sleep.
```

### D. Derived Memory

AI-generated observations.

```text
Possible trend:
weight has increased over 3 months
```

But derived memory must carry:

```text
source
confidence
timestamp
status
```

It should never silently become a medical fact.

---

# 12. Safety Architecture

Healthcare safety cannot be just a prompt saying:

> “You are a safe medical assistant.”

We need a separate safety layer.

```text
User Query
    ↓
Risk Classification
    ↓
┌───────────────┐
│ Low risk      │ → normal response
│ Moderate      │ → cautious guidance
│ High risk     │ → escalation guidance
│ Emergency     │ → urgent emergency guidance
└───────────────┘
```

And some safety rules should be deterministic rather than entirely LLM-dependent.

For example:

```text
Potential emergency signal
        ↓
Safety policy
        ↓
Immediate escalation
```

The AI should also be able to say:

> “I don't have enough information to determine this.”

That is a feature, not a failure.

---

# 13. Data Model — Initial Version

Your PostgreSQL schema can begin around:

```text
users
patients
health_profiles

conditions
medications
allergies

documents
document_chunks

encounters
lab_results
vital_measurements

symptoms
health_events
timeline_events

patient_goals

ai_conversations
ai_messages
ai_insights

source_references
consents
audit_events
```

The important table is arguably:

```text
source_references
```

because every meaningful AI assertion should eventually be traceable back to:

```text
Document
Lab
Encounter
Patient statement
Imported record
External medical source
```

That becomes our **epistemic [word: relating to what is known and how confidently it is known] foundation**.

---

# 14. Product Experience

The home screen should not feel like:

> “Ask our AI anything.”

Instead:

```text
Good morning.

Your Health
────────────────────

Recent
• Blood test — Aug 28
• Doctor visit — Aug 21

Things to review
• Blood pressure trend
• Medication changed recently

Ask about your health
[ What would you like to understand? ]

Your timeline
────────────────────
```

The UX communicates:

> **“This system knows your health.”**

not:

> **“This is another chatbot.”**

---

# 15. Your First Killer Interaction

This is what I would optimize aggressively.

A new user uploads:

```text
5 medical PDFs
2 prescriptions
3 lab reports
```

The system processes them and says:

> **“I've organized your health history. Here's what I found.”**

Then produces:

```text
Your Health Story

Known conditions
...

Current medications
...

Recent investigations
...

Important changes
...

Questions worth discussing with your doctor
...

Timeline
...
```

That moment is the **aha moment**.

The user realizes:

> “This thing actually understands my health.”

That is what we should build around.

---

# 16. MVP Success Metric

Don't measure V1 primarily by:

> number of chatbot messages.

Measure whether we are creating useful personal context.

The most important signals:

```text
% documents successfully structured
% patients with useful longitudinal profile
% queries answered using personal context
% answers with traceable sources
user-rated usefulness
return usage
incorrect/high-risk response rate
```

The north-star question:

> **“Does the product make the patient feel substantially more informed about their own healthcare?”**

---

# 17. Roadmap

### Phase 1 — Health Foundation

```text
Authentication
Patient profile
Document upload
Document processing
Structured health record
Timeline
```

### Phase 2 — Personal Health Intelligence

```text
Context retrieval
Personal health chat
Health summaries
Report comparison
Medication understanding
Timeline questions
Source citations
```

### Phase 3 — Proactive Intelligence

```text
Trend detection
Health monitoring
Personalized insights
Reminders
Relevant questions
Follow-up prompts
```

### Phase 4 — Care Navigation

```text
Triage
Care recommendations
Specialist discovery
Doctor discovery
Appointment booking
Record sharing
```

### Phase 5 — Clinician Intelligence

This is where our earlier clinical-decision-support thesis returns:

```text
Patient longitudinal summary
        ↓
Clinician view
        ↓
Relevant history
        ↓
Relevant trends
        ↓
Potential considerations
        ↓
Evidence
        ↓
Clinician decision
```

The physician remains the decision-maker.

---

# 18. India Strategy

This is an especially interesting part of the opportunity.

India already has an interoperability infrastructure direction through **ABDM**, including ABHA-linked records, consent-managed sharing, health lockers/PHRs, and APIs for digital health solutions. ([Ayushman Bharat Digital Mission][1])

That means our long-term architecture should be compatible with:

```text
Patient
   ↓
ABHA / ABDM
   ↓
Health records
   ↓
Galen Personal Health Intelligence
```

But I would **not make ABDM integration a prerequisite for V1**.

Start with:

> **Upload → understand → remember → personalize**

Then integrate external health-data networks.

This reduces dependency on external infrastructure and lets us validate the core value proposition first.

Also, India's **Digital Personal Data Protection Rules, 2025** have been notified by MeitY, with an enforcement timeline published alongside them. ([MeitY][2])

Therefore, privacy, consent, deletion, auditability, purpose limitation, and controlled data sharing should be built into the architecture from day one rather than retrofitted later. ABDM's own privacy model similarly emphasizes purpose limitation and consent-based record access. ([Ayushman Bharat Digital Mission][3])

---

# 19. The Company-Level Vision

Here is the version I would keep as our internal north star:

> **We are building the personal health intelligence layer for every individual.**
>
> Healthcare information is fragmented across hospitals, doctors, laboratories, medications, devices, and years of medical history. Our system brings that information together, builds a longitudinal understanding of the individual, and uses AI to transform that context into personalized understanding, proactive guidance, and better healthcare decisions.
>
> The patient owns the experience. The AI provides intelligence. The clinician remains responsible for medical decisions.

And the implementation sequence is now **locked**:

```text
              PERSONAL HEALTH INTELLIGENCE
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
     HEALTH DATA      MEMORY         AI REASONING
          │              │              │
          └──────────────┼──────────────┘
                         ▼
                 PERSONALIZED CARE
                         │
               ┌─────────┴─────────┐
               ▼                   ▼
          SELF-MANAGEMENT      CLINICIAN
                                   │
                                   ▼
                            CARE NAVIGATION
```

### The single implementation goal

> **V1 must make a patient say: “This AI understands my health history and can help me make sense of it.”**

Everything that does not materially contribute to that outcome is secondary for now.
