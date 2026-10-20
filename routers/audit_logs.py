import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from dependency import get_current_user
from models.users import User
from schemas.audit_logs import AuditLogOut, AuditLogPage
from services import audit_logs as audit_service

router = APIRouter(prefix="/audit-logs", tags=["Audit logs"])


@router.get(
    "",
    response_model=AuditLogPage,
    summary="List my company's audit log (newest first)",
)
def list_audit_logs(
    action_type: str | None = Query(default=None, max_length=50),
    entity_type: str | None = Query(default=None, max_length=50),
    entity_id: uuid.UUID | None = None,
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items, total = audit_service.list_company_logs(
        db,
        user,
        action_type=action_type,
        entity_type=entity_type,
        entity_id=entity_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return AuditLogPage(
        items=[AuditLogOut.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{audit_id}", response_model=AuditLogOut, summary="Get one audit log entry"
)
def get_audit_log(
    audit_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return audit_service.get_company_log(db, user, audit_id)
