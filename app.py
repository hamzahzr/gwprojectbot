import html
import os
import re
import sqlite3
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
ADMIN_IDS = {x.strip() for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
DB_PATH = os.getenv("ACCESS_DB", os.path.join(os.path.dirname(__file__), "access.db"))

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
_last_request = {}
_rate_lock = Lock()
_db_lock = Lock()
_pending_admin = {}

PERMISSIONS = {
    "search": "🔎 Pencarian",
    "ai": "🧠 AI Analysis",
    "history": "📚 Riwayat",
    "tools": "🧰 Tools",
}


def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            role TEXT NOT NULL DEFAULT 'user',
            permissions TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL
        )"""
    )
    conn.commit()
    return conn


def get_user(user_id):
    with _db_lock:
        conn = db()
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (str(user_id),)).fetchone()
        conn.close()
    return row


def ensure_user(user_id):
    if str(user_id) in ADMIN_IDS:
        return
    if not get_user(user_id):
        with _db_lock:
            conn = db()
            conn.execute(
                "INSERT OR IGNORE INTO users(user_id, role, permissions, created_at) VALUES (?, 'user', '', ?)",
                (str(user_id), int(time.time())),
            )
            conn.commit()
            conn.close()


def has_permission(user_id, permission):
    if str(user_id) in ADMIN_IDS:
        return True
    row = get_user(user_id)
    if not row:
        return False
    permissions = {p for p in row["permissions"].split(",") if p}
    return permission in permissions


def set_permission(user_id, permission, enabled):
    if str(user_id) in ADMIN_IDS:
        return
    ensure_user(user_id)
    row = get_user(user_id)
    permissions = {p for p in row["permissions"].split(",") if p}
    if enabled:
        permissions.add(permission)
    else:
        permissions.discard(permission)
    value = ",".join(sorted(permissions))
    with _db_lock:
        conn = db()
        conn.execute("UPDATE users SET permissions = ? WHERE user_id = ?", (value, str(user_id)))
        conn.commit()
        conn.close()


def remove_user(user_id):
    if str(user_id) in ADMIN_IDS:
        return
    with _db_lock:
        conn = db()
        conn.execute("DELETE FROM users WHERE user_id = ?", (str(user_id),))
        conn.commit()
        conn.close()


def list_users():
    with _db_lock:
        conn = db()
        rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        conn.close()
    return rows


def telegram(method, payload):
    response = requests.post(f"{TELEGRAM_API}/{method}", json=payload, timeout=30)
    response.raise_for_status()
    return response.json()


def send_message(chat_id, text, keyboard=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    return telegram("sendMessage", payload)


def answer_callback(callback_id):
    try:
        telegram("answerCallbackQuery", {"callback_query_id": callback_id})
    except Exception:
        pass


def main_keyboard(user_id):
    rows = []
    first = []
    if has_permission(user_id, "tools"):
        first.append({"text": "🧰 ALL TOOLS", "callback_data": "menu:tools"})
    if has_permission(user_id, "ai"):
        first.append({"text": "🧠 AI ANALYSIS", "callback_data": "menu:ai"})
    if first:
        rows.append(first)
    if has_permission(user_id, "history"):
        rows.append([{"text": "📚 RIWAYAT", "callback_data": "menu:history"}])
    if str(user_id) in ADMIN_IDS:
        rows.append([
            {"text": "⚙️ PENGATURAN", "callback_data": "menu:settings"},
            {"text": "ℹ️ STATUS", "callback_data": "menu:status"},
        ])
    else:
        rows.append([{"text": "ℹ️ STATUS", "callback_data": "menu:status"}])
    return rows


def welcome_text():
    return (
        "🛰️ <b>GW-PROJECT</b>\n"
        "<b>Private operations console</b>\n\n"
        "Pilih layanan dari menu di bawah.\n"
        "Setiap request dicatat untuk audit dan hanya memakai konektor yang diotorisasi."
    )


def settings_keyboard():
    return [
        [{"text": "➕ TAMBAH PENGGUNA", "callback_data": "settings:add"}],
        [{"text": "👥 DAFTAR PENGGUNA", "callback_data": "settings:list"}],
        [{"text": "🚫 CABUT AKSES", "callback_data": "settings:revoke"}],
        [{"text": "🔐 KELOLA HAK AKSES", "callback_data": "settings:permissions"}],
        [{"text": "🔙 KEMBALI", "callback_data": "menu:home"}],
    ]


def user_permission_keyboard(user_id):
    row = get_user(user_id)
    if not row:
        return [[{"text": "🔙 KEMBALI", "callback_data": "menu:settings"}]]
    active = {p for p in row["permissions"].split(",") if p}
    buttons = []
    for key, label in PERMISSIONS.items():
        prefix = "✅" if key in active else "⬜"
        buttons.append({"text": f"{prefix} {label}", "callback_data": f"perm:{user_id}:{key}"})
    return [buttons[:2], buttons[2:], [{"text": "🔙 KEMBALI", "callback_data": "menu:settings"}]]


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


def _pretty_key(key):
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(key))
    text = text.replace("_", " ").replace("-", " ")
    return " ".join(text.split()).title()


def _compact_value(value):
    if isinstance(value, dict):
        return " | ".join(
            f"{_pretty_key(key)}: {item}"
            for key, item in value.items()
            if item not in (None, "", [], {})
        )
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return value


def _plain_value(value):
    if isinstance(value, (dict, list)):
        value = _compact_value(value)
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def _format_record(record, number):
    lines = [f"📄 RECORD #{number}", "────────────────────────────────"]
    if isinstance(record, dict):
        fields = []
        for key, value in record.items():
            if value in (None, "", [], {}):
                continue
            fields.append((_pretty_key(key), _plain_value(value)))
        width = min(max((len(key) for key, _ in fields), default=10), 22)
        for key, value in fields:
            lines.append(f"{key:<{width}} : {value}")
    else:
        lines.append(f"Value{' ':<15}: {_plain_value(record)}")
    return "\n".join(lines)


def format_simple_result(query, result):
    if not isinstance(result, dict):
        return ["❌ Data tidak dapat ditampilkan."]
    if result.get("Error code"):
        return ["❌ Pencarian gagal. Silakan coba lagi."]
    listing = result.get("List")
    if not isinstance(listing, dict):
        return ["<b>GWPROJECT RESULT</b>\n\nTidak ada data ditemukan."]

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
        return ["<b>GWPROJECT RESULT</b>\n\nTidak ada data ditemukan."]

    header = (
        "<b>╔══════════════════════════════════╗</b>\n"
        "<b>║          GWPROJECT RESULT        ║</b>\n"
        "<b>╚══════════════════════════════════╝</b>\n\n"
        "🔎 <b>QUERY</b>\n"
        f"<code>{html.escape(detect_query_type(query))}  {html.escape(query)}</code>\n\n"
    )
    chunks = []
    current = header
    record_no = 0
    for source_index, (source_name, records) in enumerate(sources, 1):
        source_block = (
            f"📁 <b>SOURCE #{source_index}</b>\n"
            f"<code>{html.escape(source_name)}</code>\n\n"
        )
        if len(current) + len(source_block) > 3800 and current != header:
            chunks.append(current.rstrip())
            current = ""
        current += source_block
        for record in records:
            record_no += 1
            record_block = f"<pre>{html.escape(_format_record(record, record_no))}</pre>\n\n"
            if len(current) + len(record_block) > 3800 and current:
                chunks.append(current.rstrip())
                current = ""
            current += record_block
    summary = (
        "📊 <b>SUMMARY</b>\n"
        "────────────────────────────────\n"
        f"Sources : {len(sources)}\n"
        f"Records : {total_records}"
    )
    if len(current) + len(summary) > 3900 and current:
        chunks.append(current.rstrip())
        current = ""
    current += summary
    chunks.append(current.rstrip())
    return chunks


def handle_callback(callback):
    callback_id = callback.get("id")
    data = callback.get("data", "")
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    user = callback.get("from") or {}
    chat_id = chat.get("id")
    user_id = user.get("id", chat_id)
    answer_callback(callback_id)

    if not chat_id:
        return

    if data == "menu:home":
        send_message(chat_id, welcome_text(), main_keyboard(user_id))
        return

    if data == "menu:status":
        role = "ADMIN" if str(user_id) in ADMIN_IDS else (get_user(user_id)["role"].upper() if get_user(user_id) else "NONE")
        permissions = "FULL" if str(user_id) in ADMIN_IDS else ", ".join(
            PERMISSIONS[p] for p in PERMISSIONS if has_permission(user_id, p)
        ) or "Tidak ada"
        send_message(chat_id, f"ℹ️ <b>STATUS</b>\n\nRole: <b>{html.escape(role)}</b>\nAkses: {html.escape(permissions)}", [[{"text": "🔙 KEMBALI", "callback_data": "menu:home"}]])
        return

    if data == "menu:settings":
        if str(user_id) not in ADMIN_IDS:
            send_message(chat_id, "⛔ Akses admin diperlukan.")
            return
        send_message(chat_id, "⚙️ <b>PENGATURAN AKSES</b>\n\nKelola pengguna dan hak akses.", settings_keyboard())
        return

    if data == "settings:add":
        if str(user_id) not in ADMIN_IDS:
            return
        _pending_admin[user_id] = "add"
        send_message(chat_id, "➕ <b>TAMBAH PENGGUNA</b>\n\nKirim Telegram User ID yang ingin diberi akses.\n\nContoh: <code>123456789</code>", [[{"text": "❌ BATAL", "callback_data": "settings:cancel"}]])
        return

    if data == "settings:list":
        if str(user_id) not in ADMIN_IDS:
            return
        rows = list_users()
        if not rows:
            text = "👥 <b>DAFTAR PENGGUNA</b>\n\nBelum ada pengguna terdaftar."
        else:
            items = []
            for row in rows:
                perms = [PERMISSIONS[p] for p in PERMISSIONS if p in row["permissions"].split(",")]
                items.append(f"👤 <code>{html.escape(row['user_id'])}</code>\nRole: {html.escape(row['role'])}\nAkses: {html.escape(', '.join(perms) or 'Tidak ada')}")
            text = "👥 <b>DAFTAR PENGGUNA</b>\n\n" + "\n\n".join(items)
        send_message(chat_id, text, [[{"text": "🔙 KEMBALI", "callback_data": "menu:settings"}]])
        return

    if data == "settings:permissions":
        if str(user_id) not in ADMIN_IDS:
            return
        rows = list_users()
        if not rows:
            send_message(chat_id, "Belum ada pengguna. Tambahkan pengguna terlebih dahulu.", [[{"text": "🔙 KEMBALI", "callback_data": "menu:settings"}]])
            return
        keyboard = [[{"text": f"👤 {row['user_id']}", "callback_data": f"settings:user:{row['user_id']}"}] for row in rows]
        keyboard.append([{"text": "🔙 KEMBALI", "callback_data": "menu:settings"}])
        send_message(chat_id, "🔐 <b>KELOLA HAK AKSES</b>\n\nPilih pengguna:", keyboard)
        return

    if data.startswith("settings:user:"):
        if str(user_id) not in ADMIN_IDS:
            return
        target = data.split(":", 2)[2]
        row = get_user(target)
        if not row:
            send_message(chat_id, "Pengguna tidak ditemukan.")
            return
        send_message(chat_id, f"🔐 <b>HAK AKSES</b>\n\nUser ID: <code>{html.escape(target)}</code>\nRole: <b>{html.escape(row['role'])}</b>\n\nTekan tombol untuk mengaktifkan/nonaktifkan akses.", user_permission_keyboard(target))
        return

    if data.startswith("perm:"):
        if str(user_id) not in ADMIN_IDS:
            return
        parts = data.split(":")
        if len(parts) != 3 or parts[2] not in PERMISSIONS:
            return
        target, permission = parts[1], parts[2]
        row = get_user(target)
        if not row:
            return
        active = permission in {p for p in row["permissions"].split(",") if p}
        set_permission(target, permission, not active)
        send_message(chat_id, f"🔐 Akses <b>{html.escape(PERMISSIONS[permission])}</b> untuk <code>{html.escape(target)}</code> {'diaktifkan' if not active else 'dinonaktifkan'}.", user_permission_keyboard(target))
        return

    if data == "settings:revoke":
        if str(user_id) not in ADMIN_IDS:
            return
        rows = list_users()
        keyboard = [[{"text": f"🚫 {row['user_id']}", "callback_data": f"revoke:{row['user_id']}"}] for row in rows]
        keyboard.append([{"text": "🔙 KEMBALI", "callback_data": "menu:settings"}])
        send_message(chat_id, "🚫 <b>CABUT AKSES</b>\n\nPilih pengguna:", keyboard)
        return

    if data.startswith("revoke:"):
        if str(user_id) not in ADMIN_IDS:
            return
        target = data.split(":", 1)[1]
        remove_user(target)
        send_message(chat_id, f"✅ Akses untuk <code>{html.escape(target)}</code> telah dicabut.", settings_keyboard())
        return

    if data == "settings:cancel":
        _pending_admin.pop(user_id, None)
        send_message(chat_id, "Dibatalkan.", settings_keyboard())
        return

    if data == "menu:ai":
        if not has_permission(user_id, "ai"):
            send_message(chat_id, "⛔ Anda tidak memiliki akses AI Analysis.")
            return
        send_message(chat_id, "🧠 <b>AI ANALYSIS</b>\n\nFitur AI siap dikembangkan.", [[{"text": "🔙 KEMBALI", "callback_data": "menu:home"}]])
        return

    if data == "menu:history":
        if not has_permission(user_id, "history"):
            send_message(chat_id, "⛔ Anda tidak memiliki akses Riwayat.")
            return
        send_message(chat_id, "📚 <b>RIWAYAT</b>\n\nRiwayat request dapat ditampilkan di sini.", [[{"text": "🔙 KEMBALI", "callback_data": "menu:home"}]])
        return

    if data == "menu:tools":
        if not has_permission(user_id, "tools"):
            send_message(chat_id, "⛔ Anda tidak memiliki akses Tools.")
            return
        send_message(chat_id, "🧰 <b>ALL TOOLS</b>\n\nPilih tool yang diizinkan admin.", [[{"text": "🔎 PENCARIAN", "callback_data": "tool:search"}], [{"text": "🔙 KEMBALI", "callback_data": "menu:home"}]])
        return

    if data == "tool:search":
        if not has_permission(user_id, "search"):
            send_message(chat_id, "⛔ Anda tidak memiliki akses Pencarian.")
            return
        send_message(chat_id, "🔎 Gunakan perintah <code>/cek ...</code> untuk pencarian.", [[{"text": "🔙 KEMBALI", "callback_data": "menu:home"}]])


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

    callback = update.get("callback_query")
    if callback:
        handle_callback(callback)
        return jsonify({"ok": True})

    message = update.get("message") or {}
    chat = message.get("chat") or {}
    user = message.get("from") or {}
    chat_id = chat.get("id")
    user_id = user.get("id", chat_id)
    text = (message.get("text") or "").strip()

    if not chat_id or not text:
        return jsonify({"ok": True})

    if str(user_id) in ADMIN_IDS and _pending_admin.get(user_id) == "add":
        if not re.fullmatch(r"\d{3,20}", text):
            send_message(chat_id, "❌ User ID tidak valid. Kirim angka Telegram User ID.")
            return jsonify({"ok": True})
        ensure_user(text)
        _pending_admin.pop(user_id, None)
        send_message(chat_id, f"✅ Pengguna <code>{html.escape(text)}</code> ditambahkan.\n\nSekarang pilih hak akses:", [[{"text": "🔐 KELOLA HAK AKSES", "callback_data": "settings:permissions"}], [{"text": "🔙 PENGATURAN", "callback_data": "menu:settings"}]])
        return jsonify({"ok": True})

    if text.startswith("/start") or text == "/menu":
        ensure_user(user_id)
        send_message(chat_id, welcome_text(), main_keyboard(user_id))
        return jsonify({"ok": True})

    if text == "/id":
        send_message(chat_id, f"🆔 Telegram User ID Anda: <code>{html.escape(str(user_id))}</code>")
        return jsonify({"ok": True})

    if text.startswith("/settings"):
        if str(user_id) not in ADMIN_IDS:
            send_message(chat_id, "⛔ Akses admin diperlukan.")
            return jsonify({"ok": True})
        send_message(chat_id, "⚙️ <b>PENGATURAN AKSES</b>\n\nKelola pengguna dan hak akses.", settings_keyboard())
        return jsonify({"ok": True})

    if text.startswith("/cek"):
        if not has_permission(user_id, "search"):
            send_message(chat_id, "⛔ Anda belum memiliki akses Pencarian. Hubungi admin untuk mendapatkan akses.")
            return jsonify({"ok": True})

        query = text[4:].strip()
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

    send_message(chat_id, "Gunakan <code>/menu</code> untuk membuka menu utama atau <code>/id</code> untuk melihat Telegram User ID.", main_keyboard(user_id))
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
