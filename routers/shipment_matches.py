from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database import get_db
from schemas.shipment_matches import FleetMatchResponse
from services.shipment_matches import (
    FleetCompanyNotEligibleError,
    FleetCompanyNotFoundError,
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
    company_id: UUID = Query(...),
    db: Session = Depends(get_db),
):
    try:
        return generate_matches_for_fleet_company(
            db,
            company_id,
        )
    except FleetCompanyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except FleetCompanyNotEligibleError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.get(
    "/opportunities",
    response_model=list[FleetMatchResponse],
)
def get_opportunities(
    company_id: UUID = Query(...),
    db: Session = Depends(get_db),
):
    try:
        return list_matches_for_fleet_company(
            db,
            company_id,
        )
    except FleetCompanyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except FleetCompanyNotEligibleError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
