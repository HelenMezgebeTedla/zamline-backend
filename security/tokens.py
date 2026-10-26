import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from config import JWT_ALGORITHM, JWT_EXPIRE_MINUTES, JWT_SECRET

ACCESS_TOKEN_TYPE = "access"
ACCESS_TOKEN_MAX_MINUTES = 15
ACCESS_TOKEN_MINUTES = max(1, min(JWT_EXPIRE_MINUTES, ACCESS_TOKEN_MAX_MINUTES))


def _signing_key() -> str:
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET is not configured")
    return JWT_SECRET


def create_access_token(
    user_id: uuid.UUID, role: str, session_id: uuid.UUID | None = None
) -> str:
    issued_at = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": ACCESS_TOKEN_TYPE,
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=ACCESS_TOKEN_MINUTES),
        "jti": uuid.uuid4().hex,
    }
    if session_id is not None:
        payload["sid"] = str(session_id)
    return jwt.encode(payload, _signing_key(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(
        token,
        _signing_key(),
        algorithms=[JWT_ALGORITHM],
        options={"require": ["exp", "sub"]},
    )
    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise jwt.InvalidTokenError("Invalid token type")
    return payload


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hmac.new(
        _signing_key().encode("utf-8"), token.encode("utf-8"), hashlib.sha256
    ).hexdigest()
