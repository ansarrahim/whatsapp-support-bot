"""Admin dashboard blueprint, mounted at /admin. Every number on this page
traces to a real memory.py read (Redis, or the in-memory fallback) -- no
fabricated stats, including no fake "uptime": see get_stats()['live_since'].

Gated by HTTP Basic Auth (see _require_admin_auth below) -- previously this
whole blueprint, including a destructive "clear conversation" action, was
open to anyone who found the URL.
"""

from flask import Blueprint, Response, jsonify, render_template, request

from bot import memory
from config import settings

admin_bp = Blueprint("admin", __name__, url_prefix="/admin", template_folder="templates")


@admin_bp.before_request
def _require_admin_auth():
    auth = request.authorization
    if not settings.ADMIN_PASSWORD or not auth or auth.password != settings.ADMIN_PASSWORD:
        return Response(
            "Authentication required.",
            401,
            {"WWW-Authenticate": 'Basic realm="Admin"'},
        )


@admin_bp.route("/")
def index():
    return render_template("dashboard.html", bot_name=settings.BOT_NAME)


@admin_bp.route("/api/stats")
def api_stats():
    return jsonify(memory.get_stats())


@admin_bp.route("/api/conversations")
def api_conversations():
    return jsonify(memory.list_conversations())


@admin_bp.route("/api/conversations/<path:phone>/clear", methods=["POST"])
def api_clear_conversation(phone: str):
    memory.clear_history(phone)
    return jsonify({"ok": True})
