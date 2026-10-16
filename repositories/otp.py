from sqlalchemy.orm import Session

from models.otp import OTPCode


def create_otp(db: Session, user_id, code_hash: str, expires_at) -> OTPCode:
    record = OTPCode(user_id=user_id, code_hash=code_hash, expires_at=expires_at)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_latest_otp(db: Session, user_id) -> OTPCode | None:
    return (
        db.query(OTPCode)
        .filter(OTPCode.user_id == user_id)
        .order_by(OTPCode.created_at.desc())
        .first()
    )


def increment_attempts(db: Session, record: OTPCode) -> OTPCode:
    record.attempts += 1
    db.commit()
    db.refresh(record)
    return record


def delete_user_otps(db: Session, user_id) -> None:
    db.query(OTPCode).filter(OTPCode.user_id == user_id).delete()
    db.commit()
