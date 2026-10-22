from uuid import UUID

from sqlalchemy.orm import Session

from models.companies import Company


def get_cost_settings_company(db: Session, company_id: UUID):
    return db.query(Company).filter(Company.company_id == company_id).first()


def add_company_with_cost_settings(db: Session, **values):
    company = Company(**values)
    db.add(company)
    db.flush()
    return company
