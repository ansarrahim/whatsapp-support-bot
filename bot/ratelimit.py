"""Per-identifier sliding-window rate limiting. Upstash Redis when
configured, in-memory fallback otherwise -- same pattern as bot/memory.py.
The in-memory fallback is per-instance only (not consistent across Vercel's
concurrent instances, same caveat as memory.py), but it's still a real
throttle against casual abuse, which is strictly better than none.
"""

import logging
import time

from config import settings

logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 60
_mem_hits: dict[str, list[float]] = {}

_client_cache = None
_client_checked = False


def _client():
    global _client_cache, _client_checked
    if _client_checked:
        return _client_cache
    _client_checked = True
    if not settings.UPSTASH_REDIS_REST_URL or not settings.UPSTASH_REDIS_REST_TOKEN:
        return None
    try:
        from upstash_redis import Redis

        _client_cache = Redis(url=settings.UPSTASH_REDIS_REST_URL, token=settings.UPSTASH_REDIS_REST_TOKEN)
    except Exception:
        logger.exception("Failed to initialize Redis for rate limiting.")
        _client_cache = None
    return _client_cache


def is_rate_limited(identifier: str, max_requests: int) -> bool:
    """True if `identifier` has made more than `max_requests` calls in the
    last 60 seconds. Fails open (returns False) on any Redis error -- a rate
    limiter that itself breaks the app is worse than one that occasionally
    under-throttles."""
    client = _client()
    if client is None:
        now = time.time()
        hits = [t for t in _mem_hits.get(identifier, []) if now - t < _WINDOW_SECONDS]
        hits.append(now)
        _mem_hits[identifier] = hits
        return len(hits) > max_requests

    try:
        key = f"ratelimit:{identifier}"
        count = client.incr(key)
        if count == 1:
            client.expire(key, _WINDOW_SECONDS)
        return count > max_requests
    except Exception:
        logger.exception("Rate limit check failed for %s -- allowing the request through.", identifier)
        return False


def client_ip(headers, remote_addr: str | None) -> str:
    """Vercel sets X-Forwarded-For; fall back to the direct connection."""
    forwarded = headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return remote_addr or "unknown"
