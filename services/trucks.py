from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models.trucks import AvailabilityStatus, BodyType, Truck
from repositories.audit_logs import create_audit_log
from repositories.trucks import (
    DuplicatePlateError,
    get_active_reservation_for_truck,
    get_company_truck,
    get_truck_by_plate,
    save_truck,
    search_company_trucks,
)
from repositories.trucks import create_truck as create_truck_record
from schemas.trucks import (
    AllocatedShipment,
    TruckAllocationResponse,
    TruckAvailabilityUpdate,
    TruckCreate,
    TruckRetireRequest,
    TruckUpdate,
)

LOCKED_WHILE_ALLOCATED = {"body_type", "capacity_kg"}

DUPLICATE_PLATE = "Truck registration already exists"


def _is_allocated(db: Session, truck: Truck) -> bool:
    """A truck is allocated when it has an accepted reservation on a confirmed
    shipment."""
    return get_active_reservation_for_truck(db, truck.truck_id) is not None


def _reject_if_retired(truck: Truck, message: str) -> None:
    if truck.availability_status == AvailabilityStatus.RETIRED:
        raise HTTPException(status_code=409, detail=message)


def _reject_if_allocated(db: Session, truck: Truck, message: str) -> None:
    if _is_allocated(db, truck):
        raise HTTPException(status_code=409, detail=message)


def _audit(
    db: Session,
    action: str,
    user_id: UUID,
    truck: Truck,
    details: dict | None = None,
) -> None:
    create_audit_log(
        db,
        user_id=user_id,
        company_id=truck.company_id,
        action_type=action,
        entity_type="truck",
        entity_id=truck.truck_id,
        details=details,
    )

def get_truck(db: Session, company_id: UUID, truck_id: UUID) -> Truck:
    truck = get_company_truck(db, company_id, truck_id)
    if truck is None:
        raise HTTPException(status_code=404, detail="Truck not found")
    return truck


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

def create_truck(db: Session, company_id: UUID, user_id: UUID, data: TruckCreate):
    if get_truck_by_plate(db, data.plate_number):
        raise HTTPException(status_code=409, detail=DUPLICATE_PLATE)

    try:
        truck = create_truck_record(db, company_id=company_id, **data.model_dump())
        _audit(
            db, "truck_created", user_id, truck, {"plate_number": truck.plate_number}
        )
        return save_truck(db, truck)
    except DuplicatePlateError:
        raise HTTPException(status_code=409, detail=DUPLICATE_PLATE)


def update_truck(
    db: Session, company_id: UUID, user_id: UUID, truck_id: UUID, data: TruckUpdate
):
    truck = get_truck(db, company_id, truck_id)
    _reject_if_retired(truck, "Truck is retired and can no longer be changed")

    changes = data.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="No truck fields to update")

    if LOCKED_WHILE_ALLOCATED & changes.keys():
        _reject_if_allocated(
            db,
            truck,
            "Body type and capacity cannot change while the truck "
            "is allocated to a confirmed shipment",
        )

    for field, value in changes.items():
        setattr(truck, field, value)

    _audit(db, "truck_updated", user_id, truck, {"updated_fields": sorted(changes)})
    return save_truck(db, truck)


def update_availability(
    db: Session,
    company_id: UUID,
    user_id: UUID,
    truck_id: UUID,
    data: TruckAvailabilityUpdate,
):
    truck = get_truck(db, company_id, truck_id)
    _reject_if_retired(truck, "Truck is retired and can no longer be changed")

    if data.availability_status == AvailabilityStatus.AVAILABLE:
        _reject_if_allocated(
            db,
            truck,
            "Truck is allocated to a confirmed shipment and cannot be made available",
        )

    previous = truck.availability_status
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(truck, field, value)

    _audit(
        db,
        "truck_availability_changed",
        user_id,
        truck,
        {"from": previous.value, "to": truck.availability_status.value},
    )
    return save_truck(db, truck)


def retire_truck(
    db: Session,
    company_id: UUID,
    user_id: UUID,
    truck_id: UUID,
    data: TruckRetireRequest,
):
    truck = get_truck(db, company_id, truck_id)
    _reject_if_retired(truck, "Truck is already retired")
    _reject_if_allocated(
        db, truck, "Truck is allocated to a confirmed shipment and cannot be retired"
    )

    truck.availability_status = AvailabilityStatus.RETIRED

    _audit(
        db,
        "truck_retired",
        user_id,
        truck,
        {"reason": data.reason} if data.reason else None,
    )
    return save_truck(db, truck)


def _allocation_summary(db: Session, truck: Truck) -> TruckAllocationResponse:
    """Is this truck on a confirmed shipment,if it is, which one?"""
    reservation = get_active_reservation_for_truck(db, truck.truck_id)

    if reservation is None:
        # Not allocated: report the truck's own availability instead.
        return TruckAllocationResponse(
            truck_id=truck.truck_id,
            plate_number=truck.plate_number,
            availability_status=truck.availability_status,
            allocation_status=truck.availability_status.value,
            allocated_shipment=None,
        )

    shipment = reservation.shipment
    return TruckAllocationResponse(
        truck_id=truck.truck_id,
        plate_number=truck.plate_number,
        availability_status=truck.availability_status,
        allocation_status="allocated",
        allocated_shipment=AllocatedShipment(
            reservation_id=reservation.reservation_id,
            shipment_id=shipment.shipment_id,
            origin_address=shipment.origin_address,
            destination_address=shipment.destination_address,
            cargo_type=shipment.cargo_type,
            weight_kg=shipment.weight_kg,
            pickup_time=shipment.pickup_time,
            shipment_status=shipment.status,
            reserved_at=reservation.reserved_at,
        ),
    )


def get_truck_allocation(db: Session, company_id: UUID, truck_id: UUID):
    return _allocation_summary(db, get_truck(db, company_id, truck_id))


def list_truck_allocations(db: Session, company_id: UUID):
    trucks = search_company_trucks(db, company_id, include_retired=False)
    return [_allocation_summary(db, truck) for truck in trucks]