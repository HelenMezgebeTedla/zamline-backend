from pydantic import field_serializer
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from models.shipment_matches import ManagerDecision, MatchOutcome
from models.trucks import AvailabilityStatus, BodyType
from typing import Literal


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


class ShipmentOpportunityDetail(ShipmentOpportunitySummary):
    special_requirements: str | None = None


class CompatibleTruckSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    truck_id: UUID
    truck_type: str
    body_type: BodyType
    capacity_kg: float
    availability_status: AvailabilityStatus


class CompatibleTruckDetail(CompatibleTruckSummary):
    plate_number: str


class FleetMatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    match_id: UUID
    shipment_id: UUID
    truck_id: UUID
    manager_decision: ManagerDecision
    shipment: ShipmentOpportunitySummary
    truck: CompatibleTruckSummary


class MatchDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    match_id: UUID
    manager_decision: ManagerDecision
    decided_at: datetime | None = None


class EvidenceCitation(BaseModel):
    citation: str
    supports: str


class CostCalculationBasis(BaseModel):
    quantity: int = Field(gt=0)
    unit: Literal["day"]
    rate_source: Literal["configured_driver_rate"]
    evidence_text: str = Field(min_length=1)


class CostFactor(BaseModel):
    factor: str
    status: Literal["quantified", "not_quantified", "not_applicable"]
    amount: Decimal | None = None
    reason: str
    calculation_basis: CostCalculationBasis | None = None
    citations: list[str] = Field(default_factory=list)


class AiAssessment(BaseModel):
    estimated_total_cost: Decimal = Field(ge=0)
    summary: str = Field(min_length=1)
    major_cost_factors: list[CostFactor]
    assumptions: list[str]
    risk_factors: list[str]
    limitations: list[str]
    evidence_citations: list[EvidenceCitation] = Field(default_factory=list)


class ReferenceSource(BaseModel):
    citation: str
    source_id: str
    title: str
    publisher: str
    date: str
    url: str | None = None


class RouteInformation(BaseModel):
    distance_km: float
    duration_minutes: int


class GeocodedPlaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    label: str
    latitude: float
    longitude: float


class OperatingCostBreakdown(BaseModel):
    fuel_cost: Decimal
    driver_cost: Decimal
    maintenance_cost: Decimal
    toll_cost: Decimal
    other_cost: Decimal


class MatchDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    match_id: UUID
    manager_decision: ManagerDecision
    shipment: ShipmentOpportunityDetail
    truck: CompatibleTruckDetail

    proposed_payment: Decimal
    route: RouteInformation | None = None
    cost_breakdown: OperatingCostBreakdown | None = None
    operating_cost_total: Decimal | None = None
    estimated_total_cost: Decimal | None = None
    estimated_margin: Decimal | None = None
    margin_percentage: Decimal | None = None
    outcome: MatchOutcome | None = None
    reference_sources: list[ReferenceSource] | None = None
    assessment: AiAssessment | None = None
    assessment_error: str | None = None
    assessment_status: str | None = None

    @field_serializer("assessment", when_used="json")
    def serialize_assessment_for_ui(self, assessment):
        if assessment is None:
            return None

        return {
            "summary": assessment.summary,
            "major_cost_factors": [
                {
                    "factor": factor.factor,
                    "status": factor.status,
                    "amount": (
                        str(factor.amount) if factor.amount is not None else None
                    ),
                    "reason": factor.reason,
                }
                for factor in assessment.major_cost_factors
            ],
            "risk_factors": assessment.risk_factors,
            "limitations": assessment.limitations,
        }
