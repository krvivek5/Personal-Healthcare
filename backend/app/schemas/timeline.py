from __future__ import annotations

import uuid
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class HealthEvent(BaseModel):
    """
    Unified Health Event domain concept for Milestone 5 timeline synthesis.

    - event_date: Canonical string representation. Timestamp-based source dates
      are ISO-8601 UTC datetimes (e.g. '2026-09-10T14:30:00Z'); date-only source
      dates are 'YYYY-MM-DD'.
    - event_type: Explicit event type string (e.g. 'CONDITION_STARTED',
      'CONDITION_RESOLVED', 'SYMPTOM_RECORDED', 'MEDICATION_STARTED',
      'MEDICATION_STOPPED', 'DOCUMENT_DATED', 'DOCUMENT_UPLOADED',
      'GOAL_RECORDED').
    - event_state: Lifecycle/relevance state ('current', 'historical', 'neutral').
    - source_type: Originating entity ('CONDITION', 'SYMPTOM', 'MEDICATION',
      'DOCUMENT', 'GOAL').
    - source_id: UUID of originating record.
    """

    model_config = ConfigDict(from_attributes=True)

    event_date: str
    event_type: str
    event_state: Literal["current", "historical", "neutral"]
    title: str
    description: Optional[str] = None
    source_type: Literal["CONDITION", "SYMPTOM", "MEDICATION", "DOCUMENT", "GOAL"]
    source_id: uuid.UUID
