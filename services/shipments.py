from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from config import UNACCEPTED_CARGO_TYPES
from models.shipments import ShipmentStatus
from repositories.shipments import (
    create_shipment as create_shipment_record,
)
from repositories.shipments import (
    get_company_shipment,
    list_company_shipments,
)
from repositories.shipments import (
    update_shipment as update_shipment_record,
)
from schemas.shipments import ShipmentCreate, ShipmentUpdate

ZAMBIA_TIME = timezone(timedelta(hours=2), "CAT")


def validate_cargo(cargo_type: str) -> None:
    if cargo_type.strip().lower() in UNACCEPTED_CARGO_TYPES:
        raise HTTPException(
            status_code=400,
            detail="This cargo type is not accepted in the ZamLine MVP",
        )


def combine_pickup(pickup_date: date, pickup_time: time) -> datetime:
    pickup = datetime.combine(pickup_date, pickup_time, tzinfo=ZAMBIA_TIME)
    if pickup <= datetime.now(ZAMBIA_TIME):
        raise HTTPException(
            status_code=422,
            detail="Pickup date and time must be in the future",
        )
    return pickup


def create_shipment(
    db: Session,
    company_id: UUID,
    user_id: UUID,
    data: ShipmentCreate,
):
    validate_cargo(data.cargo_type)
    pickup = combine_pickup(data.pickup_date, data.pickup_time)

    shipment = create_shipment_record(
        db,
        company_id=company_id,
        user_id=user_id,
        pickup_time=pickup,
        **data.model_dump(exclude={"pickup_date", "pickup_time"}),
    )
    db.commit()
    db.refresh(shipment)
    return shipment


def list_shipments(db: Session, company_id: UUID):
    return list_company_shipments(db, company_id)


def get_shipment(db: Session, company_id: UUID, shipment_id: UUID):
    shipment = get_company_shipment(db, company_id, shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found")
    return shipment


def update_shipment(
    db: Session,
    company_id: UUID,
    user_id: UUID,
    shipment_id: UUID,
    data: ShipmentUpdate,
):
    shipment = get_shipment(db, company_id, shipment_id)

    changes = data.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="No fields to update")

    if shipment.status != ShipmentStatus.OPEN:
        raise HTTPException(
            status_code=409,
            detail="Only open shipments can be updated",
        )

    if shipment.reservation is not None:
        raise HTTPException(
            status_code=409,
            detail="Shipments with a reservation cannot be updated",
        )

    if "cargo_type" in changes:
        validate_cargo(changes["cargo_type"])

    if "pickup_date" in changes:
        pickup_date = changes.pop("pickup_date")
        pickup_time = changes.pop("pickup_time")
        changes["pickup_time"] = combine_pickup(pickup_date, pickup_time)

    if "origin_address" in changes:
        changes["origin_latitude"] = None
        changes["origin_longitude"] = None

    if "destination_address" in changes:
        changes["destination_latitude"] = None
        changes["destination_longitude"] = None

    update_shipment_record(db, shipment, **changes)
    db.commit()
    db.refresh(shipment)
    return shipment


def cancel_shipment(
    db: Session,
    company_id: UUID,
    user_id: UUID,
    shipment_id: UUID,
):
    shipment = get_shipment(db, company_id, shipment_id)
    if shipment.status != ShipmentStatus.OPEN:
        raise HTTPException(
            status_code=409,
            detail="Only open shipments can be cancelled",
        )

    shipment.status = ShipmentStatus.CANCELLED
    db.commit()
    db.refresh(shipment)
    return shipment
