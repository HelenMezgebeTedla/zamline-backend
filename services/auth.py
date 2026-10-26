from uuid import UUID

import jwt
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models.companies import VerificationStatus
from repositories.companies import get_company_by_id
from repositories.users import get_user_by_id
from security.tokens import decode_access_token
from services.sessions import ensure_session_active


def authenticate_token(db: Session, token: str):
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_access_token(token)
        user_id = UUID(payload["sub"])
    except (KeyError, ValueError, jwt.PyJWTError):
        raise credentials_error from None

    user = get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        raise credentials_error
    if payload.get("sid") is not None:
        ensure_session_active(payload["sid"])
    return user


def get_company_for_user(db: Session, user):
    company = get_company_by_id(db, user.company_id)
    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Company not found"
        )
    return company


def ensure_role(user, allowed_roles) -> None:
    if user.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )


def ensure_verified(company) -> None:
    if company.verification_status != VerificationStatus.VERIFIED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Company is not verified"
        )
