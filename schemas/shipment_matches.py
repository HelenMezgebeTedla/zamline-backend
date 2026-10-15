from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from models.shipment_matches import ManagerDecision
from models.trucks import AvailabilityStatus, BodyType


class ShipmentOpportunitySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    shipment_id: UUID
    origin_address: str
    destination_address: str
    cargo_type: str
    weight_kg: float
    required_body_type: BodyType
    pickup_time: datetime
    proposed_amount: Decimal


class CompatibleTruckSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    truck_id: UUID
    truck_type: str
    body_type: BodyType
    capacity_kg: float
    availability_status: AvailabilityStatus


class FleetMatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    match_id: UUID
    shipment_id: UUID
    truck_id: UUID
    manager_decision: ManagerDecision
    shipment: ShipmentOpportunitySummary
    truck: CompatibleTruckSummary
