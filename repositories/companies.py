from sqlalchemy.orm import Session
from uuid import UUID
from models.companies import Company


def get_company_by_id(db: Session, company_id: UUID):
    return db.query(Company).filter(Company.company_id == company_id).first()
