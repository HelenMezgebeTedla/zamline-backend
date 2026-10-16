import uuid
from datetime import datetime, timedelta, timezone

import jwt

from config import JWT_ALGORITHM, JWT_EXPIRE_MINUTES, JWT_SECRET

ACCESS_TOKEN_TYPE = "access"


def _signing_key() -> str:
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET is not configured")
    return JWT_SECRET


def create_access_token(user_id: uuid.UUID, role: str) -> str:
    issued_at = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": ACCESS_TOKEN_TYPE,
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
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
