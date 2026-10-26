from contextlib import contextmanager

from sqlalchemy.orm import Session


def save_changes(db: Session) -> None:
    db.commit()


def undo_changes(db: Session) -> None:
    db.rollback()


def reload(db: Session, *items) -> None:
    for item in items:
        db.refresh(item)


@contextmanager
def open_session():
    from database import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
