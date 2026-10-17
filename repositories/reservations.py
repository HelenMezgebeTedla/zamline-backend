import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from models.reservations import Reservation, ReservationStatus
from models.shipment_matches import ManagerDecision, ShipmentMatch
from models.shipments import Shipment, ShipmentStatus
from models.trucks import Truck
from models.users import User, UserRole


def create(db: Session, reservation: Reservation):
    db.add(reservation)
    db.flush()
    return reservation


def visible_to(db: Session, user: User):
    query = db.query(Reservation).join(
        Shipment, Shipment.shipment_id == Reservation.shipment_id
    )
    if user.role == UserRole.FLEET_MANAGER:
        return query.filter(Reservation.company_id == user.company_id)
    return query.filter(Shipment.company_id == user.company_id)


def list_for_user(db: Session, user: User, status: ReservationStatus | None = None):
    query = visible_to(db, user)
    if status:
        query = query.filter(Reservation.status == status)
    return query.order_by(Reservation.reserved_at.desc()).all()


def get_for_user(db: Session, user: User, reservation_id: uuid.UUID):
    return (
        visible_to(db, user)
        .filter(Reservation.reservation_id == reservation_id)
        .first()
    )


def get_active_for_shipment(db: Session, shipment_id: uuid.UUID):
    return (
        db.query(Reservation)
        .filter(
            Reservation.shipment_id == shipment_id,
            Reservation.status == ReservationStatus.ACCEPTED,
        )
        .first()
    )


def get_match(db: Session, match_id: uuid.UUID):
    return db.query(ShipmentMatch).filter(ShipmentMatch.match_id == match_id).first()


def get_shipment(db: Session, shipment_id: uuid.UUID):
    return db.query(Shipment).filter(Shipment.shipment_id == shipment_id).first()


def get_shipment_status(db: Session, shipment_id: uuid.UUID):
    row = db.query(Shipment.status).filter(Shipment.shipment_id == shipment_id).first()
    return row.status if row else None


def claim_shipment_if_open(db: Session, shipment_id: uuid.UUID):
    updated = (
        db.query(Shipment)
        .filter(
            Shipment.shipment_id == shipment_id, Shipment.status == ShipmentStatus.OPEN
        )
        .update({Shipment.status: ShipmentStatus.CONFIRMED}, synchronize_session=False)
    )
    return updated == 1


def company_has_match_for_shipment(
    db: Session, company_id: uuid.UUID, shipment_id: uuid.UUID
):
    match = (
        db.query(ShipmentMatch)
        .join(Truck, Truck.truck_id == ShipmentMatch.truck_id)
        .filter(
            ShipmentMatch.shipment_id == shipment_id, Truck.company_id == company_id
        )
        .first()
    )
    return match is not None


def mark_match_accepted(match: ShipmentMatch, user_id: uuid.UUID, when: datetime):
    match.manager_decision = ManagerDecision.ACCEPTED
    match.user_id = user_id
    match.decided_at = when


def close_other_pending_matches(
    db: Session, shipment_id: uuid.UUID, keep_match_id: uuid.UUID, when: datetime
):
    (
        db.query(ShipmentMatch)
        .filter(
            ShipmentMatch.shipment_id == shipment_id,
            ShipmentMatch.match_id != keep_match_id,
            ShipmentMatch.manager_decision == ManagerDecision.PENDING,
        )
        .update(
            {
                ShipmentMatch.manager_decision: ManagerDecision.CLOSED,
                ShipmentMatch.decided_at: when,
            },
            synchronize_session=False,
        )
    )
