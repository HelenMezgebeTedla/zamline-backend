from sqlalchemy.orm import Session

from models.companies import Company
from models.shipment_matches import ManagerDecision, ShipmentMatch
from models.shipments import Shipment, ShipmentStatus
from models.trucks import AvailabilityStatus, Truck


def get_company(db: Session, company_id):
    return db.query(Company).filter(Company.company_id == company_id).first()


def get_open_shipments(db: Session):
    return db.query(Shipment).filter(Shipment.status == ShipmentStatus.OPEN).all()


def get_available_trucks_for_company(db: Session, company_id):
    return (
        db.query(Truck)
        .filter(
            Truck.company_id == company_id,
            Truck.availability_status == AvailabilityStatus.AVAILABLE,
        )
        .all()
    )


def get_match(db: Session, shipment_id, truck_id):
    return (
        db.query(ShipmentMatch)
        .filter(
            ShipmentMatch.shipment_id == shipment_id,
            ShipmentMatch.truck_id == truck_id,
        )
        .first()
    )


def create_match(db: Session, shipment: Shipment, truck: Truck):
    match = ShipmentMatch(
        shipment_id=shipment.shipment_id,
        truck_id=truck.truck_id,
        proposed_amount=shipment.proposed_amount,
    )
    db.add(match)
    db.flush()
    return match


def get_current_matches_for_company(db: Session, company_id):
    return (
        db.query(ShipmentMatch)
        .join(Truck, ShipmentMatch.truck_id == Truck.truck_id)
        .join(Shipment, ShipmentMatch.shipment_id == Shipment.shipment_id)
        .filter(
            Truck.company_id == company_id,
            Shipment.status == ShipmentStatus.OPEN,
            ShipmentMatch.manager_decision == ManagerDecision.PENDING,
        )
        .order_by(ShipmentMatch.created_at.desc())
        .all()
    )
