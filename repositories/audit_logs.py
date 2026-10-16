from sqlalchemy.orm import Session

from models.audit_logs import AuditLog


def create_audit_log(
    db: Session,
    user_id=None,
    company_id=None,
    action_type: str = "",
    entity_type: str | None = None,
    entity_id=None,
    details: dict | None = None,
):
    audit_log = AuditLog(
        user_id=user_id,
        company_id=company_id,
        action_type=action_type,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )
    db.add(audit_log)
    db.commit()
    db.refresh(audit_log)
    return audit_log


def add(db: Session, entry: AuditLog):
    db.add(entry)
    return entry


def get_by_id(db: Session, audit_id):
    return db.query(AuditLog).filter(AuditLog.audit_id == audit_id).first()


def list_for_company(
    db: Session,
    company_id,
    *,
    action_type: str | None = None,
    entity_type: str | None = None,
    entity_id=None,
    date_from=None,
    date_to=None,
    limit: int = 50,
    offset: int = 0,
):
    query = db.query(AuditLog).filter(AuditLog.company_id == company_id)
    if action_type:
        query = query.filter(AuditLog.action_type == action_type)
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if entity_id:
        query = query.filter(AuditLog.entity_id == entity_id)
    if date_from:
        query = query.filter(AuditLog.created_at >= date_from)
    if date_to:
        query = query.filter(AuditLog.created_at <= date_to)

    total = query.count()
    items = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()
    return items, total
