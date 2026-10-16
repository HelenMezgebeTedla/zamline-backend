import re
from typing import NoReturn

from fastapi import HTTPException

BUSINESS_NAME_MAX = 100
REGISTRATION_NUMBER_MAX = 20
PHONE_MAX = 15

REGISTRATION_NUMBER_PATTERN = re.compile(r"^[A-Z0-9]{5,20}$")
PHONE_PATTERN = re.compile(r"^\+?[0-9]{7,15}$")


def enum_value(item) -> str:
    return str(getattr(item, "value", item))


def iso_or_none(value) -> str | None:
    return value.isoformat() if value else None


def text_or_none(value) -> str | None:
    return None if value is None else str(value)


def normalise_email(email) -> str:
    return str(email).strip().lower()


def reject(message: str) -> NoReturn:
    raise HTTPException(status_code=422, detail=message)


def clean_text(value: str | None, label: str, max_length: int) -> str:
    cleaned = " ".join((value or "").split())
    if not cleaned:
        reject(f"{label} cannot be empty")
    if len(cleaned) > max_length:
        reject(f"{label} must not exceed {max_length} characters")
    return cleaned


def validate_company_fields(
    business_name: str | None = None,
    registration_number: str | None = None,
    phone_number: str | None = None,
) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    if business_name is not None:
        cleaned["business_name"] = clean_text(
            business_name, "Business name", BUSINESS_NAME_MAX
        )
    if registration_number is not None:
        number = clean_text(
            registration_number, "Registration number", REGISTRATION_NUMBER_MAX
        ).upper()
        if not REGISTRATION_NUMBER_PATTERN.match(number):
            reject("Registration number must be 5 to 20 letters or digits")
        cleaned["registration_number"] = number
    if phone_number is not None:
        phone = clean_text(
            re.sub(r"[\s()-]", "", phone_number or ""), "Phone number", PHONE_MAX
        )
        if not PHONE_PATTERN.match(phone):
            reject("Phone number must be 7 to 15 digits with an optional + prefix")
        cleaned["phone_number"] = phone
    return cleaned


def get_company_profile(company) -> dict:
    return {
        "company_id": str(company.company_id),
        "company_type": enum_value(company.company_type),
        "business_name": company.business_name,
        "registration_number": company.registration_number,
        "company_email": company.company_email,
        "phone_number": company.phone_number,
        "verification_status": enum_value(company.verification_status),
        "verified_at": iso_or_none(company.verified_at),
        "certificate_file_url": company.certificate_file_url,
        "verification_failure_reason": company.verification_failure_reason,
        "fuel_price_per_litre": text_or_none(company.fuel_price_per_litre),
        "driver_daily_allowance": text_or_none(company.driver_daily_allowance),
        "toll_assumption": text_or_none(company.toll_assumption),
        "other_costs": text_or_none(company.other_costs),
        "created_at": iso_or_none(company.created_at),
        "updated_at": iso_or_none(company.updated_at),
    }
