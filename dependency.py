from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from database import get_db
from models.users import UserRole
from services.auth import (
    authenticate_token,
    ensure_role,
    ensure_verified,
    get_company_for_user,
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/users/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    return authenticate_token(db, token)


def get_current_company(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_company_for_user(db, current_user)


def require_role(*allowed_roles: UserRole):
    def role_dependency(current_user=Depends(get_current_user)):
        ensure_role(current_user, allowed_roles)
        return current_user

    return role_dependency


def require_verified_company(company=Depends(get_current_company)):
    ensure_verified(company)
    return company
