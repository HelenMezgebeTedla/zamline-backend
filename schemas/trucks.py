import re
from typing import Optional

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from models.shipments import ShipmentStatus
from models.trucks import AvailabilityStatus, BodyType


def normalize_plate(value: str) -> str:
    """'baa 1234' and ' BAA  1234 ' are the same truck, so store one form."""
    return re.sub(r"\s+", " ", value.strip()).upper()


class TruckCreate(BaseModel):
    plate_number: str = Field(min_length=2, max_length=20)
    truck_type: str = Field(min_length=2, max_length=30)
    body_type: BodyType
    capacity_kg: float = Field(gt=0)
    fuel_consumption_l_per_100km: float = Field(gt=0)

    current_location: Optional[str] = None

    maintenance_per_km: Decimal = Field(gt=0)
    current_location: str | None = Field(default=None, max_length=50)

    maintenance_per_km: Decimal = Field(gt=0)
    current_location: str | None = Field(default=None, max_length=50)

    available_from: datetime | None = None

    @field_validator("plate_number")
    @classmethod
    def clean_plate(cls, value: str) -> str:
        cleaned = normalize_plate(value)
        if len(cleaned) < 2:
            raise ValueError("Plate number is too short")
        return cleaned

    @field_validator("truck_type")
    @classmethod
    def clean_truck_type(cls, value: str) -> str:
        return value.strip()


class TruckUpdate(BaseModel):
    """Edit truck information (FYP-140).

    Availability has its own endpoint (FYP-141) and retiring has its own
    endpoint (FYP-142), so neither can be changed here.
    """

    model_config = ConfigDict(extra="forbid")

    truck_type: str | None = Field(default=None, min_length=2, max_length=30)
    body_type: BodyType | None = None
    capacity_kg: float | None = Field(default=None, gt=0)
    fuel_consumption_l_per_100km: float | None = Field(default=None, gt=0)
    maintenance_per_km: Decimal | None = Field(default=None, gt=0)

    current_location: Optional[str] = None

    current_location: str | None = Field(default=None, max_length=50)

    current_location: str | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def no_nulls_for_required_columns(self):
        for name in (
            "truck_type",
            "body_type",
            "capacity_kg",
            "fuel_consumption_l_per_100km",
            "maintenance_per_km",
        ):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be empty")
        return self


class TruckAvailabilityUpdate(BaseModel):
    """Switch a truck on or off for matching (FYP-141)."""

    """Switch a truck on or off for matching (FYP-141)."""

    model_config = ConfigDict(extra="forbid")

    availability_status: AvailabilityStatus
    available_from: datetime | None = None

    current_location: Optional[str] = None

    current_location: str | None = Field(default=None, max_length=50)

    current_location: str | None = Field(default=None, max_length=50)

    @field_validator("availability_status")
    @classmethod
    def not_retired(cls, value: AvailabilityStatus) -> AvailabilityStatus:
        if value == AvailabilityStatus.RETIRED:
            raise ValueError("Use POST /trucks/{truck_id}/retire to retire a truck")
        return value


class TruckRetireRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=255)


class TruckResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    truck_id: UUID
    company_id: UUID
    plate_number: str
    truck_type: str
    body_type: BodyType
    capacity_kg: float
    fuel_consumption_l_per_100km: float
    maintenance_per_km: Decimal
    availability_status: AvailabilityStatus

    current_location: Optional[str] = None
    available_from: datetime | None

    current_location: str | None
    available_from: datetime | None

    current_location: str | None
    available_from: datetime | None


class AllocatedShipment(BaseModel):
    reservation_id: UUID
    shipment_id: UUID
    origin_address: str
    destination_address: str
    cargo_type: str
    weight_kg: float
    pickup_time: datetime
    shipment_status: ShipmentStatus
    reserved_at: datetime


class TruckAllocationResponse(BaseModel):
    """Is this truck free, or tied to a confirmed shipment? (FYP-143)"""

    """Is this truck free, or tied to a confirmed shipment? (FYP-143)"""

    truck_id: UUID
    plate_number: str
    availability_status: AvailabilityStatus
    allocation_status: str  # "allocated", "available", "unavailable", "retired"
    allocated_shipment: AllocatedShipment | None
