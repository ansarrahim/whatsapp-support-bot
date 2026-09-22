"""Admin dashboard blueprint, mounted at /admin. Every number on this page
traces to a real memory.py read (Redis, or the in-memory fallback) -- no
fabricated stats, including no fake "uptime": see get_stats()['live_since'].
"""

from flask import Blueprint, jsonify, render_template

from bot import memory

admin_bp = Blueprint("admin", __name__, url_prefix="/admin", template_folder="templates")


@admin_bp.route("/")
def index():
    return render_template("index.html", bot_name="SupportBot")


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
