from enum import Enum

from pydantic import BaseModel, EmailStr, model_validator

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
    confirm_password: str | None = None

    @model_validator(mode="after")
    def passwords_match(self):
        if self.confirm_password is not None and self.password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


class UserUpdateSchema(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: EmailStr | None = None


class Portal(str, Enum):
    SHIPPER = "shipper"
    FLEET = "fleet"


class UserLoginSchema(BaseModel):
    email: EmailStr
    password: str
    portal: Portal


class OTPVerifySchema(BaseModel):
    email: EmailStr
    code: str
    portal: Portal


class ResendOTPSchema(BaseModel):
    email: EmailStr


class ForgotPasswordSchema(BaseModel):
    email: EmailStr


class ResetPasswordSchema(BaseModel):
    email: EmailStr
    code: str
    new_password: str
    confirm_password: str

    @model_validator(mode="after")
    def passwords_match(self):
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


class RefreshTokenSchema(BaseModel):
    refresh_token: str


class MessageSchema(BaseModel):
    message: str


class LoginResponseSchema(BaseModel):
    otp_required: bool = True
    message: str


class TokenSchema(BaseModel):
    access_token: str
    token_type: str = "bearer"
    refresh_token: str | None = None
    expires_in: int | None = None


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
