"""Per-user conversation memory. Upstash Redis when credentials are configured,
transparently falling back to an in-memory dict otherwise -- this fallback is
required (not a nice-to-have): it's what makes the whole bot, including the
admin dashboard, fully testable with zero credentials.

Redis key scheme:
    wa:hist:{phone}        LIST    JSON {"role","content","ts"}, newest first
    wa:meta:{phone}        HASH    last_message, last_intent, last_ts
    wa:conversations       SET     phone numbers with at least one saved message
    wa:stats:ai_handled    STRING  INCR
    wa:stats:human_routed  STRING  INCR
    wa:stats:first_seen    STRING  SETNX'd ISO timestamp on the very first webhook ever
"""

import json
import logging
from datetime import datetime, timezone

from config import settings

logger = logging.getLogger(__name__)

_HIST_PREFIX = "wa:hist:"
_META_PREFIX = "wa:meta:"
_CONVERSATIONS_KEY = "wa:conversations"
_FIRST_SEEN_KEY = "wa:stats:first_seen"

_client_cache = None
_client_checked = False

# --- in-memory fallback state (used when Upstash env vars are unset) ---
_mem_hist: dict[str, list[dict]] = {}
_mem_meta: dict[str, dict] = {}
_mem_conversations: set[str] = set()
_mem_counters: dict[str, int] = {}
_mem_first_seen: str | None = None


def _client():
    """Return an Upstash Redis client, or None if not configured (fallback path)."""
    global _client_cache, _client_checked
    if _client_checked:
        return _client_cache
    _client_checked = True
    if not settings.UPSTASH_REDIS_REST_URL or not settings.UPSTASH_REDIS_REST_TOKEN:
        logger.info("Upstash Redis not configured -- using in-memory fallback store.")
        return None
    try:
        from upstash_redis import Redis

        _client_cache = Redis(url=settings.UPSTASH_REDIS_REST_URL, token=settings.UPSTASH_REDIS_REST_TOKEN)
    except Exception:
        logger.exception("Failed to initialize Upstash Redis client -- using in-memory fallback.")
        _client_cache = None
    return _client_cache


def normalize_phone(raw: str) -> str:
    """'whatsapp:+15551234567' -> '15551234567' -- consistent key regardless of prefix."""
    return "".join(ch for ch in raw if ch.isdigit())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_history(phone: str) -> list[dict]:
    """Return up to MAX_HISTORY_MESSAGES turns, oldest first."""
    phone = normalize_phone(phone)
    client = _client()
    if client is None:
        return list(_mem_hist.get(phone, []))
    try:
        raw = client.lrange(_HIST_PREFIX + phone, 0, settings.MAX_HISTORY_MESSAGES - 1)
        entries = [json.loads(item) for item in raw]
        entries.reverse()  # stored newest-first via LPUSH; callers want oldest-first
        return entries
    except Exception:
        logger.exception("get_history failed for %s -- returning empty history.", settings.mask_phone(phone))
        return []


def save_message(phone: str, role: str, content: str) -> None:
    phone = normalize_phone(phone)
    entry = {"role": role, "content": content, "ts": _now_iso()}
    client = _client()
    if client is None:
        is_new = phone not in _mem_conversations
        _mem_hist.setdefault(phone, []).append(entry)
        _mem_hist[phone] = _mem_hist[phone][-settings.MAX_HISTORY_MESSAGES :]
        _mem_conversations.add(phone)
    else:
        try:
            is_new = client.sadd(_CONVERSATIONS_KEY, phone) == 1
            key = _HIST_PREFIX + phone
            client.lpush(key, json.dumps(entry))
            client.ltrim(key, 0, settings.MAX_HISTORY_MESSAGES - 1)
        except Exception:
            logger.exception("save_message failed for %s.", settings.mask_phone(phone))
            return
    if is_new:
        mark_first_seen()


def update_meta(phone: str, **fields: str) -> None:
    phone = normalize_phone(phone)
    fields = {**fields, "last_ts": _now_iso()}
    client = _client()
    if client is None:
        _mem_meta.setdefault(phone, {}).update(fields)
        return
    try:
        client.hset(_META_PREFIX + phone, values=fields)
    except Exception:
        logger.exception("update_meta failed for %s.", settings.mask_phone(phone))


def clear_history(phone: str) -> None:
    phone = normalize_phone(phone)
    client = _client()
    if client is None:
        _mem_hist.pop(phone, None)
        _mem_meta.pop(phone, None)
        _mem_conversations.discard(phone)
        return
    try:
        client.delete(_HIST_PREFIX + phone)
        client.delete(_META_PREFIX + phone)
        client.srem(_CONVERSATIONS_KEY, phone)
    except Exception:
        logger.exception("clear_history failed for %s.", settings.mask_phone(phone))


def list_conversations(limit: int = 50) -> list[dict]:
    """Each row carries both `phone_masked` (for display) and `phone` (the
    real normalized number, needed so the dashboard's clear-history action
    can actually find the right Redis keys -- masking is one-way, so the
    masked form alone isn't enough to act on)."""
    client = _client()
    if client is None:
        phones = list(_mem_conversations)
        rows = [{"phone": p, "phone_masked": settings.mask_phone(p), **_mem_meta.get(p, {})} for p in phones]
    else:
        try:
            phones = list(client.smembers(_CONVERSATIONS_KEY))
            rows = []
            for p in phones:
                meta = client.hgetall(_META_PREFIX + p) or {}
                rows.append({"phone": p, "phone_masked": settings.mask_phone(p), **meta})
        except Exception:
            logger.exception("list_conversations failed.")
            return []
    rows.sort(key=lambda r: r.get("last_ts", ""), reverse=True)
    return rows[:limit]


def increment_counter(name: str) -> None:
    client = _client()
    if client is None:
        _mem_counters[name] = _mem_counters.get(name, 0) + 1
        return
    try:
        client.incr(f"wa:stats:{name}")
    except Exception:
        logger.exception("increment_counter(%s) failed.", name)


def mark_first_seen() -> None:
    global _mem_first_seen
    client = _client()
    if client is None:
        if _mem_first_seen is None:
            _mem_first_seen = _now_iso()
        return
    try:
        client.setnx(_FIRST_SEEN_KEY, _now_iso())
    except Exception:
        logger.exception("mark_first_seen failed.")


def get_stats() -> dict:
    client = _client()
    if client is None:
        return {
            "total_conversations": len(_mem_conversations),
            "ai_handled": _mem_counters.get("ai_handled", 0),
            "human_routed": _mem_counters.get("human_routed", 0),
            "live_since": _mem_first_seen,
        }
    try:
        return {
            "total_conversations": client.scard(_CONVERSATIONS_KEY) or 0,
            "ai_handled": int(client.get(f"wa:stats:ai_handled") or 0),
            "human_routed": int(client.get(f"wa:stats:human_routed") or 0),
            "live_since": client.get(_FIRST_SEEN_KEY),
        }
    except Exception:
        logger.exception("get_stats failed.")
        return {"total_conversations": 0, "ai_handled": 0, "human_routed": 0, "live_since": None}
