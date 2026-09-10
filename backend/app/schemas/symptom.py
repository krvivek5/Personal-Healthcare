import uuid
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class SymptomBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    severity: Optional[Literal["mild", "moderate", "severe"]] = None
    started_at: Optional[date] = None
    ended_at: Optional[date] = None
    notes: Optional[str] = None


class SymptomCreate(SymptomBase):
    recorded_at: Optional[datetime] = None


class SymptomUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    severity: Optional[Literal["mild", "moderate", "severe"]] = None
    started_at: Optional[date] = None
    ended_at: Optional[date] = None
    notes: Optional[str] = None


class SymptomResponse(SymptomBase):
    id: uuid.UUID
    patient_id: uuid.UUID
    recorded_at: datetime
    source_type: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
