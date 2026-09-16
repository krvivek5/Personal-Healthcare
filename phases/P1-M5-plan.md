# Milestone 5 Implementation Plan — Health Timeline

## Goal

Create a chronological representation of meaningful health events to establish the foundation for understanding a person's health over time.

## WHAT

Implement a health timeline that surfaces key events (e.g., symptom started, medication started/stopped, document uploaded) in a unified chronological view. This gives users a coherent "health story" from their disparate health records.

## WHY

The core value of the Personal Health Intelligence system is its ability to understand the individual's health context *over time*. The timeline is not merely a UI feature, but a fundamental domain concept required before introducing AI understanding.

## Minimal Implementation Boundaries

- **DO** use explicitly available dates (e.g., user-entered `started_at`, `document_date`, `recorded_at`).
- **DO** link events to their source record (e.g., the specific document or condition ID).
- **DO NOT** infer or extract clinical dates from document contents using AI in Phase 1.
- **DO NOT** introduce event sourcing, event buses, Kafka, or complex asynchronous event architectures.
- **DO NOT** duplicate data in a way that requires complex synchronization to avoid stale or duplicate timeline events.

## Data / Query Architecture

To satisfy the requirement to "Avoid duplicate timeline events when the same underlying health event is created or updated" while keeping the architecture simple and reversible:

**Approach: Dynamic Timeline Synthesis**
Instead of creating a physical `timeline_events` table that requires complex SQLAlchemy hooks or triggers to keep in sync with `conditions`, `medications`, etc., we will define a unified `HealthEvent` schema and synthesize the timeline dynamically at query time.

1.  **Unified Domain Concept (Health Event Contract)**: We will create a Python domain model / Pydantic schema `HealthEvent` with fields:
    - `event_date`, `event_type`, `event_state`, `title`, `description`, `source_type` (e.g., `CONDITION`, `SYMPTOM`, `MEDICATION`, `DOCUMENT`, `GOAL`), and `source_id` (the UUID of the source record).
    - `event_type` is explicit (e.g., `CONDITION_STARTED`, `CONDITION_RESOLVED`, `SYMPTOM_RECORDED`, `MEDICATION_STARTED`, `MEDICATION_STOPPED`, `DOCUMENT_DATED`, `DOCUMENT_UPLOADED`, `GOAL_RECORDED`). Do not require the frontend to infer event meaning from title/description.
    - `event_state` (`current`, `historical`, or `neutral`): Explicitly represents the current relevance/lifecycle state of the source entity, NOT whether `event_date` is in the past.
      - **Condition** (lifecycle-bearing):
        - `active` → `current`
        - `resolved` → `historical`
      - **Medication** (lifecycle-bearing):
        - `active` → `current`
        - `stopped` → `historical`
      - **PatientGoal** (lifecycle-bearing):
        - `active` → `current`
        - `achieved` → `historical`
        - `abandoned` → `historical`
      - **Symptom and Document**:
        - `neutral` (neither source model provides a lifecycle state used by the timeline; keep representation neutral rather than inventing state semantics).
      - **Multi-Event Records State Definition**:
        - For an active Medication (`status == "active"`):
          - `Medication.started_at` → `MEDICATION_STARTED` derived with `event_state = current`.
        - For a stopped Medication (`status == "stopped"`):
          - `Medication.started_at` → `MEDICATION_STARTED` derived with `event_state = historical` (the medication course itself is stopped/historical).
          - `Medication.ended_at` → `MEDICATION_STOPPED` derived with `event_state = historical`.
        - For an active Condition (`status == "active"`):
          - `Condition.started_at` → `CONDITION_STARTED` derived with `event_state = current`.
        - For a resolved Condition (`status == "resolved"`):
          - `Condition.started_at` → `CONDITION_STARTED` derived with `event_state = historical`.
          - `Condition.ended_at` → `CONDITION_RESOLVED` derived with `event_state = historical`.
      - The frontend must use only the backend-provided `event_state` and not fetch source records merely to determine timeline state.
    - *Do not expose `storage_key` or other internal storage infrastructure identifiers.*
2.  **Event Date Contract & Normalization**:
    - The API representation for `HealthEvent.event_date` is explicitly defined:
      - Timestamp-based source dates (`started_at` when timestamp, `recorded_at`, `uploaded_at`) are returned as ISO-8601 UTC datetimes (e.g. `YYYY-MM-DDTHH:MM:SSZ`).
      - Date-only source dates (`document_date`, or date-only `started_at`/`ended_at`) are returned as ISO-8601 dates in `YYYY-MM-DD` form.
      - Backend sorting must correctly compare mixed date and datetime source values without inventing clinical time precision (e.g., comparing dates at the calendar day boundary or normalizing datetime comparisons without fabricating artificial hour/minute precision for date-only records).
      - Do not introduce additional date fields (`event_date` remains the single canonical date field).
3.  **Event-per-Source Mapping**: Each source record generates specific `HealthEvent`s based on this explicit mapping. *Crucially, generate the derived HealthEvent only when the mapped source date exists. Never invent or infer a missing clinical date.* Keep the explicit Document fallback.
    - **Condition**:
      - `started_at` → `CONDITION_STARTED` (`event_state = current` if status is `active`, `historical` if status is `resolved`). Generated only when `started_at` is present.
      - `ended_at` → `CONDITION_RESOLVED` (`event_state = historical`). Generated only when `ended_at` is present.
    - **Symptom**:
      - `recorded_at` → `SYMPTOM_RECORDED` (`event_state = neutral`). Generated when `recorded_at` is present.
    - **Medication**:
      - `started_at` → `MEDICATION_STARTED` (`event_state = current` if status is `active`, `historical` if status is `stopped`). Generated only when `started_at` is present.
      - `ended_at` → `MEDICATION_STOPPED` (`event_state = historical`). Generated only when `ended_at` is present.
    - **Document**:
      - `document_date` → `DOCUMENT_DATED` (`event_state = neutral`). Generated when `document_date` is present.
      - `uploaded_at` (fallback when `document_date` is null) → `DOCUMENT_UPLOADED` (`event_state = neutral`).
    - **PatientGoal**:
      - `recorded_at` → `GOAL_RECORDED` (`event_state = current` if status is `active`, `historical` if status is `achieved` or `abandoned`). Generated when `recorded_at` is present.
    *(Do not generate a goal timeline event solely because `target_date` exists unless explicitly justified).*
4.  **Aggregation Service**: A backend service will query the existing patient data (`conditions`, `symptoms`, `medications`, `documents`, and `patient_goals`), map them to `HealthEvent` objects using the event-per-source mapping rules, and sort them chronologically. Do not add new timeline-specific storage.
5.  **Deterministic Ordering**: When multiple HealthEvents have the same `event_date`, the API result must be deterministic. Primary ordering is `event_date` descending. Then use stable source/entity metadata (e.g., `created_at`, `source_type`, `source_id`) as a deterministic secondary/tertiary tie-breaker.
6.  **Future-Proofing**: This dynamic approach is easily reversible. If query performance becomes an issue in later phases with massive data, we can materialize this into a physical table without changing the API contract.

## Frontend Scope

-   **Timeline View**: A new "Timeline" page or dedicated section in the patient dashboard.
-   **Chronological List**: Renders the aggregated `HealthEvent` items sorted by `event_date` (descending by default).
-   **Current vs Historical Semantics**: Use the backend-provided `event_state` (`current`, `historical`, `neutral`) to drive visual presentation. Do not infer clinical state solely from `event_date` (past event date is not equivalent to historical/resolved).
-   **Source Linking**: `source_type` and `source_id` are sufficient source references for the frontend. Where applicable, allow the user to click an event to view the source. Reuse the existing source entity APIs where the UI needs to open the originating record. Do not create separate timeline-detail records or new duplicate source resources.

## Mini-Feature Sequence

1.  **Backend: Unified Schema**
    -   Define `HealthEvent` Pydantic schemas in `backend/app/schemas/timeline.py`.
2.  **Backend: Timeline Aggregation Logic**
    -   Implement the logic in `backend/app/health/timeline.py` to fetch and map data from `conditions`, `symptoms`, `medications`, `documents`, and `patient_goals` into `HealthEvent` objects. Ensure deterministic sorting logic is applied.
3.  **Backend: API Endpoint**
    -   Create `GET /api/v1/timeline` endpoint.
4.  **Backend: Focused Tests**
    -   Write Pytest tests to verify chronological ordering and correct mapping of source entities.
5.  **Frontend: Integration & UI**
    -   Create the API client method for the timeline.
    -   Build the Timeline UI components.
    -   Integrate and manually test.
6.  **Frontend: Focused Tests**
    -   Write Vitest tests for the Timeline component rendering and sorting.

## Acceptance Criteria

-   [ ] Meaningful patient-health events can be represented chronologically in a single view.
-   [ ] Events contain relevant clinical dates (`event_date`).
-   [ ] Events can be linked back to their source record where applicable.
-   [ ] Historical events remain distinguishable from the current state.
-   [ ] No duplicate timeline events exist when an underlying record is updated (updating a source record must change its derived timeline event(s) rather than creating additional duplicate events).
-   [ ] A user can only see timeline events for their own patient profile (Strict User Isolation).

## Verification Plan

### Automated Tests (Backend)
-   `test_timeline_aggregation`: Expand the primary fixture to include representative records from all five aggregation sources: condition, symptom, medication, document, and patient goal. Verify:
    - `event_type`
    - `event_date`
    - `event_state`
    - `source_type`
    - `source_id`
    - deterministic chronological ordering
    - Verify that modifying an existing source record changes its derived event(s) without creating duplicate timeline events.
-   `test_timeline_isolation`: Ensure User A cannot fetch the timeline for User B.

### Automated Tests (Frontend)
-   `Timeline.test.tsx`: Expand to explicitly test:
    - chronological rendering;
    - `event_type` presentation;
    - `event_state` visual distinction;
    - `source_type` + `source_id` source-link behavior;
    - empty state;
    - loading/error states.

### Manual Verification
-   Log in to the app as an authenticated user.
-   Visibly exercise all five source types on the browser timeline:
    1. **Condition**: Create a condition (e.g., "Hypertension", active, with a `started_at` date).
    2. **Symptom**: Record a symptom (e.g., "Headache", with severity and `recorded_at` timestamp).
    3. **Medication**: Add a medication (e.g., "Lisinopril", active, with a `started_at` date).
    4. **Document**: Upload a medical document with a specific `document_date` (e.g., a lab report).
    5. **Patient Goal**: Create a patient goal (e.g., "Walk 10,000 steps daily", active, with `recorded_at`).
-   Navigate to the Timeline view in the browser and verify:
    - All five source types are visibly rendered with their appropriate event types, labels, and source links.
    - Derived `event_state` displays correctly (`current` for active condition, medication, goal; `neutral` for symptom, document).
    - Events appear in correct descending chronological order according to `event_date` (comparing mixed dates and datetimes accurately) with deterministic tie-breaking.
-   Perform the condition-date update test:
    - Edit the existing condition's `started_at` date to a different date.
    - Refresh the Timeline view in the browser and verify that the derived event moves to its new chronological position without producing a duplicate timeline event.

