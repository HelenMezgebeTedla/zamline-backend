import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    audit_id: uuid.UUID
    user_id: uuid.UUID | None
    company_id: uuid.UUID | None
    action_type: str
    entity_type: str | None
    entity_id: uuid.UUID | None
    details: dict[str, Any] | None
    created_at: datetime


class AuditLogPage(BaseModel):
    items: list[AuditLogOut]
    total: int
    limit: int
    offset: int
