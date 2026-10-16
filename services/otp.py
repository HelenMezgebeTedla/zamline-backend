import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from config import JWT_SECRET, OTP_EXPIRE_MINUTES, OTP_MAX_ATTEMPTS
from repositories.otp import (
    create_otp,
    delete_user_otps,
    get_latest_otp,
    increment_attempts,
)
from security.email import send_otp_email

logger = logging.getLogger(__name__)

RESEND_COOLDOWN_SECONDS = 60
OTP_LENGTH = 6


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _hash_code(user_id, code: str) -> str:
    return hmac.new(
        JWT_SECRET.encode("utf-8"),
        f"{user_id}:{code}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def validate_code(value: str | None) -> str:
    cleaned = (value or "").strip()
    if len(cleaned) != OTP_LENGTH or not (cleaned.isascii() and cleaned.isdigit()):
        raise HTTPException(
            status_code=422,
            detail=f"OTP must be a {OTP_LENGTH}-digit number",
        )
    return cleaned


def _invalid_code() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid or expired code",
    )


def issue_otp(db: Session, user, enforce_cooldown: bool = False) -> bool:
    if enforce_cooldown:
        latest = get_latest_otp(db, user.user_id)
        if latest and _now() - _as_utc(latest.created_at) < timedelta(
            seconds=RESEND_COOLDOWN_SECONDS
        ):
            return False

    code = f"{secrets.randbelow(10**OTP_LENGTH):0{OTP_LENGTH}d}"
    delete_user_otps(db, user.user_id)
    create_otp(
        db,
        user.user_id,
        _hash_code(user.user_id, code),
        _now() + timedelta(minutes=OTP_EXPIRE_MINUTES),
    )

    try:
        send_otp_email(user.email, code)
    except Exception as exc:
        logger.error("Could not send OTP email: %s", type(exc).__name__)
        delete_user_otps(db, user.user_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not send the verification code. Try again later.",
        ) from exc
    return True


def check_otp(db: Session, user, code: str) -> None:
    record = get_latest_otp(db, user.user_id)
    if record is None:
        raise _invalid_code()

    if _now() > _as_utc(record.expires_at):
        delete_user_otps(db, user.user_id)
        raise _invalid_code()

    if record.attempts >= OTP_MAX_ATTEMPTS:
        delete_user_otps(db, user.user_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Too many attempts. Request a new code.",
        )

    if not hmac.compare_digest(record.code_hash, _hash_code(user.user_id, code)):
        record = increment_attempts(db, record)
        remaining = max(OTP_MAX_ATTEMPTS - record.attempts, 0)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid code. {remaining} attempts remaining.",
        )

    delete_user_otps(db, user.user_id)
