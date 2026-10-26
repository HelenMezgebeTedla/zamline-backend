import logging
import math
import os
import threading
import time

from fastapi import HTTPException, Request, status

from config import REDIS_URL

logger = logging.getLogger(__name__)

ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").strip().lower() != "false"
GLOBAL_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))

TOO_MANY_REQUESTS = "Too many requests. Please try again later."


class _MemoryStore:
    def __init__(self) -> None:
        self._counts: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def increment(self, key: str, window: int) -> tuple[int, int]:
        now = time.monotonic()
        with self._lock:
            count, expires_at = self._counts.get(key, (0, now + window))
            if now >= expires_at:
                count, expires_at = 0, now + window
            count += 1
            self._counts[key] = (count, expires_at)
            if len(self._counts) > 50000:
                self._counts = {k: v for k, v in self._counts.items() if v[1] > now}
            return count, max(1, math.ceil(expires_at - now))

    def get(self, key: str) -> tuple[int, int]:
        now = time.monotonic()
        with self._lock:
            count, expires_at = self._counts.get(key, (0, now))
            if now >= expires_at:
                return 0, 0
            return count, max(1, math.ceil(expires_at - now))

    def delete(self, key: str) -> None:
        with self._lock:
            self._counts.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._counts.clear()


class _RedisStore:
    def __init__(self, url: str) -> None:
        import redis

        self._client = redis.Redis.from_url(url, decode_responses=True)

    def increment(self, key: str, window: int) -> tuple[int, int]:
        pipe = self._client.pipeline()
        pipe.set(key, 0, ex=window, nx=True)
        pipe.incr(key)
        pipe.ttl(key)
        _, count, ttl = pipe.execute()
        return int(count), max(1, int(ttl))

    def get(self, key: str) -> tuple[int, int]:
        pipe = self._client.pipeline()
        pipe.get(key)
        pipe.ttl(key)
        count, ttl = pipe.execute()
        return int(count or 0), max(0, int(ttl))

    def delete(self, key: str) -> None:
        self._client.delete(key)


_store = _RedisStore(REDIS_URL) if REDIS_URL else _MemoryStore()


def clear_rate_limits() -> None:
    if isinstance(_store, _MemoryStore):
        _store.clear()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    if hops:
        return hops[-1]
    return request.client.host if request.client else "unknown"


def _key(name: str, identity: str) -> str:
    return f"rl:{name}:{identity.strip().lower()}"


def too_many(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=TOO_MANY_REQUESTS,
        headers={"Retry-After": str(retry_after)},
    )


def hit(name: str, identity: str, limit: int, window: int) -> None:
    if not ENABLED:
        return
    try:
        count, retry_after = _store.increment(_key(name, identity), window)
    except Exception as exc:
        logger.warning("Rate limit store unavailable: %s", type(exc).__name__)
        return
    if count > limit:
        logger.warning("Rate limit reached: %s", name)
        raise too_many(retry_after)


def ensure_not_blocked(name: str, identity: str, limit: int) -> None:
    if not ENABLED:
        return
    try:
        count, retry_after = _store.get(_key(name, identity))
    except Exception as exc:
        logger.warning("Rate limit store unavailable: %s", type(exc).__name__)
        return
    if count >= limit:
        logger.warning("Rate limit block active: %s", name)
        raise too_many(retry_after)


def record_failure(name: str, identity: str, window: int) -> None:
    if not ENABLED:
        return
    try:
        _store.increment(_key(name, identity), window)
    except Exception as exc:
        logger.warning("Rate limit store unavailable: %s", type(exc).__name__)


def reset(name: str, identity: str) -> None:
    try:
        _store.delete(_key(name, identity))
    except Exception as exc:
        logger.warning("Rate limit store unavailable: %s", type(exc).__name__)


def limit(name: str, limit_count: int, window: int):
    def dependency(request: Request) -> None:
        hit(name, client_ip(request), limit_count, window)

    return dependency
