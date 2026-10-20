from __future__ import annotations
from uuid import UUID
from sqlalchemy.orm import Session

from models.reservations import Reservation, ReservationStatus
from models.shipments import Shipment, ShipmentStatus
from models.trucks import AvailabilityStatus, BodyType, Truck


def create_truck(db: Session, **values):
    truck = Truck(**values)
    db.add(truck)
    db.flush()
    return truck


def get_truck_by_id(db: Session, truck_id: UUID):
    return db.query(Truck).filter(Truck.truck_id == truck_id).first()


def get_truck_by_plate(db: Session, plate_number: str):
    return db.query(Truck).filter(Truck.plate_number == plate_number).first()


def get_company_truck(db: Session, company_id: UUID, truck_id: UUID):
    return (
        db.query(Truck)
        .filter(Truck.company_id == company_id, Truck.truck_id == truck_id)
        .first()
    )


def list_company_trucks(db: Session, company_id: UUID):
    return db.query(Truck).filter(Truck.company_id == company_id).all()


def search_company_trucks(
    db: Session,
    company_id: UUID,
    availability_status: AvailabilityStatus | None = None,
    body_type: BodyType | None = None,
    include_retired: bool = False,
):
    query = db.query(Truck).filter(Truck.company_id == company_id)
    if availability_status is not None:
        query = query.filter(Truck.availability_status == availability_status)
    elif not include_retired:
        query = query.filter(Truck.availability_status != AvailabilityStatus.RETIRED)
    if body_type is not None:
        query = query.filter(Truck.body_type == body_type)
    return query.order_by(Truck.created_at, Truck.plate_number).all()


def list_available_company_trucks(db: Session, company_id: UUID):
    return (
        db.query(Truck)
        .filter(
            Truck.company_id == company_id,
            Truck.availability_status == AvailabilityStatus.AVAILABLE,
        )
        .all()
    )

def get_active_reservation_for_truck(db: Session, truck_id: UUID):
    return (
        db.query(Reservation)
        .join(Shipment, Shipment.shipment_id == Reservation.shipment_id)
        .filter(
            Reservation.truck_id == truck_id,
            Reservation.status == ReservationStatus.ACCEPTED,
            Shipment.status == ShipmentStatus.CONFIRMED,
        )
        
        .order_by(Reservation.created_at.desc())
        .first()
    )