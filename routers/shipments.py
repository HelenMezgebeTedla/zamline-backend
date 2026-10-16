from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from schemas.shipments import ShipmentCreate, ShipmentResponse
from services.shipments import (
    cancel_shipment,
    create_shipment,
    get_shipment,
    list_shipments,
)

router = APIRouter(prefix="/shipments", tags=["shipments"])


def shipper():
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Login is not available yet",
    )


def require_verified_company():
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Company verification is not available yet",
    )


@router.post("", response_model=ShipmentResponse, status_code=status.HTTP_201_CREATED)
def create(
    payload: ShipmentCreate,
    db: Session = Depends(get_db),
    current_user=Depends(shipper),
    company=Depends(require_verified_company),
):
    return create_shipment(db, company.company_id, current_user.user_id, payload)


@router.get("", response_model=list[ShipmentResponse])
def list_all(
    db: Session = Depends(get_db),
    current_user=Depends(shipper),
    company=Depends(require_verified_company),
):
    return list_shipments(db, company.company_id)


@router.get("/{shipment_id}", response_model=ShipmentResponse)
def read(
    shipment_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(shipper),
    company=Depends(require_verified_company),
):
    return get_shipment(db, company.company_id, shipment_id)


@router.post("/{shipment_id}/cancel", response_model=ShipmentResponse)
def cancel(
    shipment_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(shipper),
    company=Depends(require_verified_company),
):
    return cancel_shipment(
        db,
        company.company_id,
        current_user.user_id,
        shipment_id,
    )
