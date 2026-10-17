import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.companies import Company, VerificationStatus
from models.reservations import Reservation, ReservationStatus
from models.shipment_matches import ManagerDecision
from models.shipments import ShipmentStatus
from models.trucks import AvailabilityStatus
from models.users import User, UserRole
from repositories import reservations as reservations_repo
from schemas.reservations import ContactOut

LOAD_ALREADY_CLAIMED = "Load already claimed"
NO_LONGER_OPEN = "Shipment is no longer open"


def not_found(what: str):
    return HTTPException(status.HTTP_404_NOT_FOUND, detail=what)


def conflict(detail: str):
    return HTTPException(status.HTTP_409_CONFLICT, detail=detail)


def require_fleet_manager(user: User):
    if user.role != UserRole.FLEET_MANAGER:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Only a fleet manager can do this"
        )


def require_verified_company(user: User):
    if user.company.verification_status != VerificationStatus.VERIFIED:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Your company is not verified yet"
        )


def accept_match(db: Session, user: User, match_id: uuid.UUID):
    require_fleet_manager(user)
    require_verified_company(user)

    match = reservations_repo.get_match(db, match_id)
    if match is None or match.truck.company_id != user.company_id:
        raise not_found("Match not found")

    shipment_id = match.shipment_id
    if match.manager_decision == ManagerDecision.CLOSED:
        raise conflict(LOAD_ALREADY_CLAIMED)
    if match.manager_decision != ManagerDecision.PENDING:
        raise conflict(f"This match was already {match.manager_decision.value}")
    if match.truck.availability_status != AvailabilityStatus.AVAILABLE:
        raise conflict("This truck is not available")

    now = datetime.now(UTC)
    reservation = None
    try:
        with db.begin_nested():
            if reservations_repo.claim_shipment_if_open(db, shipment_id):
                reservation = reservations_repo.create(
                    db,
                    Reservation(
                        shipment_id=shipment_id,
                        company_id=user.company_id,
                        truck_id=match.truck_id,
                        user_id=user.user_id,
                        match_id=match.match_id,
                        status=ReservationStatus.ACCEPTED,
                        reserved_at=now,
                    ),
                )
    except IntegrityError:
        raise conflict(LOAD_ALREADY_CLAIMED) from None

    if reservation is None:
        current = reservations_repo.get_shipment_status(db, shipment_id)
        if current == ShipmentStatus.CONFIRMED:
            raise conflict(LOAD_ALREADY_CLAIMED)
        raise conflict(NO_LONGER_OPEN)

    reservations_repo.mark_match_accepted(match, user.user_id, now)
    reservations_repo.close_other_pending_matches(db, shipment_id, match.match_id, now)
    db.commit()
    db.refresh(reservation)
    return reservation


def list_reservations(
    db: Session, user: User, status_filter: ReservationStatus | None = None
):
    return reservations_repo.list_for_user(db, user, status_filter)


def get_reservation(db: Session, user: User, reservation_id: uuid.UUID) -> Reservation:
    reservation = reservations_repo.get_for_user(db, user, reservation_id)
    if reservation is None:
        raise not_found("Reservation not found")
    return reservation


def cancel_reservation(
    db: Session, user: User, reservation_id: uuid.UUID, reason: str | None = None
):
    reservation = get_reservation(db, user, reservation_id)
    if reservation.status == ReservationStatus.CANCELLED:
        raise conflict("Reservation is already cancelled")

    reservation.status = ReservationStatus.CANCELLED
    reservation.shipment.status = ShipmentStatus.CANCELLED
    db.commit()
    db.refresh(reservation)
    return reservation


def masked(shipment_id: uuid.UUID):
    return ContactOut(
        shipment_id=shipment_id,
        visible=False,
        counterparty_role=None,
        business_name=None,
        company_email=None,
        phone_number=None,
    )


def get_contact(db: Session, user: User, shipment_id: uuid.UUID):
    require_verified_company(user)
    shipment = reservations_repo.get_shipment(db, shipment_id)
    if shipment is None:
        raise not_found("Shipment not found")

    if user.role == UserRole.SHIPPER:
        if shipment.company_id != user.company_id:
            raise not_found("Shipment not found")
    elif not reservations_repo.company_has_match_for_shipment(
        db, user.company_id, shipment_id
    ):
        raise not_found("Shipment not found")

    reservation = reservations_repo.get_active_for_shipment(db, shipment_id)
    if reservation is None:
        return masked(shipment_id)

    if user.role == UserRole.SHIPPER:
        counterparty: Company = reservation.company
        role = "fleet"
    elif reservation.company_id == user.company_id:
        counterparty = shipment.company
        role = "shipper"
    else:
        return masked(shipment_id)

    return ContactOut(
        shipment_id=shipment_id,
        visible=True,
        counterparty_role=role,
        business_name=counterparty.business_name,
        company_email=counterparty.company_email,
        phone_number=counterparty.phone_number,
        reservation_id=reservation.reservation_id,
    )
