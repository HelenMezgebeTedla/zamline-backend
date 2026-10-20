from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from database import get_db
from dependency import get_current_user
from schemas.users import (
    CompanyRegistrationSchema,
    ForgotPasswordSchema,
    LoginResponseSchema,
    MessageSchema,
    OTPVerifySchema,
    RegistrationResponseSchema,
    ResendOTPSchema,
    ResetPasswordSchema,
    TokenSchema,
    UserLoginSchema,
    UserResponseSchema,
    UserUpdateSchema,
)
from services.users import (
    delete_current_user,
    get_current_user_profile,
    login_user,
    register_user,
    request_password_reset,
    resend_otp,
    reset_password,
    update_current_user,
    verify_otp,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=RegistrationResponseSchema,
)
def register(data: CompanyRegistrationSchema, db: Session = Depends(get_db)):
    return register_user(db, data)


@router.post("/login", response_model=LoginResponseSchema)
def login(data: UserLoginSchema, db: Session = Depends(get_db)):
    return login_user(db, data)


@router.post("/verify-otp", response_model=TokenSchema)
def verify_otp_route(data: OTPVerifySchema, db: Session = Depends(get_db)):
    return verify_otp(db, data)


@router.post("/resend-otp", response_model=MessageSchema)
def resend_otp_route(data: ResendOTPSchema, db: Session = Depends(get_db)):
    return resend_otp(db, data)


@router.post("/forgot-password", response_model=MessageSchema)
def forgot_password_route(data: ForgotPasswordSchema, db: Session = Depends(get_db)):
    return request_password_reset(db, data)


@router.post("/reset-password", response_model=MessageSchema)
def reset_password_route(data: ResetPasswordSchema, db: Session = Depends(get_db)):
    return reset_password(db, data)


@router.get("/me", response_model=UserResponseSchema)
def get_me(current_user=Depends(get_current_user)):
    return get_current_user_profile(current_user)


@router.put("/me", response_model=UserResponseSchema)
def update_me(
    data: UserUpdateSchema,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return update_current_user(db, current_user, data)


@router.patch("/me", response_model=UserResponseSchema)
def patch_me(
    data: UserUpdateSchema,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return update_current_user(db, current_user, data)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    delete_current_user(db, current_user)
