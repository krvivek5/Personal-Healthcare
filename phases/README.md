# Project Phase Documentation

This directory contains the planning and architecture documents for the project.

## Naming Convention

Use:

```text
P<phase>-M<milestone>-<type>.md
P<phase>-M<milestone>-S<slice>-<type>.md
```

Examples:

```text
P2-M3-architecture-lock.md
P2-M3-S5-plan.md
```

## Document Authority

For implementation work, use this order:

```text
Architecture Lock / Milestone Plan
        ↓
Slice Plan (when one exists)
        ↓
Existing Code + Tests
```

An architecture lock is authoritative for architectural boundaries,
invariants, non-goals, and deferred decisions.

A milestone plan defines milestone goals, slices, dependencies, and
acceptance criteria.

A slice plan contains implementation details for a specific slice.

## Phase 2

Current Phase 2 milestone documents:

```text
P2-M1-design.md
P2-M1-plan.md
P2-M2-plan.md
P2-M3-architecture-lock.md
P2-M3-S5-plan.md
```

For Milestone 3, always read:

```text
P2-M3-architecture-lock.md
        ↓
P2-M3-S<slice>-plan.md (when available)
        ↓
Existing Code + Tests
```

and the relevant slice plan when available.

## Legacy / Historical Documents

Files such as:

```text
phase-01.md
phase-01-plan.md
phase-02.md
P1-M*-plan.md
```

are historical or earlier planning documents.

Do not use them as the authoritative specification for current Phase 2
milestone work when a current architecture lock or milestone plan exists.

## Coding Agent Rules

Before implementing a slice:

1. Identify the exact Phase, Milestone, and Slice.
2. Read the applicable architecture lock or milestone plan.
3. Read the milestone architecture/plan document.
4. Read the slice plan when one exists.
5. Do not guess between conflicting documents.

If two documents appear to conflict and the authority is unclear:

```text
STOP
DO NOT GUESS
REPORT THE CONFLICT
```

Do not introduce functionality belonging to later milestones or slices.

## Core Principle

Project documentation should be explicit enough that an implementation agent
can determine the correct source of truth without relying on filenames,
timestamps, or inference.
