from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from schemas.shipment_matches import FleetMatchResponse
from services.shipment_matches import (
    generate_matches_for_fleet_company,
    list_matches_for_fleet_company,
)

router = APIRouter(
    prefix="/shipment-matches",
    tags=["Fleet Matching"],
)


@router.post(
    "/generate",
    response_model=list[FleetMatchResponse],
)
def generate_matches(
    company_id: UUID,
    db: Session = Depends(get_db),
):
    return generate_matches_for_fleet_company(
        db,
        company_id,
    )


@router.get(
    "/opportunities",
    response_model=list[FleetMatchResponse],
)
def get_opportunities(
    company_id: UUID,
    db: Session = Depends(get_db),
):
    return list_matches_for_fleet_company(
        db,
        company_id,
    )
