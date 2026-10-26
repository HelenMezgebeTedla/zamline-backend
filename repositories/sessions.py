from datetime import datetime

from sqlalchemy.orm import Session

from models.sessions import UserSession


def create_session(db: Session, **fields) -> UserSession:
    session = UserSession(**fields)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db: Session, session_id) -> UserSession | None:
    return db.query(UserSession).filter(UserSession.session_id == session_id).first()


def get_by_refresh_hash(db: Session, token_hash: str) -> UserSession | None:
    return (
        db.query(UserSession)
        .filter(UserSession.refresh_token_hash == token_hash)
        .first()
    )


def get_by_previous_hash(db: Session, token_hash: str) -> UserSession | None:
    return (
        db.query(UserSession)
        .filter(UserSession.previous_token_hash == token_hash)
        .first()
    )


def update_session(db: Session, session: UserSession, **changes) -> UserSession:
    for key, value in changes.items():
        setattr(session, key, value)
    db.commit()
    db.refresh(session)
    return session


def revoke_user_sessions(db: Session, user_id, when: datetime) -> int:
    count = (
        db.query(UserSession)
        .filter(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .update({"revoked_at": when}, synchronize_session=False)
    )
    db.commit()
    return count


def delete_sessions_before(db: Session, cutoff: datetime) -> int:
    count = (
        db.query(UserSession)
        .filter(UserSession.expires_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()
    return count
