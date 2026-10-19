import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from config import JWT_SECRET, OTP_EXPIRE_MINUTES, OTP_MAX_ATTEMPTS, REDIS_URL
from security.email import send_otp_email, send_password_reset_email

logger = logging.getLogger(__name__)

RESEND_COOLDOWN_SECONDS = 60
OTP_LENGTH = 6
KEY_PREFIX = "otp:"
PURPOSE_LOGIN = "login"
PURPOSE_RESET = "reset"


@dataclass
class OTPRecord:
    code_hash: str
    expires_at: datetime
    created_at: datetime
    attempts: int = 0

    def to_json(self) -> str:
        return json.dumps(
            {
                "code_hash": self.code_hash,
                "expires_at": self.expires_at.isoformat(),
                "created_at": self.created_at.isoformat(),
                "attempts": self.attempts,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "OTPRecord":
        data = json.loads(raw)
        return cls(
            code_hash=data["code_hash"],
            expires_at=datetime.fromisoformat(data["expires_at"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            attempts=data["attempts"],
        )


class _MemoryCache:
    def __init__(self) -> None:
        self._items: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            value, expires_at = item
            if time.monotonic() >= expires_at:
                del self._items[key]
                return None
            return value

    def set(self, key: str, value: str, ttl_seconds: float) -> None:
        with self._lock:
            self._items[key] = (value, time.monotonic() + ttl_seconds)

    def delete(self, key: str) -> None:
        with self._lock:
            self._items.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


class _RedisCache:
    def __init__(self, url: str) -> None:
        import redis

        self._client = redis.Redis.from_url(url, decode_responses=True)

    def get(self, key: str) -> str | None:
        return self._client.get(key)

    def set(self, key: str, value: str, ttl_seconds: float) -> None:
        self._client.set(key, value, ex=max(1, int(ttl_seconds)))

    def delete(self, key: str) -> None:
        self._client.delete(key)


_cache = _RedisCache(REDIS_URL) if REDIS_URL else _MemoryCache()


def _key(user_id, purpose: str = PURPOSE_LOGIN) -> str:
    if purpose == PURPOSE_LOGIN:
        return f"{KEY_PREFIX}{user_id}"
    return f"{KEY_PREFIX}{purpose}:{user_id}"


def _save(user_id, record: OTPRecord, purpose: str = PURPOSE_LOGIN) -> None:
    ttl = (record.expires_at - _now()).total_seconds()
    if ttl <= 0:
        _delete(user_id, purpose)
        return
    _cache.set(_key(user_id, purpose), record.to_json(), ttl)


def _load(user_id, purpose: str = PURPOSE_LOGIN) -> OTPRecord | None:
    raw = _cache.get(_key(user_id, purpose))
    return OTPRecord.from_json(raw) if raw else None


def _delete(user_id, purpose: str = PURPOSE_LOGIN) -> None:
    _cache.delete(_key(user_id, purpose))


def clear_otp_cache() -> None:
    if isinstance(_cache, _MemoryCache):
        _cache.clear()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _hash_code(user_id, code: str) -> str:
    return hmac.new(
        JWT_SECRET.encode("utf-8"),
        f"{user_id}:{code}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def validate_code(value: str | None) -> str:
    cleaned = (value or "").strip()
    if len(cleaned) != OTP_LENGTH or not (cleaned.isascii() and cleaned.isdigit()):
        raise HTTPException(
            status_code=422,
            detail=f"OTP must be a {OTP_LENGTH}-digit number",
        )
    return cleaned


def _invalid_code() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid or expired code",
    )


def issue_otp(
    db: Session, user, enforce_cooldown: bool = False, purpose: str = PURPOSE_LOGIN
) -> bool:
    if enforce_cooldown:
        latest = _load(user.user_id, purpose)
        if latest and _now() - _as_utc(latest.created_at) < timedelta(
            seconds=RESEND_COOLDOWN_SECONDS
        ):
            return False

    code = f"{secrets.randbelow(10**OTP_LENGTH):0{OTP_LENGTH}d}"
    _save(
        user.user_id,
        OTPRecord(
            code_hash=_hash_code(user.user_id, code),
            expires_at=_now() + timedelta(minutes=OTP_EXPIRE_MINUTES),
            created_at=_now(),
        ),
        purpose,
    )

    try:
        if purpose == PURPOSE_RESET:
            send_password_reset_email(user.email, code)
        else:
            send_otp_email(user.email, code)
    except Exception as exc:
        logger.error("Could not send OTP email: %s", type(exc).__name__)
        _delete(user.user_id, purpose)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not send the verification code. Try again later.",
        ) from exc
    return True


def check_otp(db: Session, user, code: str, purpose: str = PURPOSE_LOGIN) -> None:
    record = _load(user.user_id, purpose)
    if record is None:
        raise _invalid_code()

    if _now() > _as_utc(record.expires_at):
        _delete(user.user_id, purpose)
        raise _invalid_code()

    if record.attempts >= OTP_MAX_ATTEMPTS:
        _delete(user.user_id, purpose)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Too many attempts. Request a new code.",
        )

    if not hmac.compare_digest(record.code_hash, _hash_code(user.user_id, code)):
        record.attempts += 1
        _save(user.user_id, record, purpose)
        remaining = max(OTP_MAX_ATTEMPTS - record.attempts, 0)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid code. {remaining} attempts remaining.",
        )

    _delete(user.user_id, purpose)
