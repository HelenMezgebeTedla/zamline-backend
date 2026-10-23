from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database import get_db
from dependency import require_role, require_verified_company
from models.users import UserRole
from schemas.shipment_matches import (
    FleetMatchResponse,
    GeocodedPlaceResponse,
    MatchDecisionResponse,
    MatchDetailResponse,
    RouteInformation,
)
from services.errors import (
    DomainError,
    ExternalServiceError,
    NotAllowedError,
    NotFoundError,
)
from services.shipment_matches import (
    accept_match,
    estimate_route_for_fleet_manager,
    finish_assessment,
    generate_matches_for_fleet_manager,
    geocode_location_for_fleet_manager,
    get_match_detail,
    list_opportunities_for_fleet_manager,
    skip_match,
    start_assessment_with_run_id,
)

router = APIRouter(
    prefix="/shipment-matches",
    tags=["Fleet Matching"],
)

fleet_manager = require_role(UserRole.FLEET_MANAGER)


def to_http_exception(error: DomainError):
    if isinstance(error, NotFoundError):
        status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(error, NotAllowedError):
        status_code = status.HTTP_403_FORBIDDEN
    elif isinstance(error, ExternalServiceError):
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        status_code = status.HTTP_409_CONFLICT

    return HTTPException(status_code=status_code, detail=str(error))


@router.post(
    "/generate",
    response_model=list[FleetMatchResponse],
)
def generate_matches(
    db: Session = Depends(get_db),
    current_user=Depends(fleet_manager),
    company=Depends(require_verified_company),
):
    try:
        return generate_matches_for_fleet_manager(
            db,
            current_user.user_id,
        )
    except DomainError as error:
        raise to_http_exception(error) from error


@router.get(
    "/opportunities",
    response_model=list[FleetMatchResponse],
)
def get_opportunities(
    db: Session = Depends(get_db),
    current_user=Depends(fleet_manager),
    company=Depends(require_verified_company),
):
    try:
        return list_opportunities_for_fleet_manager(
            db,
            current_user.user_id,
        )
    except DomainError as error:
        raise to_http_exception(error) from error


@router.get(
    "/geocode",
    response_model=list[GeocodedPlaceResponse],
)
def geocode_location(
    text: str = Query(min_length=2, max_length=255),
    size: int = Query(default=5, ge=1, le=10),
    db: Session = Depends(get_db),
    current_user=Depends(fleet_manager),
    company=Depends(require_verified_company),
):
    try:
        return geocode_location_for_fleet_manager(
            db,
            current_user.user_id,
            text,
            size,
        )
    except DomainError as error:
        raise to_http_exception(error) from error


@router.get(
    "/route",
    response_model=RouteInformation,
)
def estimate_route(
    origin_latitude: float = Query(ge=-90, le=90),
    origin_longitude: float = Query(ge=-180, le=180),
    destination_latitude: float = Query(ge=-90, le=90),
    destination_longitude: float = Query(ge=-180, le=180),
    db: Session = Depends(get_db),
    current_user=Depends(fleet_manager),
    company=Depends(require_verified_company),
):
    try:
        return estimate_route_for_fleet_manager(
            db,
            current_user.user_id,
            origin_latitude,
            origin_longitude,
            destination_latitude,
            destination_longitude,
        )
    except DomainError as error:
        raise to_http_exception(error) from error


@router.get(
    "/{match_id}",
    response_model=MatchDetailResponse,
)
def get_match(
    match_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(fleet_manager),
    company=Depends(require_verified_company),
):
    try:
        return get_match_detail(
            db,
            current_user.user_id,
            match_id,
        )
    except DomainError as error:
        raise to_http_exception(error) from error


def finish_assessment_in_background(bind, match_id: UUID, run_id: str):
    with Session(bind=bind) as db:
        finish_assessment(db, match_id, run_id)


@router.post(
    "/{match_id}/assessment",
    response_model=MatchDetailResponse,
)
def create_match_assessment(
    match_id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(fleet_manager),
    company=Depends(require_verified_company),
):
    try:
        detail, run_id = start_assessment_with_run_id(
            db,
            current_user.user_id,
            match_id,
        )
    except DomainError as error:
        raise to_http_exception(error) from error

    background_tasks.add_task(
        finish_assessment_in_background,
        db.get_bind(),
        match_id,
        run_id,
    )

    return detail


@router.post(
    "/{match_id}/accept",
    response_model=MatchDecisionResponse,
)
def accept_shipment_match(
    match_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(fleet_manager),
    company=Depends(require_verified_company),
):
    try:
        return accept_match(
            db,
            current_user.user_id,
            match_id,
        )
    except DomainError as error:
        raise to_http_exception(error) from error


@router.post(
    "/{match_id}/skip",
    response_model=MatchDecisionResponse,
)
def skip_shipment_match(
    match_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(fleet_manager),
    company=Depends(require_verified_company),
):
    try:
        return skip_match(
            db,
            current_user.user_id,
            match_id,
        )
    except DomainError as error:
        raise to_http_exception(error) from error
