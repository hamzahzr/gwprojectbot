import html
import os
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
    response = requests.post(
        f"{TELEGRAM_API}/{method}",
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def send_message(chat_id, text):
    return telegram(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
    )


def allowed_query(query):
    # Initial version is deliberately limited to email/domain checks.
    if not query or len(query) > MAX_QUERY_LENGTH:
        return False
    if any(ch in query for ch in ["\n", "\r", "<", ">"]):
        return False
    return "@" in query or "." in query


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


def format_safe_result(query, result):
    # Do not forward raw breach records or personal data to Telegram.
    if not isinstance(result, dict):
        return "⚠️ API mengembalikan format yang tidak dikenali."

    if result.get("Error code"):
        return "⚠️ Pemeriksaan gagal karena API mengembalikan error."

    listing = result.get("List")
    if not isinstance(listing, dict):
        return "ℹ️ Tidak ada hasil yang dapat ditampilkan."

    names = [str(name) for name in listing.keys()]
    names = [name for name in names if name.lower() != "no results found"]

    if not names:
        return (
            "🔎 <b>HASIL PEMERIKSAAN</b>\n\n"
            f"Target: <code>{html.escape(query)}</code>\n"
            "Status: ✅ Tidak ada sumber yang terdeteksi oleh API."
        )

    shown = names[:10]
    sources = "\n".join(f"• {html.escape(name)}" for name in shown)
    extra = len(names) - len(shown)
    if extra > 0:
        sources += f"\n• +{extra} sumber lainnya"

    return (
        "🔎 <b>HASIL PEMERIKSAAN</b>\n\n"
        f"Target: <code>{html.escape(query)}</code>\n"
        "Status: ⚠️ Sumber terdeteksi\n\n"
        "Sumber/database yang terdeteksi:\n"
        f"{sources}\n\n"
        "ℹ️ Bot hanya menampilkan ringkasan. Data pribadi mentah "
        "dari sumber kebocoran tidak diteruskan ke Telegram."
    )


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
        send_message(
            chat_id,
            "🛡️ <b>GWPROJECT DATA SECURITY</b>\n\n"
            "Bot aktif.\n\n"
            "Gunakan:\n"
            "<code>/cek email@example.com</code>\n\n"
            "Gunakan bot hanya untuk pemeriksaan data yang Anda miliki "
            "atau yang memang Anda berwenang untuk periksa.",
        )
        return jsonify({"ok": True})

    if text.startswith("/cek"):
        query = text[4:].strip()
        user_id = user.get("id", chat_id)

        if not allowed_query(query):
            send_message(
                chat_id,
                "❌ Format tidak valid. Versi awal hanya menerima "
                "email atau domain.\n\n"
                "Contoh:\n<code>/cek email@example.com</code>",
            )
            return jsonify({"ok": True})

        if not rate_allowed(user_id):
            send_message(chat_id, "⏱️ Tunggu beberapa detik sebelum melakukan pemeriksaan lagi.")
            return jsonify({"ok": True})

        send_message(chat_id, "🔎 Memproses pemeriksaan...")

        try:
            result = query_api(query)
            send_message(chat_id, format_safe_result(query, result))
        except requests.RequestException:
            send_message(chat_id, "❌ API tidak dapat dihubungi saat ini.")
        except (ValueError, TypeError):
            send_message(chat_id, "❌ Respons API tidak valid.")
        except Exception:
            send_message(chat_id, "❌ Terjadi kesalahan internal.")

        return jsonify({"ok": True})

    send_message(
        chat_id,
        "Perintah yang tersedia:\n\n"
        "🔎 <code>/cek email@example.com</code>\n"
        "ℹ️ <code>/start</code>",
    )
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
