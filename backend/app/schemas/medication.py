import uuid
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class MedicationBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    dosage: Optional[str] = Field(None, max_length=100)
    frequency: Optional[str] = Field(None, max_length=100)
    status: Literal["active", "stopped"] = "active"
    as_needed: bool = False
    started_at: Optional[date] = None
    ended_at: Optional[date] = None
    notes: Optional[str] = None


class MedicationCreate(MedicationBase):
    recorded_at: Optional[datetime] = None


class MedicationUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    dosage: Optional[str] = Field(None, max_length=100)
    frequency: Optional[str] = Field(None, max_length=100)
    status: Optional[Literal["active", "stopped"]] = None
    as_needed: Optional[bool] = None
    started_at: Optional[date] = None
    ended_at: Optional[date] = None
    notes: Optional[str] = None


class MedicationResponse(MedicationBase):
    id: uuid.UUID
    patient_id: uuid.UUID
    recorded_at: datetime
    source_type: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
