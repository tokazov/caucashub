"""Optional carrier defaults; these do not publish or modify a vehicle."""
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.load import TruckType


class CarrierProfileFields(BaseModel):
    truck_type: Optional[TruckType] = None
    # Tonnes in the profile/UI; vehicle and offer payloads use kilograms.
    tonnage: Optional[float] = Field(default=None, gt=0, le=100, allow_inf_nan=False)

    @field_validator("tonnage", mode="before")
    @classmethod
    def reject_boolean_capacity(cls, value):
        if isinstance(value, bool):
            raise ValueError("Грузоподъёмность должна быть числом от 0 до 100 тонн")
        return value
