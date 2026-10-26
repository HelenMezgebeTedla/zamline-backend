import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from repositories.audit_logs import create_audit_log
from repositories.users import get_user_by_id
from security.cache import MemoryCache, make_cache
from security.tokens import (
    ACCESS_TOKEN_MINUTES,
    create_access_token,
    hash_refresh_token,
    new_refresh_token,
)

logger = logging.getLogger(__name__)

SESSION_MAX_DAYS = int(os.getenv("SESSION_MAX_DAYS", "7"))
SESSION_IDLE_HOURS = int(os.getenv("SESSION_IDLE_HOURS", "24"))
REFRESH_TOKEN_MAX_LENGTH = 200

_cache = make_cache()


def clear_sessions() -> None:
    if isinstance(_cache, MemoryCache):
        _cache.clear()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session_key(session_id: str) -> str:
    return f"session:{session_id}"


def _refresh_key(token_hash: str) -> str:
    return f"session-refresh:{token_hash}"


def _previous_key(token_hash: str) -> str:
    return f"session-previous:{token_hash}"


def _user_key(user_id) -> str:
    return f"session-user:{user_id}"


def _role(user) -> str:
    return getattr(user.role, "value", user.role)


def _session_expired() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Session expired. Please log in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _seconds_left(record: dict, now: datetime) -> float:
    idle_end = datetime.fromisoformat(record["last_used_at"]) + timedelta(
        hours=SESSION_IDLE_HOURS
    )
    ends_at = min(datetime.fromisoformat(record["expires_at"]), idle_end)
    return (ends_at - now).total_seconds()


def _load(session_id: str | None) -> dict | None:
    if not session_id:
        return None
    raw = _cache.get(_session_key(session_id))
    return json.loads(raw) if raw else None


def _save(session_id: str, record: dict, now: datetime) -> None:
    ttl = _seconds_left(record, now)
    _cache.set(_session_key(session_id), json.dumps(record), ttl)
    _cache.set(_refresh_key(record["refresh_hash"]), session_id, ttl)
    if record.get("previous_hash"):
        _cache.set(_previous_key(record["previous_hash"]), session_id, ttl)
    _cache.add_member(
        _user_key(record["user_id"]), session_id, SESSION_MAX_DAYS * 24 * 60 * 60
    )


def _revoke(session_id: str | None) -> bool:
    record = _load(session_id)
    if record is None:
        return False
    keys = [_session_key(session_id), _refresh_key(record["refresh_hash"])]
    if record.get("previous_hash"):
        keys.append(_previous_key(record["previous_hash"]))
    _cache.delete(*keys)
    _cache.remove_member(_user_key(record["user_id"]), session_id)
    return True


def _tokens(user, session_id: str, refresh_token: str) -> dict:
    return {
        "access_token": create_access_token(
            user.user_id, _role(user), uuid.UUID(session_id)
        ),
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_MINUTES * 60,
    }


def start_session(db: Session, user) -> dict:
    now = _now()
    session_id = str(uuid.uuid4())
    refresh_token = new_refresh_token()
    record = {
        "user_id": str(user.user_id),
        "refresh_hash": hash_refresh_token(refresh_token),
        "previous_hash": None,
        "created_at": now.isoformat(),
        "last_used_at": now.isoformat(),
        "expires_at": (now + timedelta(days=SESSION_MAX_DAYS)).isoformat(),
    }
    _save(session_id, record, now)
    create_audit_log(
        db,
        user_id=user.user_id,
        company_id=user.company_id,
        action_type="session_started",
        entity_type="session",
        entity_id=uuid.UUID(session_id),
    )
    return _tokens(user, session_id, refresh_token)


def _report_reuse(db: Session, token_hash: str) -> None:
    reused_id = _cache.pop(_previous_key(token_hash))
    record = _load(reused_id)
    if record is None or not _revoke(reused_id):
        return
    user_id = uuid.UUID(record["user_id"])
    user = get_user_by_id(db, user_id)
    logger.warning("Refresh token reuse detected; session revoked")
    create_audit_log(
        db,
        user_id=user_id,
        company_id=user.company_id if user else None,
        action_type="refresh_token_reused",
        entity_type="session",
        entity_id=uuid.UUID(reused_id),
    )


def refresh_session(db: Session, refresh_token: str | None) -> dict:
    token = (refresh_token or "").strip()
    if not token or len(token) > REFRESH_TOKEN_MAX_LENGTH:
        raise _session_expired()

    token_hash = hash_refresh_token(token)
    session_id = _cache.pop(_refresh_key(token_hash))
    if session_id is None:
        _report_reuse(db, token_hash)
        raise _session_expired()

    now = _now()
    record = _load(session_id)
    if record is None:
        raise _session_expired()
    user = get_user_by_id(db, uuid.UUID(record["user_id"]))
    if user is None or not user.is_active or _seconds_left(record, now) <= 0:
        _revoke(session_id)
        raise _session_expired()

    if record.get("previous_hash"):
        _cache.delete(_previous_key(record["previous_hash"]))
    new_token = new_refresh_token()
    record["previous_hash"] = token_hash
    record["refresh_hash"] = hash_refresh_token(new_token)
    record["last_used_at"] = now.isoformat()
    _save(session_id, record, now)
    return _tokens(user, session_id, new_token)


def ensure_session_active(db: Session, session_id: str) -> None:
    record = _load(str(session_id))
    if record is None or _seconds_left(record, _now()) <= 0:
        raise _session_expired()


def end_session(db: Session, user, session_id: str | None) -> None:
    record = _load(session_id)
    if record is not None and record["user_id"] == str(user.user_id):
        _revoke(session_id)
    create_audit_log(
        db,
        user_id=user.user_id,
        company_id=user.company_id,
        action_type="logout",
        entity_type="user",
        entity_id=user.user_id,
    )


def end_all_sessions(db: Session, user, reason: str) -> int:
    user_key = _user_key(user.user_id)
    count = sum(1 for session_id in _cache.members(user_key) if _revoke(session_id))
    _cache.delete(user_key)
    create_audit_log(
        db,
        user_id=user.user_id,
        company_id=user.company_id,
        action_type="sessions_revoked",
        entity_type="user",
        entity_id=user.user_id,
        details={"reason": reason, "count": count},
    )
    return count
