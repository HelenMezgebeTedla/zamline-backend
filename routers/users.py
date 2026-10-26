import jwt
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from database import get_db
from dependency import get_current_user, oauth2_scheme
from security.rate_limit import hit, limit
from security.tokens import decode_access_token
from schemas.users import (
    CompanyRegistrationSchema,
    ForgotPasswordSchema,
    LoginResponseSchema,
    MessageSchema,
    OTPVerifySchema,
    RefreshTokenSchema,
    RegistrationResponseSchema,
    ResendOTPSchema,
    ResetPasswordSchema,
    TokenSchema,
    UserLoginSchema,
    UserResponseSchema,
    UserUpdateSchema,
)
from services.companies import normalise_email
from services.sessions import end_session, refresh_session
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

MINUTE = 60
HOUR = 60 * MINUTE


def _limit_email(name: str, email: str, count: int, window: int) -> None:
    hit(name, normalise_email(email), count, window)


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=RegistrationResponseSchema,
    dependencies=[Depends(limit("register", 5, HOUR))],
)
def register(data: CompanyRegistrationSchema, db: Session = Depends(get_db)):
    return register_user(db, data)


@router.post(
    "/login",
    response_model=LoginResponseSchema,
    dependencies=[Depends(limit("login", 10, MINUTE))],
)
def login(data: UserLoginSchema, db: Session = Depends(get_db)):
    return login_user(db, data)


@router.post(
    "/verify-otp",
    response_model=TokenSchema,
    dependencies=[Depends(limit("verify-otp", 10, MINUTE))],
)
def verify_otp_route(data: OTPVerifySchema, db: Session = Depends(get_db)):
    return verify_otp(db, data)


@router.post(
    "/resend-otp",
    response_model=MessageSchema,
    dependencies=[Depends(limit("resend-otp", 5, 10 * MINUTE))],
)
def resend_otp_route(data: ResendOTPSchema, db: Session = Depends(get_db)):
    _limit_email("resend-otp-email", data.email, 3, 10 * MINUTE)
    return resend_otp(db, data)


@router.post(
    "/forgot-password",
    response_model=MessageSchema,
    dependencies=[Depends(limit("forgot-password", 5, 15 * MINUTE))],
)
def forgot_password_route(data: ForgotPasswordSchema, db: Session = Depends(get_db)):
    _limit_email("forgot-password-email", data.email, 3, 15 * MINUTE)
    return request_password_reset(db, data)


@router.post(
    "/reset-password",
    response_model=MessageSchema,
    dependencies=[Depends(limit("reset-password", 10, 15 * MINUTE))],
)
def reset_password_route(data: ResetPasswordSchema, db: Session = Depends(get_db)):
    _limit_email("reset-password-email", data.email, 5, 15 * MINUTE)
    return reset_password(db, data)


@router.post(
    "/refresh",
    response_model=TokenSchema,
    dependencies=[Depends(limit("refresh", 30, MINUTE))],
)
def refresh_route(data: RefreshTokenSchema, db: Session = Depends(get_db)):
    return refresh_session(db, data.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_route(
    token: str = Depends(oauth2_scheme),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        session_id = decode_access_token(token).get("sid")
    except jwt.PyJWTError:
        session_id = None
    end_session(db, current_user, session_id)


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
