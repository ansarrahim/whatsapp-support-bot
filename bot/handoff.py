"""Human escalation via Gmail SMTP (App Password), plain smtplib -- not OAuth.
Never raises: if mail isn't configured or sending fails, logs a warning and
returns False so the webhook keeps responding normally either way.
"""

import logging
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText

from config import settings

logger = logging.getLogger(__name__)


def escalate_to_human(sender: str, message: str, history: list[dict]) -> bool:
    if not (settings.GMAIL_USER and settings.GMAIL_APP_PASSWORD and settings.AGENT_EMAIL):
        logger.warning("Gmail handoff not configured (GMAIL_USER/GMAIL_APP_PASSWORD/AGENT_EMAIL) -- skipping email.")
        return False

    masked = settings.mask_phone(sender)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    recent = history[-5:]
    history_html = "".join(
        f"<p><b>{h['role']}:</b> {h['content']}</p>" for h in recent
    ) or "<p>(no prior messages)</p>"

    body = f"""
    <h2>{settings.BOT_NAME} — escalation</h2>
    <p><b>From:</b> {masked}</p>
    <p><b>Time:</b> {timestamp}</p>
    <p><b>Triggering message:</b> {message}</p>
    <h3>Recent conversation</h3>
    {history_html}
    """

    msg = MIMEText(body, "html")
    msg["Subject"] = f"{settings.BOT_NAME}: customer needs help ({masked})"
    msg["From"] = settings.GMAIL_USER
    msg["To"] = settings.AGENT_EMAIL

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(settings.GMAIL_USER, settings.GMAIL_APP_PASSWORD)
            server.sendmail(settings.GMAIL_USER, [settings.AGENT_EMAIL], msg.as_string())
        logger.info("Escalation email sent for %s.", masked)
        return True
    except Exception:
        logger.exception("Failed to send escalation email for %s.", masked)
        return False
