from __future__ import annotations

import threading
import time

from config import REDIS_URL


class MemoryCache:
    def __init__(self) -> None:
        self._items: dict[str, tuple[object, float]] = {}
        self._lock = threading.Lock()

    def _live(self, key: str):
        item = self._items.get(key)
        if item is None:
            return None
        value, expires_at = item
        if time.monotonic() >= expires_at:
            del self._items[key]
            return None
        return item

    def get(self, key: str) -> str | None:
        with self._lock:
            item = self._live(key)
            return item[0] if item else None

    def set(self, key: str, value: str, ttl_seconds: float) -> None:
        with self._lock:
            self._items[key] = (value, time.monotonic() + max(1, ttl_seconds))

    def pop(self, key: str) -> str | None:
        with self._lock:
            item = self._live(key)
            if item is None:
                return None
            del self._items[key]
            return item[0]

    def delete(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._items.pop(key, None)

    def add_member(self, key: str, member: str, ttl_seconds: float) -> None:
        with self._lock:
            item = self._live(key)
            members = set(item[0]) if item else set()
            members.add(member)
            expires_at = max(
                item[1] if item else 0, time.monotonic() + max(1, ttl_seconds)
            )
            self._items[key] = (members, expires_at)

    def members(self, key: str) -> set[str]:
        with self._lock:
            item = self._live(key)
            return set(item[0]) if item else set()

    def remove_member(self, key: str, member: str) -> None:
        with self._lock:
            item = self._live(key)
            if item:
                item[0].discard(member)

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


class RedisCache:
    def __init__(self, url: str) -> None:
        import redis

        self._client = redis.Redis.from_url(url, decode_responses=True)

    def get(self, key: str) -> str | None:
        return self._client.get(key)

    def set(self, key: str, value: str, ttl_seconds: float) -> None:
        self._client.set(key, value, ex=max(1, int(ttl_seconds)))

    def pop(self, key: str) -> str | None:
        return self._client.getdel(key)

    def delete(self, *keys: str) -> None:
        if keys:
            self._client.delete(*keys)

    def add_member(self, key: str, member: str, ttl_seconds: float) -> None:
        pipe = self._client.pipeline()
        pipe.sadd(key, member)
        pipe.expire(key, max(1, int(ttl_seconds)))
        pipe.execute()

    def members(self, key: str) -> set[str]:
        return set(self._client.smembers(key))

    def remove_member(self, key: str, member: str) -> None:
        self._client.srem(key, member)

    def keys(self) -> list[str]:
        return list(self._client.scan_iter())

    def clear(self) -> None:
        return None


def make_cache():
    return RedisCache(REDIS_URL) if REDIS_URL else MemoryCache()
