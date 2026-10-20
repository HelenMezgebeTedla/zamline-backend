from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.trucks import AvailabilityStatus, BodyType, Truck
from repositories.trucks import (
    create_truck as create_truck_record,
    get_active_reservation_for_truck,
    get_company_truck,
    get_truck_by_plate,
    search_company_trucks,
)
from schemas.trucks import (
    AllocatedShipment,
    TruckAllocationResponse,
    TruckAvailabilityUpdate,
    TruckCreate,
    TruckRetireRequest,
    TruckUpdate,
)
from models.audit_logs import AuditLog


def record_event(
    db: Session,
    action_type: str,
    user_id: UUID | None = None,
    company_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    details: dict | None = None,
):

    log = AuditLog(
        user_id=user_id,
        company_id=company_id,
        action_type=action_type,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )
    db.add(log)
    db.flush()
    return log


_LOAD_FIELDS = {"body_type", "capacity_kg"}


def _ensure_not_retired(truck: Truck) -> None:
    if truck.availability_status == AvailabilityStatus.RETIRED:
        raise HTTPException(
            status_code=409,
            detail="Truck is retired and can no longer be changed",
        )


def create_truck(
    db: Session,
    company_id: UUID,
    user_id: UUID,
    data: TruckCreate,
):
    if get_truck_by_plate(db, data.plate_number):
        raise HTTPException(status_code=409, detail="Truck registration already exists")

    try:
        truck = create_truck_record(
            db,
            company_id=company_id,
            **data.model_dump(),
        )
        record_event(
            db,
            "truck_created",
            user_id=user_id,
            company_id=company_id,
            entity_type="truck",
            entity_id=truck.truck_id,
            details={"plate_number": truck.plate_number},
        )
        db.commit()
        db.refresh(truck)
        return truck

    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Truck registration already exists")


def list_trucks(
    db: Session,
    company_id: UUID,
    availability_status: AvailabilityStatus | None = None,
    body_type: BodyType | None = None,
    include_retired: bool = False,
):
    return search_company_trucks(
        db,
        company_id,
        availability_status=availability_status,
        body_type=body_type,
        include_retired=include_retired,
    )


def get_truck(db: Session, company_id: UUID, truck_id: UUID):
    truck = get_company_truck(db, company_id, truck_id)
    if truck is None:
        raise HTTPException(status_code=404, detail="Truck not found")
    return truck


def update_truck(
    db: Session,
    company_id: UUID,
    user_id: UUID,
    truck_id: UUID,
    data: TruckUpdate,
):
    truck: Truck = get_truck(db, company_id, truck_id)
    _ensure_not_retired(truck)

    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No truck fields to update")

    if _LOAD_FIELDS & updates.keys() and get_active_reservation_for_truck(
        db, truck.truck_id
    ):
        raise HTTPException(
            status_code=409,
            detail="Body type and capacity cannot change while the truck "
            "is allocated to a confirmed shipment",
        )

    for field, value in updates.items():
        setattr(truck, field, value)

    record_event(
        db,
        "truck_updated",
        user_id=user_id,
        company_id=company_id,
        entity_type="truck",
        entity_id=truck.truck_id,
        details={"updated_fields": sorted(updates.keys())},
    )
    db.commit()
    db.refresh(truck)
    return truck


def update_availability(
    db: Session,
    company_id: UUID,
    user_id: UUID,
    truck_id: UUID,
    data: TruckAvailabilityUpdate,
):
    truck: Truck = get_truck(db, company_id, truck_id)
    _ensure_not_retired(truck)

    if data.availability_status == AvailabilityStatus.AVAILABLE and (
        get_active_reservation_for_truck(db, truck.truck_id)
    ):
        raise HTTPException(
            status_code=409,
            detail="Truck is allocated to a confirmed shipment and cannot be "
            "made available",
        )

    previous = truck.availability_status
    truck.availability_status = data.availability_status
    updates = data.model_dump(exclude_unset=True)
    if "available_from" in updates:
        truck.available_from = data.available_from
    if "current_location" in updates:
        truck.current_location = data.current_location

    record_event(
        db,
        "truck_availability_changed",
        user_id=user_id,
        company_id=company_id,
        entity_type="truck",
        entity_id=truck.truck_id,
        details={
            "from": previous.value,
            "to": data.availability_status.value,
        },
    )
    db.commit()
    db.refresh(truck)
    return truck


def retire_truck(
    db: Session,
    company_id: UUID,
    user_id: UUID,
    truck_id: UUID,
    data: TruckRetireRequest,
):
    truck: Truck = get_truck(db, company_id, truck_id)
    if truck.availability_status == AvailabilityStatus.RETIRED:
        raise HTTPException(status_code=409, detail="Truck is already retired")

    if get_active_reservation_for_truck(db, truck.truck_id):
        raise HTTPException(
            status_code=409,
            detail="Truck is allocated to a confirmed shipment and cannot be retired",
        )

    truck.availability_status = AvailabilityStatus.RETIRED
    record_event(
        db,
        "truck_retired",
        user_id=user_id,
        company_id=company_id,
        entity_type="truck",
        entity_id=truck.truck_id,
        details={"reason": data.reason} if data.reason else None,
    )
    db.commit()
    db.refresh(truck)
    return truck


def _allocation_for(db: Session, truck: Truck) -> TruckAllocationResponse:
    reservation = get_active_reservation_for_truck(db, truck.truck_id)
    allocated = None
    if reservation is not None:
        shipment = reservation.shipment
        allocated = AllocatedShipment(
            reservation_id=reservation.reservation_id,
            shipment_id=shipment.shipment_id,
            origin_address=shipment.origin_address,
            destination_address=shipment.destination_address,
            cargo_type=shipment.cargo_type,
            weight_kg=shipment.weight_kg,
            pickup_time=shipment.pickup_time,
            shipment_status=shipment.status,
            reserved_at=reservation.reserved_at,
        )
        allocation_status = "allocated"
    else:
        allocation_status = truck.availability_status.value

    return TruckAllocationResponse(
        truck_id=truck.truck_id,
        plate_number=truck.plate_number,
        availability_status=truck.availability_status,
        allocation_status=allocation_status,
        allocated_shipment=allocated,
    )


def get_truck_allocation(db: Session, company_id: UUID, truck_id: UUID):
    return _allocation_for(db, get_truck(db, company_id, truck_id))


def list_truck_allocations(db: Session, company_id: UUID):
    trucks = search_company_trucks(db, company_id, include_retired=False)
    return [_allocation_for(db, truck) for truck in trucks]
