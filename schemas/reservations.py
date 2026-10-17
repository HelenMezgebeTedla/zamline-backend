import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from models.reservations import ReservationStatus
from models.shipments import ShipmentStatus


class ReservationCreate(BaseModel):
    match_id: uuid.UUID


class ReservationCancel(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ReservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    reservation_id: uuid.UUID
    shipment_id: uuid.UUID
    company_id: uuid.UUID
    truck_id: uuid.UUID
    user_id: uuid.UUID
    match_id: uuid.UUID
    status: ReservationStatus
    reserved_at: datetime


class ReservationDetailOut(ReservationOut):
    fleet_company_name: str
    plate_number: str
    origin_address: str
    destination_address: str
    cargo_type: str
    proposed_amount: Decimal
    shipment_status: ShipmentStatus


class ContactOut(BaseModel):
    shipment_id: uuid.UUID
    visible: bool
    counterparty_role: Literal["shipper", "fleet"] | None
    business_name: str | None
    company_email: str | None
    phone_number: str | None
    reservation_id: uuid.UUID | None = None
