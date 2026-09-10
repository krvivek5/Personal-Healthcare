import uuid
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ConditionBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    status: Literal["active", "resolved"]
    is_chronic: bool = False
    started_at: Optional[date] = None
    ended_at: Optional[date] = None
    notes: Optional[str] = None


class ConditionCreate(ConditionBase):
    recorded_at: Optional[datetime] = None


class ConditionUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    status: Optional[Literal["active", "resolved"]] = None
    is_chronic: Optional[bool] = None
    started_at: Optional[date] = None
    ended_at: Optional[date] = None
    notes: Optional[str] = None


class ConditionResponse(ConditionBase):
    id: uuid.UUID
    patient_id: uuid.UUID
    recorded_at: datetime
    source_type: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
