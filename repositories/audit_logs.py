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
) -> AuditLog:
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
