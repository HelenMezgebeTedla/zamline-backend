from pydantic import BaseModel, EmailStr

from models.companies import CompanyType
from schemas.companies import CompanyResponseSchema


class CompanyRegistrationSchema(BaseModel):
    business_name: str
    registration_number: str
    company_email: EmailStr
    phone_number: str
    company_type: CompanyType
    first_name: str
    last_name: str
    password: str


class UserUpdateSchema(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: EmailStr | None = None


class UserLoginSchema(BaseModel):
    email: EmailStr
    password: str


class OTPVerifySchema(BaseModel):
    email: EmailStr
    code: str


class ResendOTPSchema(BaseModel):
    email: EmailStr


class MessageSchema(BaseModel):
    message: str


class LoginResponseSchema(BaseModel):
    otp_required: bool = True
    message: str


class TokenSchema(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponseSchema(BaseModel):
    user_id: str
    company_id: str
    first_name: str
    last_name: str
    email: str
    role: str
    is_active: bool
    created_at: str | None = None

    model_config = {"from_attributes": True}


class RegistrationResponseSchema(BaseModel):
    user: UserResponseSchema
    company: CompanyResponseSchema
