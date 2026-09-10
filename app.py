import html
import os
import re
import time
from threading import Lock

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
API_TOKEN = os.getenv("API_TOKEN", "").strip()
API_URL = os.getenv("API_URL", "https://leakosintapi.com/").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
MAX_QUERY_LENGTH = int(os.getenv("MAX_QUERY_LENGTH", "120"))
API_LIMIT = min(max(int(os.getenv("API_LIMIT", "100")), 100), 10000)
RATE_LIMIT_SECONDS = float(os.getenv("RATE_LIMIT_SECONDS", "3"))

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
_last_request = {}
_rate_lock = Lock()


def telegram(method, payload):
    response = requests.post(f"{TELEGRAM_API}/{method}", json=payload, timeout=30)
    response.raise_for_status()
    return response.json()


def send_message(chat_id, text):
    return telegram("sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })


def detect_query_type(query):
    value = query.strip()
    if re.fullmatch(r"\+?[0-9][0-9 .()-]{7,19}", value):
        return "nomor telepon"
    if re.fullmatch(r"[0-9]{16}", value):
        return "NIK"
    if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        return "email"
    if re.fullmatch(r"@?[A-Za-z0-9_.-]{3,64}", value):
        return "username / identifier"
    if "." in value and " " not in value:
        return "domain / identifier"
    return "nama / identifier"


def allowed_query(query):
    if not query or len(query) > MAX_QUERY_LENGTH:
        return False
    if any(ch in query for ch in ["\n", "\r", "<", ">"]):
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9@+_.()\- /]{3,120}", query))


def rate_allowed(user_id):
    now = time.monotonic()
    with _rate_lock:
        previous = _last_request.get(user_id, 0)
        if now - previous < RATE_LIMIT_SECONDS:
            return False
        _last_request[user_id] = now
    return True


def query_api(query):
    payload = {
        "token": API_TOKEN,
        "request": query,
        "limit": API_LIMIT,
        "lang": os.getenv("API_LANG", "en"),
        "type": "json",
    }
    response = requests.post(API_URL, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()


def _split_telegram_text(text, max_length=3900):
    if len(text) <= max_length:
        return [text]
    chunks, current, size = [], [], 0
    for line in text.split("\n"):
        addition = len(line) + (1 if current else 0)
        if current and size + addition > max_length:
            chunks.append("\n".join(current))
            current, size = [line], len(line)
        else:
            current.append(line)
            size += addition
    if current:
        chunks.append("\n".join(current))
    return chunks


def _format_value(value, indent=0):
    """Recursively render the API JSON into readable Telegram HTML."""
    pad = "  " * indent
    lines = []

    if isinstance(value, dict):
        for key, item in value.items():
            key_text = html.escape(str(key))
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}<b>▸ {key_text}</b>")
                lines.extend(_format_value(item, indent + 1))
            else:
                value_text = html.escape(str(item))
                lines.append(f"{pad}• <b>{key_text}:</b> <code>{value_text}</code>")
    elif isinstance(value, list):
        for index, item in enumerate(value, 1):
            lines.append(f"{pad}<b>Record {index}</b>")
            if isinstance(item, (dict, list)):
                lines.extend(_format_value(item, indent + 1))
            else:
                lines.append(f"{pad}• <code>{html.escape(str(item))}</code>")
    else:
        lines.append(f"{pad}<code>{html.escape(str(value))}</code>")

    return lines


def format_result(query, result):
    """Format the API response without changing its fields or values."""
    query_type = detect_query_type(query)

    if not isinstance(result, dict):
        return ["❌ API mengembalikan format yang tidak dikenali."]

    if result.get("Error code"):
        error = html.escape(str(result.get("Error code")))
        return [f"❌ <b>API ERROR</b>\n\n<code>{error}</code>"]

    lines = [
        "🔎 <b>GWPROJECT — HASIL PEMERIKSAAN</b>",
        "",
        f"📌 Jenis: <b>{html.escape(query_type)}</b>",
        f"🎯 Query: <code>{html.escape(query)}</code>",
        "",
    ]

    # Render the complete JSON response, including nested objects and arrays.
    lines.extend(_format_value(result))
    lines.extend(["", "━━━━━━━━━━━━━━━━━━━━", "✅ Selesai"])
    return _split_telegram_text("\n".join(lines))


@app.get("/")
def home():
    return jsonify({"status": "ok", "service": "GWProject Telegram Bot"})


@app.post("/webhook")
def webhook():
    if WEBHOOK_SECRET:
        provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if provided != WEBHOOK_SECRET:
            return jsonify({"ok": False}), 403

    update = request.get_json(silent=True) or {}
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    user = message.get("from") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()

    if not chat_id or not text:
        return jsonify({"ok": True})

    if text.startswith("/start"):
        send_message(chat_id,
            "🛡️ <b>GWPROJECT DATA SECURITY</b>\n\n"
            "Bot aktif.\n\n"
            "Gunakan:\n"
            "<code>/cek 081234567890</code>\n"
            "<code>/cek user@example.com</code>\n"
            "<code>/cek @username</code>\n"
            "<code>/cek 3201234567890001</code>\n"
            "<code>/cek Budi Santoso</code>"
        )
        return jsonify({"ok": True})

    if text.startswith("/cek"):
        query = text[4:].strip()
        user_id = user.get("id", chat_id)

        if not allowed_query(query):
            send_message(chat_id,
                "❌ Format tidak valid atau terlalu panjang.\n\n"
                "Contoh: <code>/cek 081234567890</code> atau "
                "<code>/cek Budi Santoso</code>"
            )
            return jsonify({"ok": True})

        if not rate_allowed(user_id):
            send_message(chat_id, "⏱️ Tunggu beberapa detik sebelum melakukan pemeriksaan lagi.")
            return jsonify({"ok": True})

        query_type = detect_query_type(query)
        send_message(chat_id, f"🔎 Memproses <b>{html.escape(query_type)}</b>...")

        try:
            result = query_api(query)
            for chunk in format_result(query, result):
                send_message(chat_id, chunk)
        except requests.RequestException:
            send_message(chat_id, "❌ API tidak dapat dihubungi saat ini.")
        except (ValueError, TypeError):
            send_message(chat_id, "❌ Respons API tidak valid.")
        except Exception:
            send_message(chat_id, "❌ Terjadi kesalahan internal.")

        return jsonify({"ok": True})

    send_message(chat_id,
        "Perintah yang tersedia:\n\n"
        "🔎 <code>/cek nomor-telepon</code>\n"
        "🔎 <code>/cek email@example.com</code>\n"
        "🔎 <code>/cek @username</code>\n"
        "🔎 <code>/cek NIK</code>\n"
        "🔎 <code>/cek Nama Lengkap</code>"
    )
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
