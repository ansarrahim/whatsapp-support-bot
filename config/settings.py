"""Central env-var loading. Deliberately does NOT crash on missing values at
import time -- bot/memory.py's in-memory fallback and the other modules'
graceful-degradation paths depend on being able to boot with zero credentials
configured. Call validate() from /health to surface what's missing instead.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# --- Twilio ---
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")

# --- Google Gemini ---
# Passed explicitly to genai.Client(api_key=...) rather than relying on the
# SDK's implicit env-var auto-detection, which looks for GEMINI_API_KEY, not
# GOOGLE_API_KEY as named here -- avoids a silent local-vs-deployed mismatch.
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
# gemini-2.5-flash is the one model name verified working at build time (via
# a live call in a separate project earlier the same session). Gemini's
# lineup moves fast -- check https://ai.google.dev/gemini-api/docs/models
# before a real deploy rather than trusting these defaults blindly.
GEMINI_CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-2.5-flash")
GEMINI_CLASSIFY_MODEL = os.getenv("GEMINI_CLASSIFY_MODEL", "gemini-2.5-flash")

# --- Upstash Redis ---
UPSTASH_REDIS_REST_URL = os.getenv("UPSTASH_REDIS_REST_URL")
UPSTASH_REDIS_REST_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")

# --- Gmail SMTP ---
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
AGENT_EMAIL = os.getenv("AGENT_EMAIL")

# --- Bot config ---
BOT_NAME = os.getenv("BOT_NAME", "SupportBot")
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "10"))
ESCALATION_KEYWORDS = [
    kw.strip().lower()
    for kw in os.getenv("ESCALATION_KEYWORDS", "refund,complaint,manager,urgent,broken,angry").split(",")
    if kw.strip()
]

# --- Admin dashboard auth ---
# HTTP Basic Auth, single shared password (no separate username). Unset means
# /admin is closed entirely (401), not silently open -- same fail-safe
# direction as everything else here.
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

# --- Abuse guards ---
MAX_WEBHOOK_MESSAGE_LENGTH = 2000  # WhatsApp's own text limit is ~4096; well under it
MAX_DEMO_MESSAGE_LENGTH = 300
DEMO_RATE_LIMIT_PER_MINUTE = 5


def validate() -> list[str]:
    """Return the names of unset required-for-full-operation env vars.
    Never raises -- callers (e.g. /health) decide what to do with the list."""
    required = {
        "TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID,
        "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN,
        "GOOGLE_API_KEY": GOOGLE_API_KEY,
        "UPSTASH_REDIS_REST_URL": UPSTASH_REDIS_REST_URL,
        "UPSTASH_REDIS_REST_TOKEN": UPSTASH_REDIS_REST_TOKEN,
        "GMAIL_USER": GMAIL_USER,
        "GMAIL_APP_PASSWORD": GMAIL_APP_PASSWORD,
        "AGENT_EMAIL": AGENT_EMAIL,
    }
    return [name for name, value in required.items() if not value]


def mask_phone(phone: str) -> str:
    """'whatsapp:+15551234567' -> '+1555***4567' (keep country code + last 4)."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) <= 6:
        return "***" + digits[-2:] if digits else "***"
    return f"+{digits[:4]}***{digits[-4:]}"
