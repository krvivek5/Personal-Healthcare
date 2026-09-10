import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


class HealthProfileBase(BaseModel):
    date_of_birth: Optional[date] = None
    biological_sex: Optional[str] = None
    height_cm: Optional[Decimal] = None
    blood_group: Optional[str] = None
    notes: Optional[str] = None


class HealthProfileUpdate(HealthProfileBase):
    pass


class HealthProfileResponse(HealthProfileBase):
    id: Optional[uuid.UUID] = None
    patient_id: Optional[uuid.UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
