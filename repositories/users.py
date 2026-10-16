from sqlalchemy.orm import Session

from models.users import User


def get_user_by_id(db: Session, user_id) -> User | None:
    return db.query(User).filter(User.user_id == user_id).first()


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()


def create_user(
    db: Session,
    company_id,
    first_name: str,
    last_name: str,
    email: str,
    password_hash: str,
    role: str,
    commit: bool = True,
) -> User:
    user = User(
        company_id=company_id,
        first_name=first_name,
        last_name=last_name,
        email=email,
        password_hash=password_hash,
        role=role,
    )
    db.add(user)
    if commit:
        db.commit()
        db.refresh(user)
    else:
        db.flush()
    return user


def update_user(db: Session, user: User, **changes) -> User:
    for key, value in changes.items():
        setattr(user, key, value)
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user: User) -> None:
    db.delete(user)
    db.commit()


def deactivate_users_by_company(db: Session, company_id) -> int:
    count = (
        db.query(User)
        .filter(User.company_id == company_id)
        .update({"is_active": False}, synchronize_session=False)
    )
    db.commit()
    return count
