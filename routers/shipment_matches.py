from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from dependency import require_fleet_manager, require_verified_company
from schemas.shipment_matches import FleetMatchResponse
from services.shipment_matches import (
    generate_matches_for_fleet_company,
    list_matches_for_fleet_company,
)

router = APIRouter(
    prefix="/shipment-matches",
    tags=["Fleet Matching"],
)


def _own_company_id(company, requested_id: UUID | None) -> UUID:
    if requested_id is not None and requested_id != company.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view matches for your own company",
        )
    return company.company_id


@router.post(
    "/generate",
    response_model=list[FleetMatchResponse],
)
def generate_matches(
    company_id: UUID | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_fleet_manager),
    company=Depends(require_verified_company),
):
    return generate_matches_for_fleet_company(
        db,
        _own_company_id(company, company_id),
    )


@router.get(
    "/opportunities",
    response_model=list[FleetMatchResponse],
)
def get_opportunities(
    company_id: UUID | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_fleet_manager),
    company=Depends(require_verified_company),
):
    return list_matches_for_fleet_company(
        db,
        _own_company_id(company, company_id),
    )
