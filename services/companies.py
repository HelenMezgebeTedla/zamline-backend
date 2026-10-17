import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, NoReturn
from uuid import UUID

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.companies import VerificationStatus
from repositories import audit_logs as audit_repo
from repositories import companies as company_repo
from repositories import users as user_repo
from schemas.companies import (
    CompanyCreateSchema,
    CompanyUpdateSchema,
    CompanyVerificationSchema,
)
from security.file_storage import FileStorage
from security.pacra_models import CertificateProcessingUnavailable
from security.pacra_processor import OCRProcessor, PDFOCRProcessor, QRProcessor

logger = logging.getLogger(__name__)

DELETION_GRACE_PERIOD_DAYS = 30

BUSINESS_NAME_MAX = 100
REGISTRATION_NUMBER_MAX = 20
PHONE_MAX = 15
FAILURE_REASON_MAX = 500

REGISTRATION_NUMBER_PATTERN = re.compile(r"^[A-Z0-9]{5,20}$")
PHONE_PATTERN = re.compile(r"^\+?[0-9]{7,15}$")

ALLOWED_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/jpg"}
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024
MIN_FILE_SIZE_BYTES = 100
FILE_SIGNATURES = {
    ".pdf": (b"%PDF-",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
}

REGISTRATION_LABEL_PATTERN = re.compile(
    r"(?:PACRA|REG|REGISTRATION)[\s#:]*(?P<reg>[A-Z0-9]{5,20})", re.IGNORECASE
)
NAME_LABEL_PATTERN = re.compile(
    r"(?:COMPANY|BUSINESS|NAME)[ \t:]*(?P<name>[A-Za-z][^\r\n]{2,80})", re.IGNORECASE
)


class VerificationOutcome(NamedTuple):
    verified: bool
    status: str
    failure_reason: str | None
    extracted_name: str | None
    extracted_registration: str | None


def enum_value(item) -> str:
    return str(getattr(item, "value", item))


def iso_or_none(value) -> str | None:
    return value.isoformat() if value else None


def text_or_none(value) -> str | None:
    return None if value is None else str(value)


def normalise_email(email) -> str:
    return str(email).strip().lower()


def reject(message: str) -> NoReturn:
    raise HTTPException(status_code=422, detail=message)


def clean_text(value: str | None, label: str, max_length: int) -> str:
    cleaned = " ".join((value or "").split())
    if not cleaned:
        reject(f"{label} cannot be empty")
    if len(cleaned) > max_length:
        reject(f"{label} must not exceed {max_length} characters")
    return cleaned


def validate_company_fields(
    business_name: str | None = None,
    registration_number: str | None = None,
    phone_number: str | None = None,
) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    if business_name is not None:
        cleaned["business_name"] = clean_text(
            business_name, "Business name", BUSINESS_NAME_MAX
        )
    if registration_number is not None:
        number = clean_text(
            registration_number, "Registration number", REGISTRATION_NUMBER_MAX
        ).upper()
        if not REGISTRATION_NUMBER_PATTERN.match(number):
            reject("Registration number must be 5 to 20 letters or digits")
        cleaned["registration_number"] = number
    if phone_number is not None:
        phone = clean_text(
            re.sub(r"[\s()-]", "", phone_number or ""), "Phone number", PHONE_MAX
        )
        if not PHONE_PATTERN.match(phone):
            reject("Phone number must be 7 to 15 digits with an optional + prefix")
        cleaned["phone_number"] = phone
    return cleaned


def get_company_profile(company) -> dict:
    return {
        "company_id": str(company.company_id),
        "company_type": enum_value(company.company_type),
        "business_name": company.business_name,
        "registration_number": company.registration_number,
        "company_email": company.company_email,
        "phone_number": company.phone_number,
        "verification_status": enum_value(company.verification_status),
        "verified_at": iso_or_none(company.verified_at),
        "certificate_file_url": company.certificate_file_url,
        "verification_failure_reason": company.verification_failure_reason,
        "fuel_price_per_litre": text_or_none(company.fuel_price_per_litre),
        "driver_daily_allowance": text_or_none(company.driver_daily_allowance),
        "toll_assumption": text_or_none(company.toll_assumption),
        "other_costs": text_or_none(company.other_costs),
        "created_at": iso_or_none(company.created_at),
        "updated_at": iso_or_none(company.updated_at),
    }


def get_company_view(company, current_user) -> dict:
    if current_user.company_id == company.company_id:
        return get_company_profile(company)
    return {
        "company_id": str(company.company_id),
        "company_type": enum_value(company.company_type),
        "business_name": company.business_name,
        "verification_status": enum_value(company.verification_status),
    }


def _get_company_or_404(db: Session, company_id):
    try:
        parsed_id = UUID(str(company_id))
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found") from None
    company = company_repo.get_company_by_id(db, parsed_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    return company


def _require_same_company(current_user, company, detail: str = "Not authorised"):
    if current_user.company_id != company.company_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail)


def create_company_service(db: Session, data: CompanyCreateSchema) -> dict:
    fields = validate_company_fields(
        business_name=data.business_name,
        registration_number=data.registration_number,
        phone_number=data.phone_number,
    )
    email = normalise_email(data.company_email)

    if company_repo.get_company_by_email(db, email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Company email already registered",
        )
    if company_repo.get_company_by_registration_number(
        db, fields["registration_number"]
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Company registration number already registered",
        )

    try:
        company = company_repo.create_company(
            db,
            company_type=enum_value(data.company_type),
            business_name=fields["business_name"],
            registration_number=fields["registration_number"],
            company_email=email,
            phone_number=fields["phone_number"],
        )
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Company already registered",
        ) from None

    audit_repo.create_audit_log(
        db,
        company_id=company.company_id,
        action_type="company_created",
        entity_type="company",
        entity_id=company.company_id,
    )
    return get_company_profile(company)


def get_company_route_service(db: Session, company_id, current_user) -> dict:
    return get_company_view(_get_company_or_404(db, company_id), current_user)


def list_companies_service(
    db: Session, company_type=None, verification_status=None, current_user=None
) -> list[dict]:
    if verification_status is not None:
        try:
            verification_status = VerificationStatus(verification_status)
        except ValueError:
            reject("Invalid verification_status")
    companies = company_repo.list_companies(db, company_type, verification_status)
    return [get_company_view(company, current_user) for company in companies]


def update_company_service(
    db: Session, company_id, data: CompanyUpdateSchema, current_user
) -> dict:
    company = _get_company_or_404(db, company_id)
    _require_same_company(current_user, company)

    changes = validate_company_fields(
        business_name=data.business_name, phone_number=data.phone_number
    )
    if not changes:
        return get_company_profile(company)

    new_name = changes.get("business_name")
    name_changed = new_name is not None and new_name != company.business_name
    reverification_required = (
        name_changed and company.verification_status == VerificationStatus.VERIFIED
    )
    if reverification_required:
        changes["verification_status"] = VerificationStatus.PENDING
        changes["verified_at"] = None
        changes["verification_failure_reason"] = (
            "Business name changed. Upload the PACRA certificate again."
        )

    updated = company_repo.update_company(db, company, **changes)
    audit_repo.create_audit_log(
        db,
        user_id=current_user.user_id,
        company_id=company.company_id,
        action_type="company_updated",
        entity_type="company",
        entity_id=company.company_id,
        details={
            "fields": sorted(changes.keys() & {"business_name", "phone_number"}),
            "reverification_required": reverification_required,
        },
    )
    return get_company_profile(updated)


def validate_certificate_upload(file: UploadFile) -> bytes:
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Allowed: PDF, JPG, PNG",
        )

    extension = Path(file.filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file extension. Allowed: PDF, JPG, PNG",
        )

    content = file.file.read(MAX_FILE_SIZE_BYTES + 1)

    if len(content) > MAX_FILE_SIZE_BYTES:
        limit_mb = MAX_FILE_SIZE_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum size of {limit_mb}MB",
        )
    if len(content) < MIN_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is too small or corrupted",
        )
    if not any(content.startswith(sig) for sig in FILE_SIGNATURES[extension]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File content does not match its type",
        )
    return content


def _normalise_words(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _contains_registration(text: str, registration_number: str) -> bool:
    pattern = rf"(?<![A-Z0-9]){re.escape(registration_number.upper())}(?![A-Z0-9])"
    return re.search(pattern, text.upper()) is not None


def _contains_name(text: str, business_name: str) -> bool:
    expected = _normalise_words(business_name)
    return bool(expected) and f" {expected} " in f" {_normalise_words(text)} "


def _first_match(pattern: re.Pattern, texts: list[str], group: str) -> str | None:
    for text in texts:
        match = pattern.search(text)
        if match:
            return " ".join(match.group(group).split())
    return None


def check_certificate_consistency(
    business_name: str,
    registration_number: str,
    qr_text: str | None,
    ocr_text: str | None,
) -> VerificationOutcome:
    texts = [text for text in (qr_text, ocr_text) if text]
    resubmit = VerificationStatus.RESUBMIT.value

    if not texts:
        return VerificationOutcome(
            False,
            resubmit,
            "The certificate could not be read. Upload a clearer copy.",
            None,
            None,
        )

    extracted_registration = _first_match(REGISTRATION_LABEL_PATTERN, texts, "reg")
    extracted_name = _first_match(NAME_LABEL_PATTERN, texts, "name")
    if extracted_registration:
        extracted_registration = extracted_registration.upper()

    problems = []
    if not any(_contains_registration(text, registration_number) for text in texts):
        problems.append("The registration number was not found on the certificate")
    if not any(_contains_name(text, business_name) for text in texts):
        problems.append("The business name was not found on the certificate")

    if problems:
        return VerificationOutcome(
            False, resubmit, "; ".join(problems), extracted_name, extracted_registration
        )
    return VerificationOutcome(
        True,
        VerificationStatus.VERIFIED.value,
        None,
        extracted_name,
        extracted_registration,
    )


def _read_certificate(
    file_path: str, content_type: str
) -> tuple[str | None, str | None]:
    if content_type == "application/pdf":
        ocr = PDFOCRProcessor().extract_text(file_path)
        return None, ocr.extracted_text if ocr.success else None

    qr = QRProcessor().scan(file_path)
    ocr = OCRProcessor().extract_text(file_path)
    return (
        qr.qr_data if qr.success else None,
        ocr.extracted_text if ocr.success else None,
    )


def verify_pacra_certificate(
    db: Session, company_id, certificate_file: UploadFile, current_user
) -> dict:
    company = _get_company_or_404(db, company_id)
    _require_same_company(current_user, company, "Cannot verify another company")

    content = validate_certificate_upload(certificate_file)
    storage = FileStorage()
    file_path = storage.save_bytes(certificate_file.filename or "certificate", content)
    content_type = storage.get_file_content_type(file_path)

    try:
        qr_text, ocr_text = _read_certificate(file_path, content_type)
    except CertificateProcessingUnavailable as exc:
        storage.delete_file(file_path)
        logger.error("Certificate verification is unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Certificate verification is temporarily unavailable",
        ) from exc

    outcome = check_certificate_consistency(
        company.business_name, company.registration_number, qr_text, ocr_text
    )

    previous_file = company.certificate_file_url
    changes = {
        "verification_status": VerificationStatus(outcome.status),
        "certificate_file_url": file_path,
        "verification_failure_reason": outcome.failure_reason,
    }
    if outcome.verified:
        changes["verified_at"] = datetime.now(timezone.utc)

    updated = company_repo.update_company(db, company, **changes)
    if previous_file and previous_file != file_path:
        storage.delete_file(previous_file)

    audit_repo.create_audit_log(
        db,
        user_id=current_user.user_id,
        company_id=company.company_id,
        action_type="verification_attempted",
        entity_type="company",
        entity_id=company.company_id,
        details={
            "result": outcome.status,
            "failure_reason": outcome.failure_reason,
            "file_type": content_type,
            "qr_read": qr_text is not None,
            "ocr_read": ocr_text is not None,
        },
    )

    return {
        "verified": outcome.verified,
        "status": outcome.status,
        "failure_reason": outcome.failure_reason,
        "certificate_file_url": file_path,
        "extracted_name": outcome.extracted_name,
        "extracted_registration": outcome.extracted_registration,
        "company": get_company_profile(updated),
    }


def get_own_verification_status(db: Session, company_id, current_user) -> dict:
    company = _get_company_or_404(db, company_id)
    _require_same_company(current_user, company)
    return {
        "company_id": str(company.company_id),
        "verification_status": enum_value(company.verification_status),
        "verified_at": iso_or_none(company.verified_at),
        "certificate_file_url": company.certificate_file_url,
        "verification_failure_reason": company.verification_failure_reason,
    }


def verify_company_route_service(
    db: Session, company_id, data: CompanyVerificationSchema, current_user
) -> dict:
    company = _get_company_or_404(db, company_id)
    _require_same_company(current_user, company)

    try:
        requested = VerificationStatus(data.verification_status)
    except ValueError:
        reject("Invalid verification_status")
    if requested == VerificationStatus.VERIFIED:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Verification requires a PACRA certificate upload",
        )

    reason = None
    if data.verification_failure_reason is not None:
        reason = clean_text(
            data.verification_failure_reason, "Failure reason", FAILURE_REASON_MAX
        )

    updated = company_repo.update_company(
        db,
        company,
        verification_status=requested,
        verified_at=None,
        verification_failure_reason=reason,
    )
    audit_repo.create_audit_log(
        db,
        user_id=current_user.user_id,
        company_id=company.company_id,
        action_type="verification_status_changed",
        entity_type="company",
        entity_id=company.company_id,
        details={"new_status": enum_value(requested)},
    )
    return get_company_profile(updated)


def delete_company_service(db: Session, company_id, current_user) -> None:
    company = _get_company_or_404(db, company_id)
    _require_same_company(current_user, company)

    user_repo.deactivate_users_by_company(db, company.company_id)
    audit_repo.create_audit_log(
        db,
        user_id=current_user.user_id,
        company_id=company.company_id,
        action_type="company_deletion_requested",
        entity_type="company",
        entity_id=company.company_id,
        details={"grace_period_days": DELETION_GRACE_PERIOD_DAYS},
    )
