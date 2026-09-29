# Phase 2 — Milestone 6 — Slice 6: Implementation Plan
## Longitudinal Evaluation Harness, Benchmark Expansion & Full Regression

> **Milestone Theme**: *Empower personal health inquiry with chronological intelligence: deterministic superlative resolution, recency-ranked vector retrieval, longitudinal Health Timeline grounding, cross-time report comparison, and multi-source chronological citation reconciliation.*  
> **Slice Scope**: *Longitudinal Evaluation Harness, Benchmark Expansion & Full Regression: Authoritative 70-Query Benchmark Corpus Tuple, Three-Layer Evaluation Harness, 12 Locked Invariant Adversarial Suite, Inherited Debt Baseline Accounting, Deterministic Conformance Gates, and Comprehensive Full-Stack Regression Protocol.*  
> **Status**: V1.0 — IMPLEMENTATION FROZEN  
> **Baseline Commit**: `dd1c743` (`feat(health): implement M6 S5 timeline provenance UX`)  
> **Parent Authorities**:
> - [`phases/P2-M6-architecture-lock.md`](file:///d:/Personal%20Projects/Personal%20HealthCare/phases/P2-M6-architecture-lock.md)  
> - [`docs/SPEC.md`](file:///d:/Personal%20Projects/Personal%20HealthCare/docs/SPEC.md)  
> - [`docs/DESIGN.md`](file:///d:/Personal%20Projects/Personal%20HealthCare/docs/DESIGN.md)  
> - [`docs/ROADMAP.md`](file:///d:/Personal%20Projects/Personal%20HealthCare/docs/ROADMAP.md)  
> - [`phases/P2-M5-architecture-lock.md`](file:///d:/Personal%20Projects/Personal%20HealthCare/phases/P2-M5-architecture-lock.md)  
> - [`phases/P2-M5-S6-plan.md`](file:///d:/Personal%20Projects/Personal%20HealthCare/phases/P2-M5-S6-plan.md)  
> **Execution Rule**: S6 is STRICTLY a test harness and evaluation slice. ZERO production code modifications, ZERO database migrations, and ZERO modifications to existing tests are authorized.

---

## 1. Purpose & Scope

### 1.1 Purpose
Milestone 6 delivered chronological intelligence across S1 through S5:
- **Slice 1 (`test_query_understanding_m6_s1.py`)**: Superlative extraction (`SuperlativeType.LATEST`, `SuperlativeType.FIRST`), timeline domain routing (`STRUCTURED_DOMAINS` union), `question_intent = "COMPARISON"`, and interval-superlative composition.
- **Slice 2 (`test_recency_retrieval_m6_s2.py`)**: Recency-ranked vector retrieval, pre-retrieval SQL date resolution, and deterministic hybrid candidate recall union (dense semantic $K_{\text{dense}}=10$ + lexical whole-token boundary $K_{\text{lexical}}=10$).
- **Slice 3 (`test_timeline_evidence_m6_s3.py`)**: Health Timeline projection grounding, collision-free UUID5 stable identity generation (`generate_timeline_event_id`), and M5-aligned timeline evidence evaluation.
- **Slice 4 (`test_evidence_fusion_m6_s4.py`, `test_health_inquiry_m6_s4.py`)**: Longitudinal reasoning, multi-point milestone trajectory policy ($N \le 3$, $K \le 4$), Section 7.3 cross-domain superlative reconciliation, and backend-owned `TrajectoryCompleteness` qualifier signaling.
- **Slice 5 (`HealthInquiryView.test.tsx`)**: Frontend timeline provenance UX, dedicated purple timeline citation cards, and comparative response narrative layout.

**Slice 6 establishes the formal evaluation harness and permanent quality gates for Milestone 6.** It delivers:
1. The **Authoritative 70-Case Benchmark Corpus** in `backend/tests/eval/m6_benchmark_corpus.py`, preserving all 54 M5 cases verbatim and adding 16 new locked M6 cases across Categories 10–13.
2. The **Three-Layer Deterministic Evaluation Harness** in `backend/tests/eval/test_m6_evaluation.py` (Layer 1: Query Understanding Conformance; Layer 2: Evidence / Retrieval / Fusion Conformance; Layer 3: API / Orchestrator Conformance).
3. The **Adversarial Invariant Validation Suite** in `backend/tests/eval/test_m6_invariants.py`, algorithmically proving all 9 locked M6 invariants plus 3 extended recency properties using deterministic pytest mechanisms without external hypothesis dependencies.
4. **Verified Baseline & Inherited Debt Accounting**, explicitly preserving known legacy failures without masking (956 passed, 2 failed, 4 skipped, 16 warnings; 0 errors, 0 xfailed, 0 xpassed).
5. **Full Regression Execution Matrix** validating both backend and frontend.

### 1.2 Scope Boundaries & Governing Constraints
- **In Scope (Authorized Deliverables)**:
  - `backend/tests/eval/m6_benchmark_corpus.py` (New file)
  - `backend/tests/eval/test_m6_evaluation.py` (New file)
  - `backend/tests/eval/test_m6_invariants.py` (New file)
  - `phases/P2-M6-S6-plan.md` (This authoritative specification)
- **Strictly Out of Scope (Forbidden)**:
  - ZERO changes to backend production code (`backend/app/**`).
  - ZERO changes to database models (`backend/app/db/**`) or migrations (`backend/alembic/**`).
  - ZERO changes to frontend application or test code (`frontend/**`).
  - ZERO modifications to frozen M1–M5 unit tests or evaluation files (`backend/tests/eval/m5_benchmark_corpus.py`, `backend/tests/eval/test_m5_evaluation.py`).
  - ZERO modifications to S1–S5 test files (`test_query_understanding_m6_s1.py`, etc.).
  - NO external runtime testing dependencies (e.g. `hypothesis`).

---

## 2. Parent Architecture Authorities

The implementation of S6 is strictly governed by:
1. [`phases/P2-M6-architecture-lock.md`](file:///d:/Personal%20Projects/Personal%20HealthCare/phases/P2-M6-architecture-lock.md):
   - **Section 3**: Superlative Contract (LATEST, FIRST, tie-breaking, undated exclusion).
   - **Section 4**: Timeline Domain Contract (M5 7-case alignment, `DOCUMENT_UPLOADED` disqualification).
   - **Section 5**: Recency Retrieval Contract (Pre-retrieval SQL date discovery, hybrid candidate recall union, token-structure precision).
   - **Section 6**: Stable UUID5 Citation Identity (`generate_timeline_event_id`).
   - **Section 7**: Cross-Time Comparison Contract (Longitudinal Trajectory Policy $N \le 3$, $K \le 4$, Section 7.3 cross-domain reconciliation, `TrajectoryCompleteness`).
   - **Section 12.1**: M5 Benchmark Harness as permanent immutable regression gate.
   - **Section 12.2**: M6 Benchmark Corpus locked at exactly 70 cases.
   - **Section 12.3**: Adversarial Invariant Validation Layer (12 system invariants).
   - **Section 12.4**: Inherited Debt Accounting.
2. [`docs/SPEC.md`](file:///d:/Personal%20Projects/Personal%20HealthCare/docs/SPEC.md):
   - Personal healthcare intelligence principles: clear distinction between source information, clinician-confirmed facts, and AI-derived reasoning; safe representation of uncertainty.
3. [`docs/DESIGN.md`](file:///d:/Personal%20Projects/Personal%20HealthCare/docs/DESIGN.md):
   - Longitudinal by design: health data preserves time context and deterministic provenance.
4. [`AGENTS.md`](file:///d:/Personal%20Projects/Personal%20HealthCare/AGENTS.md):
   - Scope discipline: never modify production code to make evaluation harnesses pass; preserve architectural boundaries.

---

## 3. M5 Harness Reuse vs. Extension Analysis

The frozen M5 evaluation harness (`backend/tests/eval/m5_benchmark_corpus.py` and `backend/tests/eval/test_m5_evaluation.py`) serves as the foundation for M6 S6.

### 3.1 Harness Architecture Comparison
| Dimension | M5 Harness (`test_m5_evaluation.py`) | M6 Harness (`test_m6_evaluation.py` + `test_m6_invariants.py`) | Architectural Rationale |
| :--- | :--- | :--- | :--- |
| **Corpus Size** | Exactly 54 cases | Exactly 70 cases (54 M5 + 16 M6) | Preserves all historical baseline cases while adding Categories 10–13. |
| **Corpus Schema** | `BenchmarkTestCase` (14 fields) | Extended `BenchmarkTestCase` (16 fields: adds `expected_superlative`, `expected_question_intent`) | Additive fields default to `None` and `"QUERY"`, maintaining 100% backward compatibility with M5 cases. |
| **Categories** | 9 locked categories | 13 locked categories (adds Superlative-Latest, Superlative-First, Timeline-Intent, Cross-Time-Comparison) | Explicit coverage for all M6 query understanding capabilities. |
| **Layer 1 Conformance** | Asserts 10 parser fields for 50 cases | Asserts up to 12 parser fields across all 70 cases (authoritative fields per case) | Validates S1 superlative, timeline, and comparison extraction without asserting non-authoritative fields on legacy cases. |
| **Layer 2 Conformance** | Pure 7-case fusion truth table, anti-misattribution, temporal window filtering | Pure longitudinal trajectory selection ($N \le 3$, $K \le 4$), Sec 7.3 cross-domain reconciliation, timeline evidence evaluation, attribute-aware passage allocation | Evaluates M6 pure logic functions directly without requiring live PostgreSQL database. |
| **Layer 3 Conformance** | 6 async orchestrator invariants via `httpx.AsyncClient` with `mock_dependencies` | 8+ async orchestrator invariants: adds timeline UUID5 citations, cross-domain trajectory synthesis, and exact bounded qualifier emission | Exercises end-to-end API pipeline with deterministic mocked LLM and context. |
| **Invariant Suite** | Embedded inside `test_m5_evaluation.py` | Separate dedicated module: `backend/tests/eval/test_m6_invariants.py` | Isolates algorithmic property-based and adversarial stress testing from golden fixed-case benchmark reporting. |
| **Inherited Debt** | Recorded M1 & M4 legacy failures | Records exact same M1 & M4 legacy failures, plus execution context guidelines | Complete continuity of tracked debt. |

### 3.2 What M6 Harness Reuses Verbatim
1. **The 54 M5 Benchmark Cases**: Reused verbatim in `m6_benchmark_corpus.py` without modifying queries, categories, or expected ground-truth fields.
2. **`mock_dependencies` Fixture Pattern**: Reused in Layer 3 for mocking `get_or_create_patient`, `build_inquiry_context`, `retrieve_document_passages`, and `get_llm_gateway`.
3. **Pure Execution Model**: Layers 1 and 2 remain pure, CPU-bound, in-memory evaluations executing in under 200 milliseconds.
4. **Deterministic Repeatability Technique**: Reuses the 3-run identical-output assertion under fixed reference datetime (`FIXED_REF_DATETIME`).

### 3.3 What Would Become Stale / Incorrect if Blindly Copied
1. **Strict 50-case count assertions in Layer 1**: M5 asserted `len(parser_cases) == 50`. M6 Layer 1 asserts `len(parser_cases) == 66` (70 total minus 4 safety triggers).
2. **Ignoring Superlative and Intent in Parser Assertions**: Copying M5's `test_layer1_parser_conformance` loop without checking `target.temporal_constraint.superlative` and `target.question_intent` on the 16 M6 cases would leave M6 query understanding unverified.
3. **Omitting Timeline from Structured Context**: In M5 Layer 3, `StructuredHealthContext()` lacked timeline events. M6 Layer 3 must include `recent_timeline_events` to verify timeline citation emission.
4. **Assuming Single-Date Evidence**: M5 Layer 2 only tested single-date evidence fusion. M6 Layer 2 must test multi-date longitudinal trajectories and Section 7.3 reconciliation.

---

## 4. Locked S6 Corpus Specification (`m6_benchmark_corpus.py`)

### 4.1 Corpus Arithmetic
The M6 benchmark corpus consists of **EXACTLY 70 cases**:

$$\text{Total Corpus} = 54\ (\text{M5 Baseline}) + 4\ (\text{SUP-Latest}) + 4\ (\text{SUP-First}) + 4\ (\text{TML-Timeline}) + 4\ (\text{CMP-Comparison}) = 70$$

```text
┌────────────────────────────────────────────────────────┬────────────┬────────────────────────┐
│ Category                                               │ Case Count │ Canonical ID Range     │
├────────────────────────────────────────────────────────┼────────────┼────────────────────────┤
│ Category 1: Explicit-Domain Queries                    │ 6 cases    │ EXP-01 through EXP-06  │
│ Category 2: Implicit-Document Queries                  │ 6 cases    │ IMP-01 through IMP-06  │
│ Category 3: Provider / Physician Queries               │ 6 cases    │ PRV-01 through PRV-06  │
│ Category 4: Structured Entity Synonyms                 │ 6 cases    │ SYN-01 through SYN-06  │
│ Category 5: Cross-Domain Coexistence Queries           │ 6 cases    │ CRS-01 through CRS-06  │
│ Category 6: Specific-Attribute Extraction Queries      │ 6 cases    │ ATT-01 through ATT-06  │
│ Category 7: Ambiguous / Underspecified Queries         │ 4 cases    │ AMB-01 through AMB-04  │
│ Category 8: Unroutable / Non-Medical Queries           │ 2 cases    │ UNR-01 through UNR-02  │
│ Category 9: Temporal-Interval Grounding Queries        │ 8 cases    │ TMP-01 through TMP-08  │
│ Category 10: Superlative Queries (Latest/Newest)       │ 4 cases    │ SUP-01 through SUP-04  │
│ Category 11: Superlative Queries (First/Earliest)      │ 4 cases    │ SUP-05 through SUP-08  │
│ Category 12: Timeline Intent Inquiries                 │ 4 cases    │ TML-01 through TML-04  │
│ Category 13: Cross-Time Comparison Inquiries           │ 4 cases    │ CMP-01 through CMP-04  │
│ Category 14: Safety Precedence Invariants (from M5)    │ 4 cases    │ SAF-01 through SAF-04  │
├────────────────────────────────────────────────────────┼────────────┼────────────────────────┤
│ TOTAL LOCKED M6 BENCHMARK CORPUS                       │ 70 cases   │ Exactly 70 Cases       │
└────────────────────────────────────────────────────────┴────────────┴────────────────────────┘
```
> **Crucial Corpus Arithmetic Clarification**: Category 14 is a logical safety subset of the 54 preserved M5 cases and is not additive to the 70-case corpus. Therefore it must not be included in the arithmetic `54 + 16`. The corpus contains exactly 70 unique `BenchmarkTestCase` entries ($54\ \text{M5 baseline} + 16\ \text{M6 locked cases} = 70$).

### 4.2 BenchmarkTestCase Schema Definition
```python
from datetime import date
from typing import Optional
from pydantic import BaseModel, Field

from app.schemas.inquiry import RoutingMode, SuperlativeType, TemporalScope


class BenchmarkTestCase(BaseModel):
    """Authoritative schema for all 70 benchmark evaluation cases."""
    case_id: str                              # Unique canonical ID (e.g. "EXP-01", "SUP-01")
    category: str                             # Canonical category string
    query: str                                # Exact natural-language query string
    expected_routing_mode: RoutingMode        # Expected router classification
    expected_structured_domains: list[str] = Field(default_factory=list)
    expected_document_domains: list[str] = Field(default_factory=list)
    expected_target_entity: Optional[str] = None
    expected_attributes: list[str] = Field(default_factory=list)
    expected_temporal_scope: TemporalScope = TemporalScope.ALL
    expected_anchor_year: Optional[int] = None
    expected_start_date: Optional[date] = None
    expected_end_date: Optional[date] = None
    expected_clarification_required: bool = False
    is_safety_trigger: bool = False
    # M6 Additive Fields (defaulted for M5 compatibility):
    expected_superlative: Optional[SuperlativeType] = None
    expected_question_intent: str = "QUERY"
```

### 4.3 Detailed Specification of the 16 New Locked M6 Cases
All 16 ground truth specifications below reflect the **exact canonical parser output** produced by `backend/app/health/query_understanding.py`:

#### Category 10: Superlative Queries — Latest/Newest (4 cases)
1. **`SUP-01`**:
   - `query`: `"What is my latest cholesterol?"`
   - `category`: `"Superlative-Latest"`
   - `expected_routing_mode`: `RoutingMode.DOCUMENT_ONLY`
   - `expected_structured_domains`: `[]`
   - `expected_document_domains`: `["labs"]`
   - `expected_target_entity`: `"Cholesterol"` *(Exact canonical entity from ANALYTE_ENTITIES)*
   - `expected_attributes`: `[]`
   - `expected_temporal_scope`: `TemporalScope.ALL`
   - `expected_superlative`: `SuperlativeType.LATEST`
   - `expected_question_intent`: `"QUERY"`
2. **`SUP-02`**:
   - `query`: `"What is my newest prescription?"`
   - `category`: `"Superlative-Latest"`
   - `expected_routing_mode`: `RoutingMode.DOCUMENT_ONLY`
   - `expected_structured_domains`: `[]`
   - `expected_document_domains`: `["prescriptions"]`
   - `expected_target_entity`: `None`
   - `expected_attributes`: `[]`
   - `expected_temporal_scope`: `TemporalScope.ALL`
   - `expected_superlative`: `SuperlativeType.LATEST`
   - `expected_question_intent`: `"QUERY"`
3. **`SUP-03`**:
   - `query`: `"What is my latest blood pressure reading?"`
   - `category`: `"Superlative-Latest"`
   - `expected_routing_mode`: `RoutingMode.DOCUMENT_ONLY`
   - `expected_structured_domains`: `[]`
   - `expected_document_domains`: `["clinical_documents", "reports"]`
   - `expected_target_entity`: `"blood pressure"` *(Exact canonical entity from VITAL_ENTITIES)*
   - `expected_attributes`: `[]`
   - `expected_temporal_scope`: `TemporalScope.ALL`
   - `expected_superlative`: `SuperlativeType.LATEST`
   - `expected_question_intent`: `"QUERY"`
4. **`SUP-04`**:
   - `query`: `"What was my latest lab report in 2024?"`
   - `category`: `"Superlative-Latest"`
   - `expected_routing_mode`: `RoutingMode.DOCUMENT_ONLY`
   - `expected_structured_domains`: `[]`
   - `expected_document_domains`: `["clinical_documents", "labs", "reports"]` *(Deterministic multi-domain union: "lab" -> labs, "report" -> reports, clinical_documents, matching EXP-06)*
   - `expected_target_entity`: `None`
   - `expected_attributes`: `[]`
   - `expected_temporal_scope`: `TemporalScope.INTERVAL`
   - `expected_anchor_year`: `2024`
   - `expected_start_date`: `date(2024, 1, 1)`
   - `expected_end_date`: `date(2024, 12, 31)`
   - `expected_superlative`: `SuperlativeType.LATEST`
   - `expected_question_intent`: `"QUERY"`

#### Category 11: Superlative Queries — First/Earliest (4 cases)
5. **`SUP-05`**:
   - `query`: `"What was my first diagnosed condition?"`
   - `category`: `"Superlative-First"`
   - `expected_routing_mode`: `RoutingMode.CROSS_DOMAIN`
   - `expected_structured_domains`: `["conditions"]`
   - `expected_document_domains`: `["clinical_documents"]`
   - `expected_target_entity`: `None`
   - `expected_attributes`: `[]`
   - `expected_temporal_scope`: `TemporalScope.ALL` *(Superlative overrides "diagnosed" historical scope to ALL)*
   - `expected_superlative`: `SuperlativeType.FIRST`
   - `expected_question_intent`: `"QUERY"`
6. **`SUP-06`**:
   - `query`: `"What was my earliest recorded medication?"`
   - `category`: `"Superlative-First"`
   - `expected_routing_mode`: `RoutingMode.CROSS_DOMAIN`
   - `expected_structured_domains`: `["medications"]`
   - `expected_document_domains`: `["prescriptions"]`
   - `expected_target_entity`: `None`
   - `expected_attributes`: `[]`
   - `expected_temporal_scope`: `TemporalScope.ALL`
   - `expected_superlative`: `SuperlativeType.FIRST`
   - `expected_question_intent`: `"QUERY"`
7. **`SUP-07`**:
   - `query`: `"What was my first blood pressure measurement?"`
   - `category`: `"Superlative-First"`
   - `expected_routing_mode`: `RoutingMode.DOCUMENT_ONLY`
   - `expected_structured_domains`: `[]`
   - `expected_document_domains`: `["clinical_documents", "reports"]`
   - `expected_target_entity`: `"blood pressure"` *(Exact canonical entity from VITAL_ENTITIES)*
   - `expected_attributes`: `[]`
   - `expected_temporal_scope`: `TemporalScope.ALL`
   - `expected_superlative`: `SuperlativeType.FIRST`
   - `expected_question_intent`: `"QUERY"`
8. **`SUP-08`**:
   - `query`: `"What was my first lab test in 2023?"`
   - `category`: `"Superlative-First"`
   - `expected_routing_mode`: `RoutingMode.DOCUMENT_ONLY`
   - `expected_structured_domains`: `[]`
   - `expected_document_domains`: `["labs"]`
   - `expected_target_entity`: `None`
   - `expected_attributes`: `[]`
   - `expected_temporal_scope`: `TemporalScope.INTERVAL`
   - `expected_anchor_year`: `2023`
   - `expected_start_date`: `date(2023, 1, 1)`
   - `expected_end_date`: `date(2023, 12, 31)`
   - `expected_superlative`: `SuperlativeType.FIRST`
   - `expected_question_intent`: `"QUERY"`

#### Category 12: Timeline Intent Inquiries (4 cases)
9. **`TML-01`**:
   - `query`: `"Show my health timeline"`
   - `category`: `"Timeline-Intent"`
   - `expected_routing_mode`: `RoutingMode.STRUCTURED_ONLY`
   - `expected_structured_domains`: `["timeline"]`
   - `expected_document_domains`: `[]`
   - `expected_target_entity`: `None`
   - `expected_attributes`: `[]`
   - `expected_temporal_scope`: `TemporalScope.ALL`
   - `expected_superlative`: `None`
   - `expected_question_intent`: `"QUERY"`
10. **`TML-02`**:
    - `query`: `"What events happened in 2024?"`
    - `category`: `"Timeline-Intent"`
    - `expected_routing_mode`: `RoutingMode.CROSS_DOMAIN`
    - `expected_structured_domains`: `["timeline"]`
    - `expected_document_domains`: `["clinical_documents", "labs", "reports"]`
    - `expected_target_entity`: `None`
    - `expected_attributes`: `[]`
    - `expected_temporal_scope`: `TemporalScope.INTERVAL`
    - `expected_anchor_year`: `2024`
    - `expected_start_date`: `date(2024, 1, 1)`
    - `expected_end_date`: `date(2024, 12, 31)`
    - `expected_superlative`: `None`
    - `expected_question_intent`: `"QUERY"`
11. **`TML-03`**:
    - `query`: `"When was my doctor consultation?"`
    - `category`: `"Timeline-Intent"`
    - `expected_routing_mode`: `RoutingMode.CROSS_DOMAIN`
    - `expected_structured_domains`: `["timeline"]`
    - `expected_document_domains`: `["clinical_documents", "reports"]`
    - `expected_target_entity`: `"consultation"` *(Exact canonical entity from consultation timeline anchor)*
    - `expected_attributes`: `[]`
    - `expected_temporal_scope`: `TemporalScope.ALL`
    - `expected_superlative`: `None`
    - `expected_question_intent`: `"QUERY"`
12. **`TML-04`**:
    - `query`: `"What was my timeline for Asthma?"`
    - `category`: `"Timeline-Intent"`
    - `expected_routing_mode`: `RoutingMode.CROSS_DOMAIN`
    - `expected_structured_domains`: `["conditions", "timeline"]`
    - `expected_document_domains`: `["clinical_documents"]`
    - `expected_target_entity`: `"Asthma"` *(Exact canonical entity from CONDITION_ENTITIES)*
    - `expected_attributes`: `[]`
    - `expected_temporal_scope`: `TemporalScope.ALL`
    - `expected_superlative`: `None`
    - `expected_question_intent`: `"QUERY"`

#### Category 13: Cross-Time Comparison Inquiries (4 cases)
13. **`CMP-01`**:
    - `query`: `"How has my cholesterol changed over time?"`
    - `category`: `"Cross-Time-Comparison"`
    - `expected_routing_mode`: `RoutingMode.DOCUMENT_ONLY`
    - `expected_structured_domains`: `[]`
    - `expected_document_domains`: `["labs"]`
    - `expected_target_entity`: `"Cholesterol"` *(Exact canonical entity from ANALYTE_ENTITIES)*
    - `expected_attributes`: `[]`
    - `expected_temporal_scope`: `TemporalScope.ALL`
    - `expected_superlative`: `None`
    - `expected_question_intent`: `"COMPARISON"`
14. **`CMP-02`**:
    - `query`: `"Compare my blood test results between 2023 and 2025"`
    - `category`: `"Cross-Time-Comparison"`
    - `expected_routing_mode`: `RoutingMode.DOCUMENT_ONLY`
    - `expected_structured_domains`: `[]`
    - `expected_document_domains`: `["labs"]`
    - `expected_target_entity`: `None`
    - `expected_attributes`: `[]`
    - `expected_temporal_scope`: `TemporalScope.INTERVAL`
    - `expected_anchor_year`: `None`
    - `expected_start_date`: `date(2023, 1, 1)`
    - `expected_end_date`: `date(2025, 12, 31)`
    - `expected_superlative`: `None`
    - `expected_question_intent`: `"COMPARISON"`
15. **`CMP-03`**:
    - `query`: `"How did my blood pressure change?"`
    - `category`: `"Cross-Time-Comparison"`
    - `expected_routing_mode`: `RoutingMode.DOCUMENT_ONLY`
    - `expected_structured_domains`: `[]`
    - `expected_document_domains`: `["clinical_documents", "reports"]`
    - `expected_target_entity`: `"blood pressure"` *(Exact canonical entity from VITAL_ENTITIES)*
    - `expected_attributes`: `[]`
    - `expected_temporal_scope`: `TemporalScope.ALL`
    - `expected_superlative`: `None`
    - `expected_question_intent`: `"COMPARISON"`
16. **`CMP-04`**:
    - `query`: `"Compare my medication dosage over time"`
    - `category`: `"Cross-Time-Comparison"`
    - `expected_routing_mode`: `RoutingMode.CROSS_DOMAIN`
    - `expected_structured_domains`: `["medications"]`
    - `expected_document_domains`: `["prescriptions"]`
    - `expected_target_entity`: `None`
    - `expected_attributes`: `["dosage"]`
    - `expected_temporal_scope`: `TemporalScope.ALL`
    - `expected_superlative`: `None`
    - `expected_question_intent`: `"COMPARISON"`

### 4.4 Corpus Inspection Helpers
`backend/tests/eval/m6_benchmark_corpus.py` exports the following typed helper functions:
- `get_case_by_id(case_id: str) -> Optional[BenchmarkTestCase]`
- `get_cases_by_category(category: str) -> tuple[BenchmarkTestCase, ...]`
- `get_parser_benchmark_cases() -> tuple[BenchmarkTestCase, ...]` (All 66 non-safety cases)
- `get_safety_cases() -> tuple[BenchmarkTestCase, ...]` (The 4 safety cases: `SAF-01`..`SAF-04`)
- `get_superlative_cases() -> tuple[BenchmarkTestCase, ...]` (The 8 superlative cases: `SUP-01`..`SUP-08`)
- `get_timeline_cases() -> tuple[BenchmarkTestCase, ...]` (The 4 timeline cases: `TML-01`..`TML-04`)
- `get_comparison_cases() -> tuple[BenchmarkTestCase, ...]` (The 4 comparison cases: `CMP-01`..`CMP-04`)
- `get_normal_routable_cases() -> tuple[BenchmarkTestCase, ...]` (All 58 normal routable cases)
- `get_ambiguous_cases() -> tuple[BenchmarkTestCase, ...]` (The 4 ambiguous cases: `AMB-01`..`AMB-04`)
- `get_valid_temporal_cases() -> tuple[BenchmarkTestCase, ...]` (Valid interval cases across M5 + M6)

---

## 5. Three-Layer M6 Evaluation Harness (`test_m6_evaluation.py`)

`backend/tests/eval/test_m6_evaluation.py` implements the three-layer deterministic evaluation harness.

### 5.1 Layer 1: Query Understanding Conformance
- **Function**: `test_layer1_parser_conformance()`
- **Execution**: Evaluates all 66 non-safety benchmark cases through `parse_natural_language_query(case.query)`.
- **Clock Pinning**: Pinned via `with patch("app.health.query_understanding.datetime") as mock_dt: mock_dt.now.return_value = FIXED_REF_DATETIME`.
- **Assertion Rules**:
  - For `TMP-07` and `TMP-08` (fail-closed impossible dates): asserts `routing_mode == UNROUTABLE` and `not clarification_required`.
  - For standard cases: asserts exact match on `routing_mode`, `sorted(candidate_structured_domains)`, `sorted(candidate_document_domains)`, `target_entity`, `sorted(requested_attributes)`, `temporal_constraint.scope`, `temporal_constraint.anchor_year`, `temporal_constraint.start_date`, `temporal_constraint.end_date`, and `clarification_required`.
  - For M6 cases (`SUP-01..08`, `TML-01..04`, `CMP-01..04`): additionally asserts `temporal_constraint.superlative == case.expected_superlative` and `question_intent == case.expected_question_intent`.
- **Metric Gates**:
  - `routing_conformance_count == 66/66` (100%)
  - `false_unroutable_count == 0`
  - `clarification_recall_count == 4/4` (100%)
  - `clarification_total_triggered == 4` (100% precision)
  - `false_clarification_count == 0`
  - `superlative_conformance_count == 8/8` (100%)
  - `comparison_conformance_count == 4/4` (100%)
  - `timeline_routing_conformance_count == 4/4` (100%)
- **Deterministic Repeatability**: `test_eval_deterministic_repeatability()` executes all 70 cases 3 times and asserts `res1 == res2 == res3`.

### 5.2 Layer 2: Evidence / Retrieval / Fusion Conformance
- **Function**: Pure CPU unit tests exercising `evidence_evaluator.py`, `evidence_fusion.py`, and `sanitized_context.py` using synthetic fixtures:
  1. `test_layer2_m5_fusion_truth_table_preservation()`: Re-verifies the 7 M5 truth-table cases (complementary sufficiency, structured dominant, document dominant, partial, uncorroborated, absent everywhere, attribute absent).
  2. `test_layer2_timeline_evidence_evaluation()`: Verifies `evaluate_timeline_evidence()` with matching entity/attributes, interval bounds, and superlative filtering.
  3. `test_layer2_superlative_chronological_extremity()`: Verifies that under `superlative == LATEST`, the newest qualified passage is selected; under `FIRST`, the oldest qualified passage is selected.
  4. `test_layer2_undated_evidence_disqualification()`: Verifies that passages with `document_date IS NULL` and timeline events with `DOCUMENT_UPLOADED` or missing dates cannot win a dated superlative.
  5. `test_layer2_longitudinal_trajectory_milestone_selection()`: Verifies that `select_longitudinal_milestones()` correctly picks Baseline (oldest), Intermediate (newest intermediate), and Latest (newest) when $\ge 3$ distinct dates exist.
  6. `test_layer2_attribute_aware_passage_budget()`: Verifies that `allocate_attribute_aware_milestone_passages()` bounds total passages to $K \le 4$ and prioritizes passages matching requested attributes.
  7. `test_layer2_cross_domain_superlative_reconciliation()`: Verifies Section 7.3 cross-domain reconciliation: newer clinical date wins regardless of whether it originates from structured records or document passages, with deterministic `STRUCTURED` priority on same-date ties.
  8. `test_layer2_trajectory_completeness_qualifier_contract()`: Verifies that when distinct evaluated candidate dates exceed selected milestone dates, `trajectory_completeness` is set to `BOUNDED_WITH_ADDITIONAL_QUALIFIED_CANDIDATES` and the exact locked qualifier string is injected.

### 5.3 Layer 3: API / Orchestrator Conformance
- **Function**: Async integration tests using `httpx.AsyncClient` with `mock_dependencies` covering orchestrator invariants:
  1. `test_layer3_safety_precedence()`: Safety queries (`SAF-01`..`SAF-04`) short-circuit at Step 1 with 0 DB queries and 0 LLM calls.
  2. `test_layer3_ambiguity_unroutable_zero_database_access()`: Ambiguous and unroutable queries short-circuit at Step 2 with 0 DB and 0 LLM access.
  3. `test_layer3_domain_isolation()`: `DOCUMENT_ONLY` queries skip `build_inquiry_context()` (`m_ctx.call_count == 0`); `STRUCTURED_ONLY` queries skip `retrieve_document_passages()` (`m_ret.call_count == 0`).
  4. `test_layer3_timeline_citation_provenance()`: When timeline events are cited, verifies that `entity_type == "TIMELINE"` citations are emitted with stable UUID5 identities (`record_id == generate_timeline_event_id(...)`).
  5. `test_layer3_cross_domain_trajectory_synthesis()`: Submits a comparative inquiry (`"How has my asthma changed over time?"`), verifies that both structured conditions and document passages are passed to sanitized context in strict chronological order with `[DOC-N]` tokens.
  6. `test_layer3_bounded_qualifier_delivery()`: When bounded trajectory completeness is triggered, verifies the response answer contains the complete, exact locked qualifier:
     ```text
     Note: This summary highlights key milestone dates (Baseline, Intermediate, and Latest). Additional qualified dated candidates were identified in the evaluated evidence set and are not shown in this summary.
     ```
     *(The test must assert exact character-for-character equality with `BOUNDED_TRAJECTORY_QUALIFIER`, failing if any character or word is modified).*
  7. `test_layer3_comparison_zero_date_llm_bypass()`: Permanently preserves the frozen S4 Step 7.5 behavior in the M6 evaluation harness. Submits a comparative inquiry (e.g. `"How has my cholesterol changed over time?"`) against a mocked context containing zero dated clinical records. Asserts:
     - `question_intent == "COMPARISON"`
     - `evidence_status == EvidenceStatus.INSUFFICIENT`
     - `answer == "No clinically dated records were found to compare changes over time."`
     - `citations == []`
     - `mock_llm.embed_or_generate call_count == 0` (LLM provider completely bypassed)
     Uses the existing S6 `mock_dependencies` pattern without introducing new production behavior or modifying the frozen S4 zero-date directive.
  8. `test_layer3_tenant_isolation_boundary()`: Verifies that candidates retrieved with foreign `patient_id` are completely rejected and omitted from evidence and citations.
  9. `test_layer3_fail_closed_subsystem_errors()`: Unhandled database or retrieval exceptions yield safe 500 error responses without leaking internal traces.

---

## 6. Adversarial Invariant Suite Specification (`test_m6_invariants.py`)

`backend/tests/eval/test_m6_invariants.py` is a dedicated validation layer that stresses ordering, qualification, and boundary properties across arbitrary candidate sets, synthetic dates, and adversarial permutations.

### 6.1 Testing Methodology
- Uses standard deterministic `pytest` mechanisms (`@pytest.mark.parametrize`, deterministic fixtures, fixed random seeds `random.Random(42)`).
- **Hypothesis is NOT used**. Zero new dependencies.
- Every test runs multiple controlled permutations to prove order invariance.

### 6.2 The 12 Locked Invariant Specifications

```text
┌────┬─────────────────────────────────────────────────┬────────────────────────────────────────────────────────┐
│ #  │ Invariant Name                                  │ Core Assertion & Property Guarantee                    │
├────┼─────────────────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ 1  │ LATEST Selection Invariant                      │ selected_latest.date == max(q.date for q in Q)         │
│ 2  │ FIRST Selection Invariant                       │ selected_first.date == min(q.date for q in Q)          │
│ 3  │ Upload Date Disqualification Invariant          │ DOCUMENT_UPLOADED / uploaded_at cannot win superlative │
│ 4  │ Tenant Isolation Invariant                      │ candidate.patient_id == authenticated_patient_id       │
│ 5  │ Deterministic Tie-Breaking Invariant            │ Same dates -> deterministic doc_id/chunk_index sort    │
│ 6  │ Undated Exclusion Invariant                     │ Undated records never defeat dated records             │
│ 7  │ Bounded Trajectory Policy Invariant             │ Milestone dates N <= 3; passage budget K <= 4          │
│ 8  │ Deterministic Union Deduplication Invariant     │ |C_dense U C_lexical| <= 20; zero duplicate chunk IDs  │
│ 9  │ Qualification-Precedes-Ranking Invariant        │ Uncorroborated newer chunk disqualified before sort    │
│ 10 │ Adversarial Hybrid-Recall Recency Invariant     │ Dense-blind newest/oldest recovered via lexical path   │
│ 11 │ Token-Structure Boundary Invariant              │ "bp" != "RBP"; "chol" != "cholecystectomy"             │
│ 12 │ Literal Regex Metacharacter Escaping Invariant  │ "a.b" matches literal "a.b", not "axb" (no wildcard)   │
└────┴─────────────────────────────────────────────────┴────────────────────────────────────────────────────────┘
```

#### Invariant 1: LATEST Selection Invariant
- **Fixture Shape**: Synthetic candidate pool of 5 passages with clinical dates `[2021-03-01, 2023-07-15, 2025-11-20, 2022-01-10, 2024-05-12]`.
- **Operation**: `evaluate_passage_evidence()` with `superlative = SuperlativeType.LATEST`.
- **Expected Invariant**: Selected winning milestone passage date strictly equals `date(2025, 11, 20)`.
- **Adversarial Permutations**: Candidate pool shuffled across 10 deterministic random permutations; in all 10 permutations, the winning date is identical.
- **Failure Interpretation**: Chronological ranking is sensitive to input retrieval order or sorting key is inverted.

#### Invariant 2: FIRST Selection Invariant
- **Fixture Shape**: Same synthetic candidate pool of 5 passages.
- **Operation**: `evaluate_passage_evidence()` with `superlative = SuperlativeType.FIRST`.
- **Expected Invariant**: Selected winning milestone passage date strictly equals `date(2021, 3, 1)`.
- **Adversarial Permutations**: Shuffled across 10 deterministic permutations; winning date remains invariant.
- **Failure Interpretation**: Ascending sort logic inverted or fails to sort.

#### Invariant 3: Upload Date Disqualification Invariant
- **Fixture Shape**:
  - Candidate A: Timeline event with `event_type = "DOCUMENT_UPLOADED"`, `event_date = "2026-01-01"`.
  - Candidate B: Clinical condition with `event_type = "CONDITION_STARTED"`, `event_date = "2023-05-10"`.
- **Operation**: `extract_canonical_clinical_date()` and `evaluate_timeline_evidence()` under `LATEST`.
- **Expected Invariant**: Candidate A extracts `clinical_date = None` and is disqualified; Candidate B wins with date `2023-05-10`.
- **Failure Interpretation**: Administrative upload timestamp leaked into clinical chronological ranking.

#### Invariant 4: Tenant Isolation Invariant
- **Fixture Shape**: Retrieval candidate set containing 3 passages for `patient_A` and 2 passages for `patient_B`.
- **Operation**: `evaluate_passage_evidence(..., requesting_patient_id=patient_A)` exercising existing parameter.
- **Expected Invariant**: If any candidate passage or retrieval result belongs to a mismatched `patient_id` (`patient_B`), the existing tenant integrity gate immediately triggers fail-closed, returning `EvidenceStatus.INSUFFICIENT` with empty qualified passages; when evaluated with strictly isolated `patient_A` passages, qualification proceeds safely.
- **Failure Interpretation**: Cross-tenant data leakage in evaluation or retrieval layer.

#### Invariant 5: Deterministic Tie-Breaking Invariant
- **Fixture Shape**: 4 passages sharing the exact same date `2024-06-15`, with distinct `(document_id, chunk_index)`.
- **Operation**: `evaluate_passage_evidence()` under `LATEST` across 8 different input sequence permutations.
- **Expected Invariant**: The resulting qualified passage list is identical across all 8 permutations, ordered strictly by `(document_id ASC, chunk_index ASC)`.
- **Failure Interpretation**: Unstable sort or arbitrary database-return-order dependency.

#### Invariant 6: Undated Exclusion Invariant
- **Fixture Shape**:
  - Candidate 1: Dated passage `2022-01-01`.
  - Candidate 2: Undated passage (`document_date = None`).
  - Candidate 3: All candidates undated (`document_date = None`).
- **Operation**: `evaluate_passage_evidence()` under `LATEST`.
- **Expected Invariant**:
  - In mixed set: Candidate 1 wins. Candidate 2 cannot win.
  - In all-undated set: Returns `EvidenceStatus.PARTIALLY_SUFFICIENT` with date-absence directive: `"Records were found, but lack documented clinical dates..."`. Refuses to assert chronological certainty.
- **Failure Interpretation**: Undated record arbitrarily selected as newest, or system fabricates certainty without dates.

#### Invariant 7: Bounded Longitudinal Trajectory Policy Invariant
- **Fixture Shape**: Synthetic candidate set with 6 distinct clinical dates: `[2020-01-01, 2021-02-01, 2022-03-01, 2023-04-01, 2024-05-01, 2025-06-01]`.
- **Operation**: `select_longitudinal_milestones()` and `allocate_attribute_aware_milestone_passages()`.
- **Expected Invariant**:
  - Selected milestone points: Exactly 3: Baseline (`2020-01-01`), Intermediate (`2024-05-01` - newest intermediate), Latest (`2025-06-01`).
  - Allocated passages: Total count $K \le 4$.
- **Failure Interpretation**: Milestones exceed $N=3$ or passage allocation exceeds $K=4$.

#### Invariant 8: Deterministic Union Deduplication Invariant
- **Fixture Shape**: $\mathcal{C}_{\text{dense}}$ of 10 chunks, $\mathcal{C}_{\text{lexical}}$ of 10 chunks, with 4 overlapping chunk IDs.
- **Operation**: Candidate union and deduplication via `(chunk_id)`.
- **Expected Invariant**: Deduplicated union $|\mathcal{U}| == 16$. Zero duplicate chunk IDs. Order invariant under union order ($\mathcal{C}_{\text{dense}} \cup \mathcal{C}_{\text{lexical}} == \mathcal{C}_{\text{lexical}} \cup \mathcal{C}_{\text{dense}}$).
- **Failure Interpretation**: Duplicate chunks retained or union size exceeds bounded candidate universe ($|\mathcal{U}| \le 20$).

#### Invariant 9: Qualification-Precedes-Ranking Invariant
- **Fixture Shape**:
  - Passage A: Dated `2025-01-01`, text: `"Patient visited optometrist for routine eye exam."` (Does NOT corroborate Cholesterol).
  - Passage B: Dated `2022-06-15`, text: `"Total Cholesterol: 195 mg/dL. HDL: 50."` (Corroborates Cholesterol).
- **Operation**: `evaluate_passage_evidence(target_entity="Cholesterol", superlative=LATEST)`.
- **Expected Invariant**: Passage A is disqualified during entity qualification. Passage B wins despite older date.
- **Failure Interpretation**: Chronological ranking performed before qualification, allowing an uncorroborated newer passage to win.

#### Invariant 10: Adversarial Hybrid-Recall Recency Invariant (Validation Extension)
> **Operational Boundary Clarification**: Invariant 10 validates recency correctness after the deterministic hybrid candidate union has been formed. It does not independently validate PostgreSQL lexical-retrieval execution. SQL retrieval-path correctness remains covered by the frozen M6 S2 retrieval tests.
- **Scenario 10a (Dense-Blind LATEST Recovery)**:
  - **Setup**: Construct a synthetic candidate universe representing the result of dense + lexical union. Place 10 older passages (2020–2023) in the simulated dense top-10, and place the true newest candidate $P_{\text{newest}}$ (`2026-03-01`) outside the simulated dense top-10 but inside the simulated lexical-recall result.
  - **Invariant**: Evaluator qualification and recency ranking select $P_{\text{newest}}$ as the newest qualified candidate.
- **Scenario 10b (Dense-Blind FIRST Recovery)**:
  - **Setup**: Construct the analogous synthetic union for FIRST. Place the true oldest candidate $P_{\text{oldest}}$ (`2017-05-10`) outside simulated dense recall but inside simulated lexical recall.
  - **Invariant**: Evaluator qualification and recency ranking select $P_{\text{oldest}}$ as the oldest qualified candidate.
*(Note: This test operates on synthetic in-memory fixtures; it does not claim to prove SQL lexical retrieval itself, does not call the live database, and does not modify `retrieval.py`).*

#### Invariant 11: Lexical Recall Precision / Token-Structure Boundary Invariant (Validation Extension)
- **Scenario 11a (Short Token / BP)**:
  - Passage text: `"Serum RBP levels measured at 45 mcg/mL."`
  - Invariant: Single-token variant `"bp"` does NOT match `"RBP"`. Passage fails whole-token boundary check (`\m bp \M`) and is excluded from lexical recall and entity qualification.
- **Scenario 11b (Prefix / Cholesterol)**:
  - Passage text: `"Patient scheduled for elective laparoscopic cholecystectomy."`
  - Invariant: Single-token variant `"chol"` does NOT match `"cholecystectomy"`. Excluded from lexical recall and entity qualification.

#### Invariant 12: Literal Regex Metacharacter Escaping Invariant (Validation Extension)
- **Scenario 12a (Curated Variant with Metacharacters)**:
  - Single-token variant `"a.b"`. Passage 1: `"a.b normal"`; Passage 2: `"axb normal"`.
  - Invariant: Passage 1 matches; Passage 2 does NOT match. Proves `.` was escaped as a literal character and did not act as a regex wildcard.
- **Scenario 12b (Fallback Entity with Metacharacters)**:
  - Single-word fallback entity `"c+d"`. Passage 1: `"c+d present"`; Passage 2: `"cccd present"`.
  - Invariant: Passage 1 matches; Passage 2 does NOT match. Proves `+` was escaped as a literal character.

---

## 7. Tenant Isolation Verification Architecture

> **Authoritative Architectural Mandate**: S6 validates the existing tenant-isolation contract at its current enforcement layer and introduces no new production filtering or function parameters.

### 7.1 Two-Layer Enforcement Architecture in Codebase
Inspection of the current implementation confirms the two distinct enforcement layers:

1. **Primary Tenant Boundary (Database Query Scoping)**:
   - In `backend/app/health/retrieval.py`: Both dense pgvector queries and lexical queries enforce `DocumentChunk.patient_id == patient_id` and `MedicalDocument.patient_id == patient_id` in SQL `WHERE` predicates. Cross-tenant candidate retrieval is mathematically impossible at the database query level.
   - In `backend/app/health/inquiry_context.py`: `build_inquiry_context()` scopes all queries to `Model.patient_id == patient_id`.

2. **Evaluator Defense-in-Depth (`evidence_evaluator.py`)**:
   - `evaluate_passage_evidence()` already contains the existing parameter:
     ```python
     def evaluate_passage_evidence(
         target: InquiryTarget,
         retrieval_result: Any,
         requesting_patient_id: Optional[uuid.UUID] = None,
     ) -> EvidenceResult:
     ```
   - It validates:
     - `if retrieval_result.patient_id != requesting_patient_id:` fail-closed return `EvidenceStatus.INSUFFICIENT`.
     - `for p in retrieval_result.passages: if p.patient_id != requesting_patient_id:` fail-closed return `EvidenceStatus.INSUFFICIENT`.
   - `evaluate_document_evidence()` also enforces `if evidence.patient_id != requesting_patient_id:` fail-closed return `INSUFFICIENT`.
   - S6 introduces **zero new parameters** to `evidence_evaluator.py`, exercising this exact existing defense-in-depth implementation.

3. **Fusion & Orchestrator Flow**:
   - `evidence_fusion.py` operates on already-isolated, qualified candidate pools passed from upstream evaluator functions.
   - `health_inquiry.py` resolves `patient = await get_or_create_patient(db, current_user.id)` and passes `patient.id` to `retrieve_document_passages()`, `build_inquiry_context()`, and `evaluate_passage_evidence(..., patient.id)`.

> **Authoritative Boundary Scope**: S6 directly validates the evaluator-level tenant-isolation defense-in-depth contract. Database-level tenant scoping remains enforced by the existing retrieval/context SQL predicates and is exercised through the orchestrated API path. S6 adds no new database tests or production filtering.

### 7.2 Evaluator Invariant Test Execution
`test_m6_invariants.py` constructs synthetic retrieval results containing passages with mismatched `patient_id` values and invokes `evaluate_passage_evidence(..., requesting_patient_id=patient_A)`. It asserts that the existing fail-closed gate triggers immediately, returning `INSUFFICIENT` with zero passages qualified. This directly proves the evaluator defense-in-depth contract without calling the live database.

---

## 8. Determinism Verification Architecture

To guarantee 100% deterministic reproducibility across environments:
1. **Clock Normalization**: All temporal parsing and benchmark evaluations are executed under a frozen reference datetime (`FIXED_REF_DATETIME = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)`).
2. **Order-Independent Sorting**: All candidate sorting in evidence evaluation uses deterministic composite keys:
   - Passage ordering: `(document_date DESC/ASC, document_id ASC, chunk_index ASC)`.
   - Structured record ordering: `(event_date DESC/ASC, record_id ASC)`.
   - Cross-domain reconciliation tie-break: `STRUCTURED` priority over `DOCUMENT`, then secondary UUID tie-break.
3. **No Unordered Set Iterations**: All domain lists and attribute collections are explicitly sorted before assertion (`sorted(target.candidate_document_domains) == sorted(case.expected_document_domains)`).
4. **Seed-Pinned Permutations**: All invariant permutation tests use a fixed pseudo-random generator `random.Random(42)`.
5. **Repeatability Assertion**: `test_eval_deterministic_repeatability()` executes 3 full passes of query understanding and safety evaluation, asserting strict value equality (`res1 == res2 == res3`).

---

## 9. Inherited Debt Accounting & Baseline Verification

An empirical baseline run was executed from the authoritative working directory (`cd backend; ..\backend\.venv\Scripts\pytest.exe tests -q; cd ..`) against HEAD (`dd1c743`):

### 9.1 Authoritative Backend Baseline Summary
```text
=========================== short test summary info ===========================
FAILED tests/test_health_inquiry_api.py::test_partial_evidence_response
FAILED tests/test_health_inquiry_m4_s6.py::test_endpoint_document_inquiry_zero_candidates_insufficient
2 failed, 956 passed, 4 skipped, 16 warnings in 96.90s (0:01:36)
```

**Exact Category Breakdown (Total = 962 executed test items)**:
- **Passed**: `956`
- **Failed**: `2`
- **Skipped**: `4`
- **Warnings**: `16`
- **Xfailed**: `0`
- **Xpassed**: `0`
- **Errors**: `0`

**Classification of Failures**:
1. `tests/test_health_inquiry_api.py::test_partial_evidence_response` (M1 origin: asserts legacy partial evidence response wording `partially available` or `not recorded` instead of M5/M6 directive).
2. `tests/test_health_inquiry_m4_s6.py::test_endpoint_document_inquiry_zero_candidates_insufficient` (M4-S6 origin: asserts `"do not contain a record of: blood test."` whereas M5/M6 router and evaluation contract yields `"no document records are available for this domain."`).

**Both failures remain strictly classified as VERIFIED INHERITED ARCHITECTURAL DEBT**. They must NOT be modified, skipped, or weakened in S6.

### 9.2 Backend Code Quality (`ruff`)
- `python -m ruff check backend/app backend/tests`: **All checks passed (0 errors)**.
- `python -m ruff format --check backend/app backend/tests`: 1 pre-existing formatting diff in `backend/tests/test_query_understanding_m6_s1.py` (from S1). Under S6 frozen-file constraints, this file remains untouched.

### 9.3 Frontend Baseline & Explicit Build Gate Distinction
- **Vitest Component & Integration Suite**:
  - `npm --prefix frontend test`: **9 passed (9 files), 110 passed (110 tests) in 140s**.
- **ESLint**:
  - `npm --prefix frontend run lint`: **Passed cleanly with 0 errors**.
- **Vite Production Build (REQUIRED S6 REGRESSION GATE)**:
  - `npx vite build`: **Built successfully for production in 26s (`dist/`)**.
- **Frontend Configuration Debt (NOT an S6 Regression)**:
  - Running `npm run build` executes `tsc -b && vite build`. `tsc -b` fails because `frontend/tsconfig.json` includes `src/` which contains test files referencing Vitest/Node globals without explicit `@types/node` references in `tsconfig.json`. This is pre-existing configuration debt and does not represent an S6 regression. S6 will NOT modify `tsconfig.json` or frontend test code.

---

## 10. Full Regression Protocol

The authoritative S6 verification matrix consists of:

### 10.1 Focused S6 Evaluation Suite
```powershell
backend\.venv\Scripts\pytest.exe backend\tests\eval\test_m6_evaluation.py backend\tests\eval\test_m6_invariants.py -v
```
*Gate: 100% of M6 evaluation and invariant tests MUST PASS.*

### 10.2 Immutable M5 Regression Gate
```powershell
backend\.venv\Scripts\pytest.exe backend\tests\eval\test_m5_evaluation.py -v
```
*Gate: All 11 M5 evaluation tests and all 54 M5 cases MUST PASS.*

### 10.3 Full Backend Regression Suite
```powershell
cd backend
..\backend\.venv\Scripts\pytest.exe tests -q
cd ..
```
*Gate: Exactly 956 passed, 2 failed (strictly the verified inherited debt), 4 skipped, 0 errors.*

### 10.4 Backend Linting
```powershell
backend\.venv\Scripts\python.exe -m ruff check backend/app backend/tests
```
*Gate: All checks pass (0 errors).*

### 10.5 Full Frontend Regression Suite
```powershell
npm --prefix frontend test
npm --prefix frontend run lint
npx --prefix frontend vite build
```
*Gate: All 9 test files and 110 tests pass. ESLint passes with 0 errors. Vite production build completes with exit code 0.*

---

## 11. S6 File Boundaries

```text
┌────────────────────────────────────────────────────────┬────────────────────────────────────────────┐
│ File Path                                              │ Authorization & Action                     │
├────────────────────────────────────────────────────────┼────────────────────────────────────────────┤
│ backend/tests/eval/m6_benchmark_corpus.py              │ NEW FILE (Authorize creation)              │
│ backend/tests/eval/test_m6_evaluation.py               │ NEW FILE (Authorize creation)              │
│ backend/tests/eval/test_m6_invariants.py               │ NEW FILE (Authorize creation)              │
│ phases/P2-M6-S6-plan.md                                │ AUTHORITATIVE PLAN (Frozen in this step)   │
├────────────────────────────────────────────────────────┼────────────────────────────────────────────┤
│ backend/app/** (All production code)                   │ STRICTLY FROZEN (Zero edits)               │
│ backend/alembic/** (All database migrations)           │ STRICTLY FROZEN (Zero edits)               │
│ backend/tests/eval/m5_benchmark_corpus.py              │ STRICTLY FROZEN (Immutable M5 gate)        │
│ backend/tests/eval/test_m5_evaluation.py               │ STRICTLY FROZEN (Immutable M5 gate)        │
│ backend/tests/test_*.py (Existing M1–M5 tests)         │ STRICTLY FROZEN (Zero edits)               │
│ backend/tests/test_*_m6_s*.py (Existing S1–S5 tests)   │ STRICTLY FROZEN (Zero edits)               │
│ frontend/** (All UI & test code)                       │ STRICTLY FROZEN (Zero edits)               │
└────────────────────────────────────────────────────────┴────────────────────────────────────────────┘
```

---

## 12. Non-Goals

To maintain strict project scope discipline per `AGENTS.md`:
1. **NO Production Code Edits**: S6 does not modify `inquiry.py`, `retrieval.py`, `query_understanding.py`, `evidence_evaluator.py`, `evidence_fusion.py`, `sanitized_context.py`, or `health_inquiry.py`.
2. **NO Weakening of Existing Assertions**: S6 does not xfail, skip, or edit the 2 inherited legacy test failures.
3. **NO Database Schema Migrations**: Zero Alembic migrations.
4. **NO External Testing Dependencies**: No `hypothesis`, `faker`, or third-party property generators.
5. **NO Re-Formatting of Predecessor Test Files**: `test_query_understanding_m6_s1.py` remains frozen despite pre-existing ruff formatting diff.
6. **NO Frontend Modifications**: S6 does not edit `frontend/` files or modify `tsconfig.json`.

---

## 13. Resolved Ambiguities & Specification Nuances

### Ambiguity 1: Multi-Domain Anchor Union for `SUP-04`
- **Context**: In `P2-M6-architecture-lock.md` line 872, `SUP-04` (`"What was my latest lab report in 2024?"`) listed `doc: ["labs"]` in a short bullet summary.
- **Resolution**: Under the authoritative parser implementation and M5 multi-domain union rules (identical to `EXP-06` `"What lab reports have been uploaded?"`), the word `"lab"` triggers `LAB_ANCHORS` (`labs`) and `"report"` triggers `DIAGNOSTIC_ANCHORS` (`reports`, `clinical_documents`). The deterministic candidate document domain list is `["clinical_documents", "labs", "reports"]`. `m6_benchmark_corpus.py` specifies this exact multi-domain union.

### Ambiguity 2: Layer 1 Conformance Assertion Scope
- **Context**: Older M5 cases did not define `superlative` or `question_intent`.
- **Resolution**: Layer 1 asserts `superlative` and `question_intent` on the 16 M6 cases where they are authoritative, while asserting only the authoritative fields on M5 cases. This guarantees S1 parser behavior is thoroughly verified without creating artificial contradictions on legacy cases.

### Ambiguity 3: Invariant Testing Methodology
- **Context**: Architecture lock Section 12.3 described an adversarial invariant validation layer.
- **Resolution**: Implemented in `test_m6_invariants.py` using standard pytest parameterization and seed-pinned deterministic fixtures (`random.Random(42)`). Hypothesis is explicitly excluded.

---

## 14. Definition of Done & Closure Criteria for S6

Milestone 6 Slice 6 is complete only when:

### 14.1 Corpus
- **Exactly 70 BenchmarkTestCase entries** in `backend/tests/eval/m6_benchmark_corpus.py`.
- **54 M5 cases preserved verbatim** with zero modifications.
- **16 M6 cases exactly matching the locked corpus** and repository canonical parser output.

### 14.2 Evaluation
- **Layer 1 = 100% deterministic conformance** (66/66 routing conformance, 0 false unroutable, 4/4 clarification recall, 0 false clarification, 8/8 superlative, 4/4 comparison, 4/4 timeline).
- **Layer 2 = all required M6 evidence/retrieval/fusion contracts** (truth-table preservation, recency extremity, milestone trajectory $N \le 3, K \le 4$, Section 7.3 cross-domain reconciliation).
- **Layer 3 = all selected orchestrator invariants** (safety precedence, zero-DB unroutable, domain isolation, timeline UUID5 citation provenance, cross-domain trajectory synthesis, exact character-for-character locked `BOUNDED_TRAJECTORY_QUALIFIER` delivery, zero-date comparison LLM bypass permanent gate).
- **Invariant suite = all 12 declared invariants** (Invariants 1–9 locked; Invariants 10–12 validation extensions) passing across all permutations.

### 14.3 Regression
- **M5 evaluation = 11/11** (`test_m5_evaluation.py` passes completely).
- **Full backend = baseline 956 + 31 S6 tests = 987 passed + zero new failures** (command `cd backend; pytest tests -q; cd ..` yields exactly 987 passed, 2 failed, 4 skipped, 16 warnings, 0 errors).
  - *Known inherited debt*: 2 failures strictly preserved (`test_partial_evidence_response` & `test_endpoint_document_inquiry_zero_candidates_insufficient`), never converted into passes or weakened.
- **Ruff check = PASS** (`python -m ruff check backend/app backend/tests` yields 0 errors).
- **Frontend Vitest = 110/110** (all 9 test files and 110 tests pass).
- **Frontend ESLint = PASS** (`npm --prefix frontend run lint` yields 0 errors).
- **Vite production build = PASS** (`npx --prefix frontend vite build` completes with exit code 0).
  - *Pre-existing configuration debt*: `npm run build` / `tsc -b` test-file configuration failure explicitly distinguished from Vite production build.
- **Strict File Boundaries Preserved**:
  - Production modifications: 0
  - Migration modifications: 0
  - Existing test modifications: 0
  - Frontend modifications: 0

---

## 15. Readiness Gate & Authorization Statement

```text
CORPUS ARITHMETIC VERIFIED: 54 M5 + 16 M6 = EXACTLY 70
NEW S6 ARTIFACTS PLANNED: 3 FILES ONLY
PRODUCTION CODE EDITS PLANNED: 0
DATABASE MIGRATIONS PLANNED: 0
EXISTING TEST MODIFICATIONS PLANNED: 0
FRONTEND MODIFICATIONS PLANNED: 0
INHERITED DEBT AUDITED & ISOLATED: YES (956 BASELINE -> 987 POST-S6, 2 FAILED, 4 SKIPPED, 0 ERRORS)
HARNESS REUSE CONTRACT CLOSED: YES
INVARIANT TEST MATRIX CLOSED: YES (12 INVARIANTS)
TENANT ISOLATION BOUNDARY: VALIDATED AT EXISTING RETRIEVAL & EVALUATOR LAYER
BOUNDED QUALIFIER ASSERTION: EXACT LOCKED STRING
TARGET-ENTITY CANONICALIZATION: VALIDATED AGAINST REPOSITORY PARSER
VITE PRODUCTION BUILD GATE: VALIDATED (EXIT CODE 0)
```

```text
P2-M6-S6 PLAN STATUS: V1.0 — IMPLEMENTATION FROZEN

FINAL PRE-IMPLEMENTATION AMENDMENTS:
- Invariant 10 operational boundary clarified
- Zero-date / zero-LLM Layer 3 gate added
- Tenant-isolation wording clarified
- Category 14 overlap clarified

AUTHORIZED IMPLEMENTATION FILES:
1. backend/tests/eval/m6_benchmark_corpus.py
2. backend/tests/eval/test_m6_evaluation.py
3. backend/tests/eval/test_m6_invariants.py

PRODUCTION MODIFICATIONS: 0
MIGRATIONS: 0
EXISTING TEST MODIFICATIONS: 0
FRONTEND MODIFICATIONS: 0
```
