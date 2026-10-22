import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from database import get_db
from dependency import require_role, require_verified_company
from models.users import UserRole
from schemas.cost_settings import (
    CostSettingsCreate,
    CostSettingsPostResponse,
    CostSettingsResponse,
    CostSettingsUpdate,
)
from services.cost_settings import (
    get_cost_settings,
    post_company_cost_settings,
    update_cost_settings,
)

router = APIRouter(tags=["fleet"])


fleet_manager = require_role(UserRole.FLEET_MANAGER)


@router.post(
    "/cost-settings",
    response_model=CostSettingsPostResponse,
    status_code=status.HTTP_201_CREATED,
)
def post(
    payload: CostSettingsCreate,
    db: Session = Depends(get_db),
    current_user=Depends(fleet_manager),
    company=Depends(require_verified_company),
):
  
    return post_company_cost_settings(db, current_user.user_id, payload)

@router.get("/companies/{company_id}/cost-settings", response_model=CostSettingsResponse)
def read(
    company_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user=Depends(fleet_manager),
    company=Depends(require_verified_company),
):

    return get_cost_settings(db, company.company_id)


@router.patch("/companies/{company_id}/cost-settings", response_model=CostSettingsResponse)
def update(
    company_id: uuid.UUID,
    payload: CostSettingsUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(fleet_manager),
    company=Depends(require_verified_company),
):
    return update_cost_settings(
        db,
        company_id,
        current_user.user_id,
        payload,
    )