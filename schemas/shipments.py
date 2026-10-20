from datetime import date, datetime, time
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from models.shipments import ShipmentStatus
from models.trucks import BodyType


class ShipmentCreate(BaseModel):
    origin_address: str = Field(min_length=2, max_length=250)
    destination_address: str = Field(min_length=2, max_length=250)
    cargo_type: str = Field(min_length=2, max_length=20)
    weight_kg: float = Field(gt=0)
    required_body_type: BodyType
    pickup_date: date
    pickup_time: time
    special_requirements: Optional[str] = None
    proposed_amount: Decimal = Field(gt=0)


class ShipmentUpdate(BaseModel):
    origin_address: str = Field(default=None, min_length=2, max_length=250)
    destination_address: str = Field(default=None, min_length=2, max_length=250)
    cargo_type: str = Field(default=None, min_length=2, max_length=20)
    weight_kg: float = Field(default=None, gt=0)
    required_body_type: BodyType = Field(default=None)
    pickup_date: date = Field(default=None)
    pickup_time: time = Field(default=None)
    special_requirements: Optional[str] = Field(default=None)
    proposed_amount: Decimal = Field(default=None, gt=0)

    @model_validator(mode="after")
    def pickup_date_and_time_together(self):
        sent = {"pickup_date", "pickup_time"} & self.model_fields_set
        if len(sent) == 1:
            raise ValueError("pickup_date and pickup_time must be sent together")
        return self


class ShipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    shipment_id: UUID
    company_id: UUID
    user_id: UUID
    origin_address: str
    origin_latitude: float | None = None
    origin_longitude: float | None = None
    destination_address: str
    destination_latitude: float | None = None
    destination_longitude: float | None = None
    cargo_type: str
    weight_kg: float
    required_body_type: BodyType
    pickup_time: datetime
    special_requirements: Optional[str] = Field(default=None)
    proposed_amount: Decimal
    status: ShipmentStatus
    published_at: datetime
