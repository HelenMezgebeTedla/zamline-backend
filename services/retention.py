import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from models.companies import Company
from models.users import User
from repositories.audit_logs import delete_before, get_entity_ids_before
from repositories.companies import get_companies_by_ids
from repositories.transactions import open_session, save_changes
from repositories.users import get_users_by_company, get_users_by_ids
from security.file_storage import FileStorage
from security.password import hash_password

logger = logging.getLogger(__name__)

AUDIT_LOG_DAYS = 365
DELETION_GRACE_DAYS = 30
DELETED_DOMAIN = "deleted.invalid"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _anonymise_user(user: User) -> None:
    user.first_name = "Deleted"
    user.last_name = "User"
    user.email = f"deleted-{user.user_id.hex}@{DELETED_DOMAIN}"
    user.password_hash = hash_password(secrets.token_urlsafe(32))
    user.is_active = False


def _anonymise_company(company: Company, storage: FileStorage) -> None:
    if company.certificate_file_url:
        storage.delete_file(company.certificate_file_url)
    company.business_name = "Deleted company"
    company.company_email = f"deleted-{company.company_id.hex}@{DELETED_DOMAIN}"
    company.phone_number = "0000000"
    company.certificate_file_url = None
    company.verification_failure_reason = None


def anonymise_deleted_accounts(db: Session, now: datetime) -> tuple[int, int]:
    cutoff = now - timedelta(days=DELETION_GRACE_DAYS)
    storage = FileStorage()
    users_done = 0
    companies_done = 0

    user_ids = get_entity_ids_before(db, "user_deletion_requested", cutoff)
    for user in get_users_by_ids(db, user_ids):
        if not user.is_active and not user.email.endswith(DELETED_DOMAIN):
            _anonymise_user(user)
            users_done += 1

    company_ids = get_entity_ids_before(db, "company_deletion_requested", cutoff)
    for company in get_companies_by_ids(db, company_ids):
        members = get_users_by_company(db, company.company_id)
        if any(member.is_active for member in members):
            continue
        for member in members:
            if not member.email.endswith(DELETED_DOMAIN):
                _anonymise_user(member)
                users_done += 1
        if not company.company_email.endswith(DELETED_DOMAIN):
            _anonymise_company(company, storage)
            companies_done += 1

    save_changes(db)
    return users_done, companies_done


def delete_old_audit_logs(db: Session, now: datetime) -> int:
    cutoff = now - timedelta(days=AUDIT_LOG_DAYS)
    count = delete_before(db, cutoff)
    save_changes(db)
    return count


def run_retention(db: Session, now: datetime | None = None) -> dict:
    now = now or _now()
    users, companies = anonymise_deleted_accounts(db, now)
    audit_logs = delete_old_audit_logs(db, now)
    result = {
        "users_anonymised": users,
        "companies_anonymised": companies,
        "audit_logs_deleted": audit_logs,
    }
    logger.warning("Retention finished: %s", result)
    return result


def main() -> None:
    with open_session() as db:
        print(run_retention(db))


if __name__ == "__main__":
    main()
