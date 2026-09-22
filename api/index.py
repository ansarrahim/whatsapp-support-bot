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

from flask import Flask, Response, request

from config import settings
from bot.responder import build_response
from dashboard.routes import admin_bp

app = Flask(__name__)
app.register_blueprint(admin_bp)


@app.route("/", methods=["GET"])
def home():
    missing = settings.validate()
    status_line = "Fully configured" if not missing else f"{len(missing)} credential(s) not yet configured"
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{settings.BOT_NAME}</title>
<style>
body{{background:#0b0f14;color:#e6edf3;font-family:-apple-system,sans-serif;
max-width:640px;margin:60px auto;padding:0 20px;line-height:1.5}}
a{{color:#34d399}} code{{background:#12181f;padding:2px 6px;border-radius:4px}}
.status{{color:{'#34d399' if not missing else '#f87171'}}}
</style></head><body>
<h1>{settings.BOT_NAME}</h1>
<p>A WhatsApp AI customer-support bot. Status: <span class="status">{status_line}</span></p>
<p><a href="/admin">Admin dashboard</a> &middot; <a href="/health">Health check (JSON)</a></p>
<p>Twilio webhook endpoint: <code>POST /webhook</code></p>
</body></html>"""


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
