from uuid import UUID
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from database import get_db
from dependency import require_role, require_verified_company
from models.trucks import AvailabilityStatus, BodyType
from models.users import UserRole
from schemas.trucks import (
    TruckAllocationResponse,
    TruckAvailabilityUpdate,
    TruckCreate,
    TruckResponse,
    TruckRetireRequest,
    TruckUpdate,
)
from services.trucks import (
    create_truck,
    get_truck,
    get_truck_allocation,
    list_truck_allocations,
    list_trucks,
    retire_truck,
    update_availability,
    update_truck,
)

router = APIRouter(prefix="/trucks", tags=["fleet"])

fleet_manager = require_role(UserRole.FLEET_MANAGER)


@router.post("", response_model=TruckResponse, status_code=status.HTTP_201_CREATED)
def create(
    payload: TruckCreate,
    db: Session = Depends(get_db),
    current_user=Depends(fleet_manager),
    company=Depends(require_verified_company),
):
    return create_truck(db, company.company_id, current_user.user_id, payload)


@router.get("", response_model=list[TruckResponse])
def list_all(
    availability_status: AvailabilityStatus | None = None,
    body_type: BodyType | None = None,
    include_retired: bool = False,
    db: Session = Depends(get_db),
    current_user=Depends(fleet_manager),
    company=Depends(require_verified_company),
):
    return list_trucks(
        db,
        company.company_id,
        availability_status=availability_status,
        body_type=body_type,
        include_retired=include_retired,
    )


@router.get("/allocations", response_model=list[TruckAllocationResponse])
def allocations(
    db: Session = Depends(get_db),
    current_user=Depends(fleet_manager),
    company=Depends(require_verified_company),
):
    return list_truck_allocations(db, company.company_id)


@router.get("/{truck_id}", response_model=TruckResponse)
def read(
    truck_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(fleet_manager),
    company=Depends(require_verified_company),
):
    return get_truck(db, company.company_id, truck_id)


@router.patch("/{truck_id}", response_model=TruckResponse)
def update(
    truck_id: UUID,
    payload: TruckUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(fleet_manager),
    company=Depends(require_verified_company),
):
    return update_truck(
        db,
        company.company_id,
        current_user.user_id,
        truck_id,
        payload,
    )


@router.patch("/{truck_id}/availability", response_model=TruckResponse)
def change_availability(
    truck_id: UUID,
    payload: TruckAvailabilityUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(fleet_manager),
    company=Depends(require_verified_company),
):
    return update_availability(
        db,
        company.company_id,
        current_user.user_id,
        truck_id,
        payload,
    )


@router.post("/{truck_id}/retire", response_model=TruckResponse)
def retire(
    truck_id: UUID,
    payload: TruckRetireRequest | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(fleet_manager),
    company=Depends(require_verified_company),
):
    return retire_truck(
        db,
        company.company_id,
        current_user.user_id,
        truck_id,
        payload or TruckRetireRequest(),
    )


@router.get("/{truck_id}/allocation", response_model=TruckAllocationResponse)
def allocation(
    truck_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(fleet_manager),
    company=Depends(require_verified_company),
):
    return get_truck_allocation(db, company.company_id, truck_id)
