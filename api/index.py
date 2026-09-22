"""Vercel entrypoint. Vercel's Python runtime detects the top-level `app`
WSGI object directly -- no serverless-wsgi wrapper needed. Verified with a
smoke-test deploy (including a cross-package import) before this real
version was written.
"""

import logging
import os
import sys
from datetime import datetime, timezone

# Defensive: guarantees `bot`, `dashboard`, `config` import as siblings of
# `api/` regardless of Vercel's exact working-directory/sys.path behavior.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows console default encoding can't print em-dashes/non-ASCII text during
# local dev -- harmless on Vercel's Linux runtime, but fixes local debugging.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from flask import Flask, Response, jsonify, render_template, request

from config import settings
from bot.responder import build_demo_response, build_response
from dashboard.routes import admin_bp

app = Flask(__name__)
app.register_blueprint(admin_bp)

_MAX_DEMO_MESSAGE_LENGTH = 300


@app.route("/", methods=["GET"])
def home():
    missing = settings.validate()
    status_line = "Fully configured" if not missing else f"{len(missing)} credential(s) not yet configured"
    return render_template(
        "index.html",
        bot_name=settings.BOT_NAME,
        status_line=status_line,
        status_color="#34d399" if not missing else "#f87171",
    )


@app.route("/api/demo", methods=["POST"])
def api_demo():
    """Public, stateless chat demo -- lets a visitor try the real Gemini
    pipeline right on the landing page without needing WhatsApp/Twilio set
    up. No memory writes, no escalation email (see build_demo_response's
    docstring). Message length is capped as a light abuse guard; a proper
    per-IP rate limit would need Upstash, which isn't wired up here yet."""
    data = request.get_json(silent=True) or {}
    message = str(data.get("message", "")).strip()[:_MAX_DEMO_MESSAGE_LENGTH]
    if not message:
        return jsonify({"intent": "error", "reply": "Type something first!"}), 400

    try:
        result = build_demo_response(message)
    except Exception:
        logging.exception("build_demo_response failed.")
        result = {"intent": "error", "reply": "Sorry, something went wrong on our end -- try again in a moment."}

    return jsonify(result)


@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.form.get("Body", "")
    sender = request.form.get("From", "")
    media_url = request.form.get("MediaUrl0")

    try:
        reply = build_response(body, sender, media_url)
    except Exception:
        logging.exception("build_response raised unexpectedly for %s.", settings.mask_phone(sender))
        reply = "Sorry, something went wrong on our end -- I'm flagging this for our team."

    logging.info(
        "webhook sender=%s has_media=%s reply_len=%d",
        settings.mask_phone(sender),
        bool(media_url),
        len(reply),
    )

    twiml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{_xml_escape(reply)}</Message></Response>'
    return Response(twiml, mimetype="text/xml")


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


@app.route("/health", methods=["GET"])
def health():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": settings.GEMINI_CHAT_MODEL,
        "missing_config": settings.validate(),
    }


if __name__ == "__main__":
    app.run(debug=True, port=5000)
