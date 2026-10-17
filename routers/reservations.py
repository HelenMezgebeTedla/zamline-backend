import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from database import get_db
from dependency import get_current_user
from models.reservations import Reservation, ReservationStatus
from models.users import User
from schemas.reservations import (
    ContactOut,
    ReservationCancel,
    ReservationCreate,
    ReservationDetailOut,
    ReservationOut,
)
from services import reservations as reservations_service

router = APIRouter(tags=["Reservations"])


def detail(r: Reservation):
    return ReservationDetailOut(
        **ReservationOut.model_validate(r).model_dump(),
        fleet_company_name=r.company.business_name,
        plate_number=r.truck.plate_number,
        origin_address=r.shipment.origin_address,
        destination_address=r.shipment.destination_address,
        cargo_type=r.shipment.cargo_type,
        proposed_amount=r.shipment.proposed_amount,
        shipment_status=r.shipment.status,
    )


@router.post(
    "/reservations",
    response_model=ReservationDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="Accept a matched shipment (first acceptance wins)",
    responses={
        409: {"description": "Load already claimed, or the match/truck can't be used"}
    },
)
def accept_shipment(
    body: ReservationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return detail(reservations_service.accept_match(db, user, body.match_id))


@router.get(
    "/reservations",
    response_model=list[ReservationDetailOut],
    summary="List my company's reservations",
)
def list_reservations(
    status_filter: ReservationStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return [
        detail(r)
        for r in reservations_service.list_reservations(db, user, status_filter)
    ]


@router.get(
    "/reservations/{reservation_id}",
    response_model=ReservationDetailOut,
    summary="Get one reservation",
)
def get_reservation(
    reservation_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return detail(reservations_service.get_reservation(db, user, reservation_id))


@router.patch(
    "/reservations/{reservation_id}/cancel",
    response_model=ReservationDetailOut,
    summary="Cancel a reservation",
)
def cancel_reservation(
    reservation_id: uuid.UUID,
    body: ReservationCancel | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return detail(
        reservations_service.cancel_reservation(
            db, user, reservation_id, body.reason if body else None
        )
    )


@router.get(
    "/shipments/{shipment_id}/contact",
    response_model=ContactOut,
    tags=["Contact handoff"],
    summary="Counterparty contact details (masked until the shipment is reserved)",
)
def get_contact(
    shipment_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return reservations_service.get_contact(db, user, shipment_id)
