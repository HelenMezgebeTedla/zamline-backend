from sqlalchemy.orm import Session
from uuid import UUID
from models.users import User


def get_user_by_id(db: Session, user_id: UUID):
    return db.query(User).filter(User.user_id == user_id).first()
