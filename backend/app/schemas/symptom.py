import uuid
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.provenance import RESERVED_SOURCE_TYPES


def _reject_verification_state(data: dict) -> None:
    if "verification_state" in data:
        raise ValueError(
            "verification_state is server-owned and must not be submitted by clients."
        )


class SymptomBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    severity: Optional[Literal["mild", "moderate", "severe"]] = None
    started_at: Optional[date] = None
    ended_at: Optional[date] = None
    notes: Optional[str] = None


class SymptomCreate(SymptomBase):
    recorded_at: Optional[datetime] = None
    source_type: Optional[str] = None
    source_id: Optional[uuid.UUID] = None

    @model_validator(mode="before")
    @classmethod
    def reject_verification_state(cls, data: dict) -> dict:
        _reject_verification_state(data)
        return data

    @model_validator(mode="before")
    @classmethod
    def reject_reserved_source_types(cls, data: dict) -> dict:
        st = data.get("source_type")
        if st is not None and st in RESERVED_SOURCE_TYPES:
            raise ValueError(
                f"source_type '{st}' is reserved and cannot be submitted by clients."
            )
        return data


class SymptomUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    severity: Optional[Literal["mild", "moderate", "severe"]] = None
    started_at: Optional[date] = None
    ended_at: Optional[date] = None
    notes: Optional[str] = None
    source_type: Optional[str] = None
    source_id: Optional[uuid.UUID] = None

    @model_validator(mode="before")
    @classmethod
    def reject_verification_state(cls, data: dict) -> dict:
        _reject_verification_state(data)
        return data

    @model_validator(mode="before")
    @classmethod
    def reject_reserved_source_types(cls, data: dict) -> dict:
        st = data.get("source_type")
        if st is not None and st in RESERVED_SOURCE_TYPES:
            raise ValueError(
                f"source_type '{st}' is reserved and cannot be submitted by clients."
            )
        return data


class SymptomResponse(SymptomBase):
    id: uuid.UUID
    patient_id: uuid.UUID
    recorded_at: datetime
    source_type: str
    source_id: Optional[uuid.UUID]
    verification_state: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
