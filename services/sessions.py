import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from repositories.audit_logs import create_audit_log
from repositories.sessions import (
    create_session,
    get_by_previous_hash,
    get_by_refresh_hash,
    get_session,
    revoke_user_sessions,
    update_session,
)
from repositories.users import get_user_by_id
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _role(user) -> str:
    return getattr(user.role, "value", user.role)


def _session_expired() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Session expired. Please log in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _is_live(session, now: datetime) -> bool:
    if session.revoked_at is not None:
        return False
    if now >= _as_utc(session.expires_at):
        return False
    idle_limit = _as_utc(session.last_used_at) + timedelta(hours=SESSION_IDLE_HOURS)
    return now < idle_limit


def _tokens(user, session, refresh_token: str) -> dict:
    return {
        "access_token": create_access_token(
            user.user_id, _role(user), session.session_id
        ),
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_MINUTES * 60,
    }


def start_session(db: Session, user) -> dict:
    now = _now()
    refresh_token = new_refresh_token()
    session = create_session(
        db,
        user_id=user.user_id,
        refresh_token_hash=hash_refresh_token(refresh_token),
        last_used_at=now,
        expires_at=now + timedelta(days=SESSION_MAX_DAYS),
    )
    create_audit_log(
        db,
        user_id=user.user_id,
        company_id=user.company_id,
        action_type="session_started",
        entity_type="session",
        entity_id=session.session_id,
    )
    return _tokens(user, session, refresh_token)


def refresh_session(db: Session, refresh_token: str | None) -> dict:
    token = (refresh_token or "").strip()
    if not token or len(token) > REFRESH_TOKEN_MAX_LENGTH:
        raise _session_expired()

    token_hash = hash_refresh_token(token)
    session = get_by_refresh_hash(db, token_hash)
    now = _now()

    if session is None:
        reused = get_by_previous_hash(db, token_hash)
        if reused is not None and reused.revoked_at is None:
            update_session(db, reused, revoked_at=now)
            user = get_user_by_id(db, reused.user_id)
            logger.warning("Refresh token reuse detected; session revoked")
            create_audit_log(
                db,
                user_id=reused.user_id,
                company_id=user.company_id if user else None,
                action_type="refresh_token_reused",
                entity_type="session",
                entity_id=reused.session_id,
            )
        raise _session_expired()

    user = get_user_by_id(db, session.user_id)
    if user is None or not user.is_active or not _is_live(session, now):
        if session.revoked_at is None:
            update_session(db, session, revoked_at=now)
        raise _session_expired()

    new_token = new_refresh_token()
    session = update_session(
        db,
        session,
        previous_token_hash=token_hash,
        refresh_token_hash=hash_refresh_token(new_token),
        last_used_at=now,
    )
    return _tokens(user, session, new_token)


def ensure_session_active(db: Session, session_id: str) -> None:
    try:
        session = get_session(db, uuid.UUID(session_id))
    except (TypeError, ValueError):
        session = None
    if session is None or not _is_live(session, _now()):
        raise _session_expired()


def end_session(db: Session, user, session_id: str | None) -> None:
    if session_id:
        try:
            session = get_session(db, uuid.UUID(session_id))
        except (TypeError, ValueError):
            session = None
        if session is not None and session.user_id == user.user_id:
            if session.revoked_at is None:
                update_session(db, session, revoked_at=_now())
    create_audit_log(
        db,
        user_id=user.user_id,
        company_id=user.company_id,
        action_type="logout",
        entity_type="user",
        entity_id=user.user_id,
    )


def end_all_sessions(db: Session, user, reason: str) -> int:
    count = revoke_user_sessions(db, user.user_id, _now())
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
