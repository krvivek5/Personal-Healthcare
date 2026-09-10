import uuid
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class GoalBase(BaseModel):
    description: str = Field(..., min_length=1)
    status: Literal["active", "achieved", "abandoned"]
    target_date: Optional[date] = None
    notes: Optional[str] = None


class GoalCreate(GoalBase):
    recorded_at: Optional[datetime] = None


class GoalUpdate(BaseModel):
    description: Optional[str] = Field(None, min_length=1)
    status: Optional[Literal["active", "achieved", "abandoned"]] = None
    target_date: Optional[date] = None
    notes: Optional[str] = None


class GoalResponse(GoalBase):
    id: uuid.UUID
    patient_id: uuid.UUID
    recorded_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
