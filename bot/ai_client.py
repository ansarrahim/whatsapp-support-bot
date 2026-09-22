"""Gemini integration via the current `google-genai` SDK (the older
`google-generativeai` package is deprecated -- do not reintroduce it).
Every function here fails gracefully: classification fails toward "complex"
(routes to a human rather than risking a wrong auto-answer), generation and
transcription fail toward a safe fallback string/exception the caller
already expects, so a missing/invalid GOOGLE_API_KEY never crashes /webhook.
"""

import json
import logging

import requests

from config import settings

logger = logging.getLogger(__name__)

_client_cache = None
_client_checked = False


class VoiceTranscriptionError(Exception):
    """Raised when a voice note can't be downloaded or transcribed."""


def _client():
    global _client_cache, _client_checked
    if _client_checked:
        return _client_cache
    _client_checked = True
    if not settings.GOOGLE_API_KEY:
        logger.warning("GOOGLE_API_KEY not set -- AI calls will fail gracefully.")
        return None
    try:
        from google import genai

        _client_cache = genai.Client(api_key=settings.GOOGLE_API_KEY)
    except Exception:
        logger.exception("Failed to initialize Gemini client.")
        _client_cache = None
    return _client_cache


_CLASSIFY_PROMPT = """Classify the customer's message into exactly one word, no
punctuation, no explanation. Choose from: greeting, faq, complex, human_request.

- greeting: a hello/hi/thanks with no actual question
- faq: a question likely answerable from a restaurant FAQ (hours, menu, location,
  reservations, delivery, payment, parking, kids, catering, gift cards)
- complex: a complaint, refund request, problem, or anything an FAQ can't answer
- human_request: the customer is explicitly asking to talk to a person

Conversation so far:
{history}

Customer's new message: {message}

Respond with exactly one word."""


def classify_intent(message: str, history: list[dict]) -> str:
    client = _client()
    if client is None:
        return "complex"
    try:
        history_text = "\n".join(f"{h['role']}: {h['content']}" for h in history[-6:]) or "(no prior messages)"
        response = client.models.generate_content(
            model=settings.GEMINI_CLASSIFY_MODEL,
            contents=_CLASSIFY_PROMPT.format(history=history_text, message=message),
        )
        label = (response.text or "").strip().lower()
        if label in {"greeting", "faq", "complex", "human_request"}:
            return label
        logger.warning("classify_intent got an unexpected label %r -- defaulting to complex.", label)
        return "complex"
    except Exception:
        logger.exception("classify_intent failed -- defaulting to complex.")
        return "complex"


_RESPONSE_PROMPT = """You are {bot_name}, a friendly WhatsApp support assistant
for a restaurant. Answer using ONLY the FAQ knowledge base below -- if the
answer isn't in it, say you're not sure and that you're looping in the team.
Keep it to 3 sentences max, plain text, no markdown, no bullet points
(this is a WhatsApp message).

FAQ knowledge base:
{faqs}

Conversation so far:
{history}

Customer's new message: {message}"""


def generate_response(message: str, history: list[dict], faqs: list[dict]) -> str:
    client = _client()
    if client is None:
        return "Thanks for reaching out! Our AI assistant isn't fully connected yet -- I'm flagging this for our team to follow up."
    try:
        faqs_text = json.dumps(faqs, ensure_ascii=False)
        history_text = "\n".join(f"{h['role']}: {h['content']}" for h in history[-6:]) or "(no prior messages)"
        response = client.models.generate_content(
            model=settings.GEMINI_CHAT_MODEL,
            contents=_RESPONSE_PROMPT.format(
                bot_name=settings.BOT_NAME, faqs=faqs_text, history=history_text, message=message
            ),
        )
        text = (response.text or "").strip()
        return text or "Sorry, I didn't quite catch that -- could you rephrase?"
    except Exception:
        logger.exception("generate_response failed.")
        return "Sorry, I'm having trouble answering that right now -- I'll get our team to follow up with you."


def transcribe_voice(media_url: str, auth: tuple[str, str]) -> str:
    """Downloads a Twilio voice-note media URL (requires Basic Auth) and
    transcribes it via Gemini. Raises VoiceTranscriptionError on any failure
    so the caller can route to a human rather than silently mis-transcribing."""
    client = _client()
    if client is None:
        raise VoiceTranscriptionError("Gemini client not configured (GOOGLE_API_KEY missing).")
    try:
        audio_resp = requests.get(media_url, auth=auth, timeout=30)
        audio_resp.raise_for_status()
        audio_bytes = audio_resp.content
    except Exception as exc:
        raise VoiceTranscriptionError(f"Could not download voice note: {exc}") from exc

    try:
        response = client.models.generate_content(
            model=settings.GEMINI_CHAT_MODEL,
            contents=[
                {"inline_data": {"mime_type": "audio/ogg", "data": audio_bytes}},
                "Transcribe this voice message. Reply with only the transcription, nothing else.",
            ],
        )
        text = (response.text or "").strip()
        if not text:
            raise VoiceTranscriptionError("Transcription came back empty.")
        return text
    except VoiceTranscriptionError:
        raise
    except Exception as exc:
        raise VoiceTranscriptionError(f"Transcription failed: {exc}") from exc
