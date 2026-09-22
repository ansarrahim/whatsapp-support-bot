"""Orchestrates: get history -> transcribe (if voice) -> classify -> route ->
save -> return reply. This is the one place all the other modules meet.
"""

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from config import settings
from bot import ai_client, handoff, memory

logger = logging.getLogger(__name__)

FOOTER = "\n\n— Reply HUMAN anytime to reach our team"
_HUMAN_WORD_RE = re.compile(r"\bhuman\b", re.IGNORECASE)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=1)
def load_faqs() -> list[dict]:
    with open(_DATA_DIR / "faqs.json", "r", encoding="utf-8") as f:
        return json.load(f)


def _is_escalation_triggered(message: str, intent: str) -> bool:
    """Deterministic override on top of the LLM classifier -- a keyword/word
    match always wins even if the classifier says something else."""
    if intent in ("complex", "human_request"):
        return True
    if _HUMAN_WORD_RE.search(message):
        return True
    lowered = message.lower()
    return any(keyword in lowered for keyword in settings.ESCALATION_KEYWORDS)


def build_response(message: str, sender: str, media_url: str | None) -> str:
    history = memory.get_history(sender)

    if media_url:
        try:
            message = ai_client.transcribe_voice(
                media_url, auth=(settings.TWILIO_ACCOUNT_SID or "", settings.TWILIO_AUTH_TOKEN or "")
            )
        except ai_client.VoiceTranscriptionError:
            logger.exception("Voice transcription failed for %s.", settings.mask_phone(sender))
            reply = (
                "Sorry, I couldn't quite make out that voice note — could you type "
                "your question instead?"
            ) + FOOTER
            memory.save_message(sender, "user", "[voice note — transcription failed]")
            memory.save_message(sender, "assistant", reply)
            memory.update_meta(sender, last_message="[voice note]", last_intent="voice_failed")
            return reply

    intent = ai_client.classify_intent(message, history)
    escalate = _is_escalation_triggered(message, intent)

    if escalate:
        handoff.escalate_to_human(sender, message, history)
        reply = "Got it — I'm connecting you with our team, they'll follow up with you shortly."
        memory.increment_counter("human_routed")
    elif intent == "greeting":
        reply = f"Hey there! I'm {settings.BOT_NAME}. Ask me about hours, reservations, delivery, or anything else — happy to help."
        memory.increment_counter("ai_handled")
    else:
        reply = ai_client.generate_response(message, history, load_faqs())
        memory.increment_counter("ai_handled")

    reply += FOOTER

    memory.save_message(sender, "user", message)
    memory.save_message(sender, "assistant", reply)
    memory.update_meta(sender, last_message=message, last_intent=intent)

    return reply
