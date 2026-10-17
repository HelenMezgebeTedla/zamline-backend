import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models.audit_logs import AuditLog
from models.users import User
from repositories import audit_logs as audit_repo


class ActionType(StrEnum):
    VERIFICATION_ATTEMPTED = "verification_attempted"
    SHIPMENT_PUBLISHED = "shipment_published"
    SHIPMENT_VIEWED = "shipment_viewed"
    FLEET_UPDATED = "fleet_updated"
    COST_SETTINGS_UPDATED = "cost_settings_updated"
    ASSESSMENT_REQUESTED = "assessment_requested"
    SHIPMENT_ACCEPTED = "shipment_accepted"
    ACCEPTANCE_REJECTED = "acceptance_rejected"
    RESERVATION_CANCELLED = "reservation_cancelled"
    CONTACT_VIEWED = "contact_viewed"
    AUTHORIZATION_FAILED = "authorization_failed"


SECRET_KEY_HINTS = (
    "password",
    "token",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "credential",
)


def sanitize(value: Any):
    if isinstance(value, dict):
        return {
            str(k): "[REDACTED]"
            if any(h in str(k).lower() for h in SECRET_KEY_HINTS)
            else sanitize(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize(v) for v in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def log_action(
    db: Session,
    action_type: ActionType | str,
    *,
    user: User | None = None,
    company_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
):
    entry = AuditLog(
        user_id=user.user_id if user else None,
        company_id=company_id or (user.company_id if user else None),
        action_type=str(action_type),
        entity_type=entity_type,
        entity_id=entity_id,
        details=sanitize(details) if details else None,
    )
    return audit_repo.add(db, entry)


def log_and_commit(db: Session, action_type: ActionType | str, **kwargs: Any):
    log_action(db, action_type, **kwargs)
    db.commit()


def list_company_logs(
    db: Session,
    user: User,
    *,
    action_type: str | None,
    entity_type: str | None,
    entity_id: uuid.UUID | None,
    date_from: datetime | None,
    date_to: datetime | None,
    limit: int,
    offset: int,
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, detail="'from' must be before 'to'")
    return audit_repo.list_for_company(
        db,
        user.company_id,
        action_type=action_type,
        entity_type=entity_type,
        entity_id=entity_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


def get_company_log(db: Session, user: User, audit_id: uuid.UUID):
    entry = audit_repo.get_by_id(db, audit_id)
    if entry is None or entry.company_id != user.company_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Audit log entry not found"
        )
    return entry
