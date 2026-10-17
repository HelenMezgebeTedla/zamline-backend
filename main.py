import os
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

import models
from database import Base, SessionLocal, engine, get_db
from routers.shipment_matches import router as shipment_matches_router
from routers.trucks import router as trucks_router
from security.password import hash_password, verify_password
from security.tokens import create_access_token

Base.metadata.create_all(bind=engine)

app = FastAPI(title="ZamLine", version="0.2.0")

app.include_router(shipment_matches_router)
app.include_router(trucks_router)

TEST_EMAIL = "fleet.manager@zamline-mock.com"
TEST_PASSWORD = "FleetPass123!"


def create_test_user() -> None:
    db = SessionLocal()
    try:
        if db.query(models.User).filter(models.User.email == TEST_EMAIL).first():
            return
        company = models.Company(
            company_type=models.CompanyType.FLEET,
            business_name="Mwape Haulage Ltd",
            registration_number="PACRA-TEST-01",
            company_email="ops@mwapehaulage-mock.com",
            phone_number="+260970000001",
            verification_status=models.VerificationStatus.VERIFIED,
            verified_at=datetime.now(timezone.utc),
        )
        db.add(company)
        db.flush()
        db.add(
            models.User(
                company_id=company.company_id,
                first_name="Mwape",
                last_name="Banda",
                email=TEST_EMAIL,
                password_hash=hash_password(TEST_PASSWORD),
                role=models.UserRole.FLEET_MANAGER,
                is_active=True,
            )
        )
        db.commit()
    finally:
        db.close()


if os.getenv("ENABLE_TEST_USER", "").lower() == "true":
    create_test_user()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@app.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    email = str(payload.email).lower()
    user = db.query(models.User).filter(models.User.email == email).first()

    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Email verification is required")

    try:
        token = create_access_token(user.user_id, user.role.value)
    except RuntimeError:
        raise HTTPException(
            status_code=503, detail="JWT_SECRET is not set. Add it to your .env file."
        )
    return {"access_token": token, "token_type": "bearer"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
