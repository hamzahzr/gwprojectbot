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
        return "Nomor HP"
    if re.fullmatch(r"[0-9]{16}", value):
        return "NIK"
    if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        return "Email"
    if re.fullmatch(r"@?[A-Za-z0-9_.-]{3,64}", value):
        return "Username"
    return "Nama"


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


def format_simple_result(query, result):
    """Format results into a clean Telegram layout while masking sensitive values."""
    if not isinstance(result, dict):
        return ["❌ Data tidak dapat ditampilkan."]

    if result.get("Error code"):
        return ["❌ Pencarian gagal. Silakan coba lagi."]

    listing = result.get("List")
    if not isinstance(listing, dict):
        return ["🔎 <b>GWPROJECT RESULT</b>\n\nTidak ada data ditemukan."]

    sources = []
    total_records = 0
    for source_name, source_data in listing.items():
        if str(source_name).lower() == "no results found":
            continue
        records = source_data if isinstance(source_data, list) else [source_data]
        records = [r for r in records if r not in (None, "", [], {})]
        if records:
            sources.append((str(source_name), records))
            total_records += len(records)

    if not sources:
        return ["🔎 <b>GWPROJECT RESULT</b>\n\nTidak ada data ditemukan."]

    header = (
        "╔════════════════════════════════╗\n"
        "║       <b>GWPROJECT RESULT</b>         ║\n"
        "╚════════════════════════════════╝\n\n"
        "🔎 <b>QUERY</b>\n"
        f"<code>{html.escape(query)}</code>\n\n"
    )

    parts = [header]
    record_number = 0
    for source_name, records in sources:
        parts.append(
            "📁 <b>SOURCE</b>\n"
            f"{html.escape(source_name)}\n"
        )
        for record in records:
            record_number += 1
            parts.append(f"📄 <b>RECORD #{record_number}</b>\n────────────────────────────────")
            if isinstance(record, dict):
                for key, value in record.items():
                    if value in (None, "", [], {}):
                        continue
                    value = _compact_value(value)
                    value = _mask_sensitive(key, value)
                    parts.append(
                        f"{html.escape(_pretty_key(key)):18}: <code>{html.escape(str(value))}</code>"
                    )
            else:
                parts.append(f"Data               : <code>{html.escape(str(record))}</code>")
            parts.append("")

    parts.append(
        "📊 <b>SUMMARY</b>\n"
        "────────────────────────────────\n"
        f"Sources : {len(sources)}\n"
        f"Records : {total_records}"
    )

    text = "\n".join(parts).strip()
    return split_message(text)


def split_message(text, max_length=3900):
    if len(text) <= max_length:
        return [text]
    chunks = []
    current = ""
    for block in text.split("\n\n"):
        candidate = block if not current else current + "\n\n" + block
        if current and len(candidate) > max_length:
            chunks.append(current)
            current = block
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _pretty_key(key):
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(key))
    text = text.replace("_", " ").replace("-", " ")
    return " ".join(text.split()).title()


def _compact_value(value):
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            if item not in (None, "", [], {}):
                parts.append(f"{_pretty_key(key)}: {item}")
        return " | ".join(parts)
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return value


def _mask_sensitive(key, value):
    """Prevent raw personal identifiers, credentials, and secrets from being echoed."""
    key_text = str(key).lower().replace("_", " ").replace("-", " ")
    sensitive = (
        "nik", "phone", "mobile", "telephone", "email", "e mail", "address",
        "nama", "name", "username", "password", "passwd", "token", "secret",
        "api key", "apikey", "cookie", "session", "credit", "card", "ssn"
    )
    if any(term in key_text for term in sensitive):
        text = str(value)
        if len(text) <= 4:
            return "••••"
        return text[:2] + "••••" + text[-2:]
    return value


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
            "🔎 <b>GWPROJECT</b>\n\n"
            "Gunakan perintah:\n\n"
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
            send_message(chat_id, "❌ Format pencarian tidak valid.")
            return jsonify({"ok": True})

        if not rate_allowed(user_id):
            send_message(chat_id, "⏱️ Tunggu beberapa detik sebelum pencarian berikutnya.")
            return jsonify({"ok": True})

        send_message(chat_id, "🔎 <b>Mencari...</b>")

        try:
            result = query_api(query)
            for chunk in format_simple_result(query, result):
                send_message(chat_id, chunk)
        except requests.RequestException:
            send_message(chat_id, "❌ Server tidak dapat dihubungi.")
        except (ValueError, TypeError):
            send_message(chat_id, "❌ Respons server tidak valid.")
        except Exception:
            send_message(chat_id, "❌ Terjadi kesalahan. Silakan coba lagi.")

        return jsonify({"ok": True})

    send_message(chat_id,
        "Perintah:\n\n"
        "<code>/cek nomor HP</code>\n"
        "<code>/cek email</code>\n"
        "<code>/cek username</code>\n"
        "<code>/cek NIK</code>\n"
        "<code>/cek nama lengkap</code>"
    )
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
