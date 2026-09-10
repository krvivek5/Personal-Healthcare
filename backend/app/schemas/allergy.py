import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class AllergyBase(BaseModel):
    allergen: str = Field(..., min_length=1, max_length=255)
    reaction: Optional[str] = Field(None, max_length=255)
    severity: Optional[Literal["mild", "moderate", "severe", "life_threatening"]] = None
    notes: Optional[str] = None


class AllergyCreate(AllergyBase):
    recorded_at: Optional[datetime] = None


class AllergyUpdate(BaseModel):
    allergen: Optional[str] = Field(None, min_length=1, max_length=255)
    reaction: Optional[str] = Field(None, max_length=255)
    severity: Optional[Literal["mild", "moderate", "severe", "life_threatening"]] = None
    notes: Optional[str] = None


class AllergyResponse(AllergyBase):
    id: uuid.UUID
    patient_id: uuid.UUID
    recorded_at: datetime
    source_type: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
