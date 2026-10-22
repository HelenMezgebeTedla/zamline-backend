from decimal import Decimal
from uuid import UUID
from models.users import User


from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.companies import Company, CompanyType, VerificationStatus
from repositories.companies import (
    get_company_by_email,
    get_company_by_registration_number,
)
from repositories.cost_settings import (
    add_company_with_cost_settings,
    get_cost_settings_company,
)
from schemas.cost_settings import (
    EXTREME_VALUE_LIMITS,
    CostSettingsCreate,
    CostSettingsUpdate,
    CostSettingsValues,
)
from services.audit_logs import log_action


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

    log_action(
        db,
        "cost_settings_updated",
        user=User(user_id=user_id),
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


def check_cost_settings(
    data: CostSettingsValues | None,
    company_type: CompanyType,
) -> None:

    if data is None:
        return
    if company_type != CompanyType.FLEET:
        raise HTTPException(
            status_code=400,
            detail="Internal cost settings are for fleet companies only",
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
                        "value": str(data.money_values()[name]),
                        "limit": str(EXTREME_VALUE_LIMITS[name]),
                    }
                    for name in extreme
                },
            },
        )


def cost_settings_updates(data: CostSettingsValues | None) -> dict[str, Decimal | None]:

    if data is None:
        return {}
    return data.money_updates()


def post_company_cost_settings(
    db: Session,
    user_id: UUID,
    data: CostSettingsCreate,
) -> Company:

    registration_number = data.registration_number
    company_email = str(data.company_email).lower()

    if get_company_by_registration_number(db, registration_number):
        raise HTTPException(
            status_code=409,
            detail="Registration number is already registered",
        )
    if get_company_by_email(db, company_email):
        raise HTTPException(
            status_code=409,
            detail="Company email is already registered",
        )

    check_cost_settings(data, CompanyType.FLEET)

    try:
        company = add_company_with_cost_settings(
            db,
            company_type=CompanyType.FLEET,
            business_name=data.business_name,
            registration_number=registration_number,
            company_email=company_email,
            phone_number=data.phone_number,
            verification_status=VerificationStatus.PENDING,
            **data.money_values(),
        )

        log_action(
            db,
            "cost_settings_posted",
            user=User(user_id=user_id),
            company_id=company.company_id,
            entity_type="company",
            entity_id=company.company_id,
            details={"posted_fields": sorted(data.money_values().keys())},
        )
        db.commit()
        db.refresh(company)
        return company
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Registration number is already registered",
        )
