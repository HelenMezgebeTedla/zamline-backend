from sqlalchemy.orm import Session

from models.companies import Company


def get_company_by_id(db: Session, company_id) -> Company | None:
    return db.query(Company).filter(Company.company_id == company_id).first()


def get_company_by_registration_number(
    db: Session, registration_number: str
) -> Company | None:
    return (
        db.query(Company)
        .filter(Company.registration_number == registration_number)
        .first()
    )


def get_company_by_email(db: Session, email: str) -> Company | None:
    return db.query(Company).filter(Company.company_email == email).first()


def create_company(
    db: Session,
    company_type: str,
    business_name: str,
    registration_number: str,
    company_email: str,
    phone_number: str,
    fuel_price_per_litre=None,
    driver_daily_allowance=None,
    toll_assumption=None,
    other_costs=None,
    commit: bool = True,
) -> Company:
    company = Company(
        company_type=company_type,
        business_name=business_name,
        registration_number=registration_number,
        company_email=company_email,
        phone_number=phone_number,
        fuel_price_per_litre=fuel_price_per_litre,
        driver_daily_allowance=driver_daily_allowance,
        toll_assumption=toll_assumption,
        other_costs=other_costs,
    )
    db.add(company)
    if commit:
        db.commit()
        db.refresh(company)
    else:
        db.flush()
    return company


def update_company(db: Session, company: Company, **changes) -> Company:
    for key, value in changes.items():
        setattr(company, key, value)
    db.commit()
    db.refresh(company)
    return company


def list_companies(
    db: Session, company_type=None, verification_status=None, limit: int = 200
) -> list[Company]:
    query = db.query(Company)
    if company_type is not None:
        query = query.filter(Company.company_type == company_type)
    if verification_status is not None:
        query = query.filter(Company.verification_status == verification_status)
    return query.order_by(Company.created_at.desc()).limit(limit).all()
