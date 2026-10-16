from pydantic import BaseModel, EmailStr

from models.companies import CompanyType


class CompanyCreateSchema(BaseModel):
    business_name: str
    registration_number: str
    company_email: EmailStr
    phone_number: str
    company_type: CompanyType


class CompanyUpdateSchema(BaseModel):
    business_name: str | None = None
    phone_number: str | None = None


class CompanyVerificationSchema(BaseModel):
    verification_status: str
    verification_failure_reason: str | None = None


class CompanyResponseSchema(BaseModel):
    company_id: str
    company_type: str
    business_name: str
    registration_number: str
    company_email: str
    phone_number: str
    verification_status: str
    verified_at: str | None = None
    certificate_file_url: str | None = None
    verification_failure_reason: str | None = None
    fuel_price_per_litre: str | None = None
    driver_daily_allowance: str | None = None
    toll_assumption: str | None = None
    other_costs: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    model_config = {"from_attributes": True}


class VerificationStatusResponseSchema(BaseModel):
    company_id: str
    verification_status: str
    verified_at: str | None = None
    certificate_file_url: str | None = None
    verification_failure_reason: str | None = None


class CertificateVerificationResponseSchema(BaseModel):
    verified: bool
    status: str
    failure_reason: str | None = None
    certificate_file_url: str | None = None
    extracted_name: str | None = None
    extracted_registration: str | None = None
    company: CompanyResponseSchema
