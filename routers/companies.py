from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.orm import Session

from database import get_db
from dependency import get_current_user
from models.companies import CompanyType
from schemas.companies import (
    CertificateVerificationResponseSchema,
    CompanyCreateSchema,
    CompanyResponseSchema,
    CompanyUpdateSchema,
    CompanyVerificationSchema,
    VerificationStatusResponseSchema,
)
from services.companies import (
    create_company_service,
    delete_company_service,
    get_company_route_service,
    get_own_verification_status,
    list_companies_service,
    update_company_service,
    verify_company_route_service,
    verify_pacra_certificate,
)

router = APIRouter(prefix="/companies", tags=["companies"])


@router.post(
    "/create", response_model=CompanyResponseSchema, status_code=status.HTTP_201_CREATED
)
def create_company_route(data: CompanyCreateSchema, db: Session = Depends(get_db)):
    return create_company_service(db, data)


@router.get("/list", response_model=None)
def list_companies_route(
    company_type: CompanyType | None = None,
    verification_status: str | None = None,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_companies_service(db, company_type, verification_status, current_user)


@router.get("/{company_id}", response_model=None)
def get_company_route(
    company_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_company_route_service(db, company_id, current_user)


@router.put("/{company_id}", response_model=CompanyResponseSchema)
def update_company_route(
    company_id: str,
    data: CompanyUpdateSchema,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return update_company_service(db, company_id, data, current_user)


@router.patch("/{company_id}", response_model=CompanyResponseSchema)
def patch_company_route(
    company_id: str,
    data: CompanyUpdateSchema,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return update_company_service(db, company_id, data, current_user)


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_company_route(
    company_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    delete_company_service(db, company_id, current_user)


@router.post("/{company_id}/verify", response_model=CompanyResponseSchema)
def verify_company_route(
    company_id: str,
    data: CompanyVerificationSchema,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return verify_company_route_service(db, company_id, data, current_user)


@router.post(
    "/{company_id}/verify-certificate",
    response_model=CertificateVerificationResponseSchema,
)
def verify_certificate_route(
    company_id: str,
    certificate_file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return verify_pacra_certificate(db, company_id, certificate_file, current_user)


@router.post(
    "/{company_id}/verify-retry",
    response_model=CertificateVerificationResponseSchema,
)
def verify_retry_route(
    company_id: str,
    certificate_file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return verify_pacra_certificate(db, company_id, certificate_file, current_user)


@router.get(
    "/{company_id}/verification-status",
    response_model=VerificationStatusResponseSchema,
)
def verification_status_route(
    company_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_own_verification_status(db, company_id, current_user)
