"""
Canonical provenance enums and types for M6.

These are the single source of truth for valid provenance values across
the entire Phase 1 backend. All service code and validation helpers MUST
import from here — never hard-code string literals elsewhere.
"""

from enum import Enum


class HealthSourceType(str, Enum):
    """Origin classification of a health entity."""

    PATIENT_REPORTED = "PATIENT_REPORTED"
    SOURCE_DOCUMENT = "SOURCE_DOCUMENT"
    # Reserved — cannot be asserted by clients in Phase 1.
    CLINICIAN_CONFIRMED = "CLINICIAN_CONFIRMED"


class VerificationState(str, Enum):
    """Epistemic / verification classification of a health entity.

    Server-owned and response-only in Phase 1. Clients cannot submit or
    alter this field.
    """

    PATIENT_REPORTED = "PATIENT_REPORTED"
    SOURCE_RECORDED = "SOURCE_RECORDED"
    # Reserved — cannot be asserted by clients in Phase 1.
    CLINICIAN_CONFIRMED = "CLINICIAN_CONFIRMED"
    AI_DERIVED = "AI_DERIVED"
    UNCERTAIN = "UNCERTAIN"


# ── Sets used in validation ────────────────────────────────────────────────────

#: Source type values that Phase 1 clients are allowed to supply.
ALLOWED_CLIENT_SOURCE_TYPES: frozenset[str] = frozenset(
    {
        HealthSourceType.PATIENT_REPORTED,
        HealthSourceType.SOURCE_DOCUMENT,
    }
)

#: Source type values that are reserved and may NOT be supplied by Phase 1 clients.
RESERVED_SOURCE_TYPES: frozenset[str] = frozenset(
    {
        HealthSourceType.CLINICIAN_CONFIRMED,
    }
)

#: All verification state values are reserved; clients may never submit any.
RESERVED_VERIFICATION_STATES: frozenset[str] = frozenset(
    {v.value for v in VerificationState}
)
