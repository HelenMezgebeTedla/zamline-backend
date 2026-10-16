import secrets
from functools import lru_cache

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from repositories.audit_logs import create_audit_log
from repositories.companies import (
    create_company,
    get_company_by_email,
    get_company_by_registration_number,
)
from repositories.users import (
    create_user,
    get_user_by_email,
    update_user,
)
from schemas.users import (
    CompanyRegistrationSchema,
    OTPVerifySchema,
    ResendOTPSchema,
    UserLoginSchema,
    UserUpdateSchema,
)
from security.password import hash_password, verify_password
from security.tokens import create_access_token
from services import otp as otp_service
from services.companies import (
    clean_text,
    enum_value,
    get_company_profile,
    iso_or_none,
    normalise_email,
    reject,
    validate_company_fields,
)

DELETION_GRACE_PERIOD_DAYS = 30
OTP_SENT_MESSAGE = "If the account exists, a verification code has been sent"

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_BYTES = 128
PERSON_NAME_MAX = 50


@lru_cache(maxsize=1)
def _unknown_user_hash() -> str:
    return hash_password(secrets.token_urlsafe(16))


def validate_password(value: str | None) -> str:
    if not value:
        reject("Password cannot be empty")
    if len(value) < PASSWORD_MIN_LENGTH:
        reject(f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
    if len(value.encode("utf-8")) > PASSWORD_MAX_BYTES:
        reject(f"Password must not exceed {PASSWORD_MAX_BYTES} bytes")
    return value


def user_to_dict(user) -> dict:
    return {
        "user_id": str(user.user_id),
        "company_id": str(user.company_id),
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "role": enum_value(user.role),
        "is_active": user.is_active,
        "created_at": iso_or_none(user.created_at),
    }


def register_user(db: Session, data: CompanyRegistrationSchema) -> dict:
    company_fields = validate_company_fields(
        business_name=data.business_name,
        registration_number=data.registration_number,
        phone_number=data.phone_number,
    )
    first_name = clean_text(data.first_name, "First name", PERSON_NAME_MAX)
    last_name = clean_text(data.last_name, "Last name", PERSON_NAME_MAX)
    validate_password(data.password)

    email = normalise_email(data.company_email)

    if get_company_by_email(db, email) or get_user_by_email(db, email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Company email already registered",
        )

    if get_company_by_registration_number(db, company_fields["registration_number"]):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Company registration number already registered",
        )

    company_type = enum_value(data.company_type)
    role = "fleet_manager" if company_type == "fleet" else "shipper"

    try:
        company = create_company(
            db,
            company_type=company_type,
            business_name=company_fields["business_name"],
            registration_number=company_fields["registration_number"],
            company_email=email,
            phone_number=company_fields["phone_number"],
            commit=False,
        )
        user = create_user(
            db,
            company_id=company.company_id,
            first_name=first_name,
            last_name=last_name,
            email=email,
            password_hash=hash_password(data.password),
            role=role,
            commit=False,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Company or email already registered",
        ) from None

    db.refresh(company)
    db.refresh(user)

    create_audit_log(
        db,
        user_id=user.user_id,
        company_id=company.company_id,
        action_type="user_registered",
        entity_type="user",
        entity_id=user.user_id,
        details={"role": role},
    )

    return {"user": user_to_dict(user), "company": get_company_profile(company)}


def login_user(db: Session, data: UserLoginSchema) -> dict:
    user = get_user_by_email(db, normalise_email(data.email))

    password_ok = False
    if len(data.password.encode("utf-8")) <= PASSWORD_MAX_BYTES:
        password_ok = verify_password(
            data.password, user.password_hash if user else _unknown_user_hash()
        )
    if not user or not password_ok:
        create_audit_log(
            db,
            user_id=user.user_id if user else None,
            company_id=user.company_id if user else None,
            action_type="login_failed",
            entity_type="user",
            entity_id=user.user_id if user else None,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    otp_service.issue_otp(db, user)
    create_audit_log(
        db,
        user_id=user.user_id,
        company_id=user.company_id,
        action_type="login_otp_sent",
        entity_type="user",
        entity_id=user.user_id,
    )
    return {
        "otp_required": True,
        "message": "A verification code has been sent to your email",
    }


def verify_otp(db: Session, data: OTPVerifySchema) -> dict:
    code = otp_service.validate_code(data.code)
    user = get_user_by_email(db, normalise_email(data.email))

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired code",
        )

    try:
        otp_service.check_otp(db, user, code)
    except HTTPException:
        create_audit_log(
            db,
            user_id=user.user_id,
            company_id=user.company_id,
            action_type="otp_failed",
            entity_type="user",
            entity_id=user.user_id,
        )
        raise

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    create_audit_log(
        db,
        user_id=user.user_id,
        company_id=user.company_id,
        action_type="login",
        entity_type="user",
        entity_id=user.user_id,
    )
    return {
        "access_token": create_access_token(user.user_id, enum_value(user.role)),
        "token_type": "bearer",
    }


def resend_otp(db: Session, data: ResendOTPSchema) -> dict:
    user = get_user_by_email(db, normalise_email(data.email))

    if user is not None and user.is_active:
        sent = otp_service.issue_otp(db, user, enforce_cooldown=True)
        if sent:
            create_audit_log(
                db,
                user_id=user.user_id,
                company_id=user.company_id,
                action_type="otp_resent",
                entity_type="user",
                entity_id=user.user_id,
            )

    return {"message": OTP_SENT_MESSAGE}


def get_current_user_profile(user) -> dict:
    return user_to_dict(user)


def update_current_user(db: Session, user, data: UserUpdateSchema) -> dict:
    changes: dict[str, str] = {}

    if data.first_name is not None:
        changes["first_name"] = clean_text(
            data.first_name, "First name", PERSON_NAME_MAX
        )
    if data.last_name is not None:
        changes["last_name"] = clean_text(data.last_name, "Last name", PERSON_NAME_MAX)
    if data.email is not None:
        new_email = normalise_email(data.email)
        if new_email != user.email:
            if get_user_by_email(db, new_email):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Email already in use",
                )
            changes["email"] = new_email

    if not changes:
        return user_to_dict(user)

    try:
        updated_user = update_user(db, user, **changes)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already in use",
        ) from None

    create_audit_log(
        db,
        user_id=user.user_id,
        company_id=user.company_id,
        action_type="user_updated",
        entity_type="user",
        entity_id=user.user_id,
        details={"fields": sorted(changes)},
    )
    return user_to_dict(updated_user)


def delete_current_user(db: Session, user) -> None:
    update_user(db, user, is_active=False)
    create_audit_log(
        db,
        user_id=user.user_id,
        company_id=user.company_id,
        action_type="user_deletion_requested",
        entity_type="user",
        entity_id=user.user_id,
        details={"grace_period_days": DELETION_GRACE_PERIOD_DAYS},
    )
