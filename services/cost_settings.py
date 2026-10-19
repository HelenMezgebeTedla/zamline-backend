from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models.audit_logs import AuditLog
from models.companies import CompanyType
from repositories.cost_settings import get_cost_settings_company
from schemas.cost_settings import EXTREME_VALUE_LIMITS, CostSettingsUpdate


def record_event(
    db: Session,
    action_type: str,
    user_id: UUID | None = None,
    company_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    details: dict | None = None,
):
    """Write one audit log row. Kept here so this feature doesn't depend on
    the shared services/audit_logs.py, which another teammate owns."""
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


def get_cost_settings(db: Session, company_id: UUID):
    company = get_cost_settings_company(db, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    if company.company_type != CompanyType.FLEET:
        raise HTTPException(status_code=403, detail="Fleet company required")
    return company


def update_cost_settings(
    db: Session,
    company_id: UUID,
    user_id: UUID,
    data: CostSettingsUpdate,
):
    company = get_cost_settings(db, company_id)
    updates = data.money_updates()
    if not updates:
        raise HTTPException(status_code=400, detail="No cost settings to update")

    if "fuel_price_per_litre" in updates and updates["fuel_price_per_litre"] is None:
        raise HTTPException(
            status_code=422,
            detail="fuel_price_per_litre cannot be cleared",
        )

    extreme = data.extreme_fields()
    if extreme and not data.confirm_extreme_values:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Some values are unusually high. Check them, then "
                "send again with confirm_extreme_values set to true.",
                "fields": {
                    name: {
                        "value": str(updates[name]),
                        "limit": str(EXTREME_VALUE_LIMITS[name]),
                    }
                    for name in extreme
                },
            },
        )

    for field, value in updates.items():
        setattr(company, field, value)

   
    record_event(
        db,
        "cost_settings_updated",
        user_id=user_id,
        company_id=company_id,
        entity_type="company",
        entity_id=company_id,
        details={
            "updated_fields": sorted(updates.keys()),
            "extreme_values_confirmed": sorted(extreme),
        },
    )
    db.commit()
    db.refresh(company)
    return company