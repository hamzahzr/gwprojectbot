import html
import os
import re
import sqlite3
import time
from threading import Lock

import requests
from flask import Flask, jsonify, request

from output_formatter import format_error, format_tool_output
from tiktok_api import query_tiktok
from username_api import query_username_api

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
ADMIN_IDS = {x.strip() for x in os.getenv("ADMIN_IDS", "654083689").split(",") if x.strip()}
DB_PATH = os.path.join(os.path.dirname(__file__), "gwproject.db")
RATE_LIMIT_SECONDS = float(os.getenv("RATE_LIMIT_SECONDS", "3"))

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
_last_request = {}
_pending_input = {}
_rate_lock = Lock()
_db_lock = Lock()

PERMISSIONS = ("search", "ai", "username", "rekening", "ewallet", "tiktok", "nopol", "tools")


def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _db_lock:
        conn = db()
        conn.execute("CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, role TEXT NOT NULL DEFAULT 'user', permissions TEXT NOT NULL DEFAULT '')")
        conn.execute("CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, action TEXT, created_at INTEGER)")
        for uid in ADMIN_IDS:
            conn.execute(
                "INSERT INTO users(user_id, role, permissions) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET role='admin', permissions=?",
                (uid, "admin", ",".join(PERMISSIONS), ",".join(PERMISSIONS)),
            )
        conn.commit()
        conn.close()


def get_user(user_id):
    uid = str(user_id)
    with _db_lock:
        conn = db()
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        if not row:
            conn.execute("INSERT INTO users(user_id, role, permissions) VALUES(?,?,?)", (uid, "user", ""))
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        conn.close()
    return row


def is_admin(user_id):
    return str(user_id) in ADMIN_IDS or get_user(user_id)["role"] == "admin"


def has_permission(user_id, permission):
    if is_admin(user_id):
        return True
    row = get_user(user_id)
    return permission in {p for p in row["permissions"].split(",") if p}


def set_permission(user_id, permission, enabled):
    uid = str(user_id)
    row = get_user(uid)
    perms = {p for p in row["permissions"].split(",") if p}
    if enabled:
        perms.add(permission)
    else:
        perms.discard(permission)
    with _db_lock:
        conn = db()
        conn.execute("UPDATE users SET permissions=? WHERE user_id=?", (",".join(sorted(perms)), uid))
        conn.commit()
        conn.close()


def set_role(user_id, role):
    uid = str(user_id)
    with _db_lock:
        conn = db()
        conn.execute("UPDATE users SET role=? WHERE user_id=?", (role, uid))
        conn.commit()
        conn.close()


def audit(user_id, action):
    with _db_lock:
        conn = db()
        conn.execute("INSERT INTO audit(user_id, action, created_at) VALUES(?,?,?)", (str(user_id), action, int(time.time())))
        conn.commit()
        conn.close()


def telegram(method, payload):
    response = requests.post(f"{TELEGRAM_API}/{method}", json=payload, timeout=30)
    response.raise_for_status()
    return response.json()


def send_message(chat_id, text, markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if markup:
        payload["reply_markup"] = markup
    return telegram("sendMessage", payload)


def send_long_message(chat_id, text, limit=3900):
    if len(text) <= limit:
        return [send_message(chat_id, text)]
    chunks = []
    current = ""
    for line in text.splitlines():
        candidate = line if not current else current + "\n" + line
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
            while len(line) > limit:
                chunks.append(line[:limit])
                line = line[limit:]
            current = line
    if current:
        chunks.append(current)
    return [send_message(chat_id, chunk) for chunk in chunks]


def send_tool_result(chat_id, tool_name, result):
    text = format_tool_output(tool_name, result, title="GW-PROJECT RESULT")
    return send_long_message(chat_id, text)


def send_tool_error(chat_id, tool_name, error):
    text = format_error(tool_name, str(error))
    return send_long_message(chat_id, text)


def edit_message(chat_id, message_id, text, markup=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if markup is not None:
        payload["reply_markup"] = markup
    return telegram("editMessageText", payload)


def answer_callback(callback_id, text=""):
    return telegram("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


def button(text, data):
    return {"text": text, "callback_data": data}


def main_menu(user_id):
    rows = [
        [button("🧰 ALL TOOLS", "tools"), button("🧠 AI ANALYSIS", "ai")],
        [button("ℹ️ STATUS", "status")],
    ]
    if is_admin(user_id):
        rows.append([button("⚙️ PENGATURAN", "settings")])
    return {"inline_keyboard": rows}


def tools_menu(user_id):
    if not has_permission(user_id, "tools"):
        return {"inline_keyboard": [[button("🔒 AKSES DITOLAK", "denied")], [button("🔙 KEMBALI", "home")]]}
    return {"inline_keyboard": [
        [button("🔎 SEARCH", "search")],
        [button("👤 CEK USERNAME", "username")],
        [button("🎵 TIKTOK SCRAPER", "tiktok")],
        [button("🏦 CEK REKENING", "rekening")],
        [button("💳 CEK eWallet", "ewallet")],
        [button("🚗 CEK NOPOL", "nopol")],
        [button("🔙 KEMBALI", "home")],
    ]}


def settings_menu():
    return {"inline_keyboard": [
        [button("👥 DAFTAR PENGGUNA", "users")],
        [button("➕ GRANT AKSES", "grant_help")],
        [button("🚫 REVOKE AKSES", "revoke_help")],
        [button("👑 ROLE", "role_help")],
        [button("🔙 KEMBALI", "home")],
    ]}


def status_text(user_id):
    row = get_user(user_id)
    role = "ADMIN" if is_admin(user_id) else row["role"].upper()
    perms = "Semua akses" if role == "ADMIN" else (", ".join(row["permissions"].split(",")) or "Belum ada akses")
    return f"ℹ️ <b>STATUS GWPROJECT</b>\n\n👤 ID: <code>{html.escape(str(user_id))}</code>\n🛡️ Role: <b>{role}</b>\n🔐 Akses: <b>{html.escape(perms)}</b>"


def users_text():
    with _db_lock:
        conn = db()
        rows = conn.execute("SELECT user_id, role, permissions FROM users ORDER BY rowid DESC LIMIT 30").fetchall()
        conn.close()
    lines = ["👥 <b>DAFTAR PENGGUNA</b>", ""]
    for row in rows:
        role = "ADMIN" if row["role"] == "admin" else row["role"].upper()
        perms = "semua" if role == "ADMIN" else (row["permissions"] or "-")
        lines.append(f"<code>{html.escape(row['user_id'])}</code> · <b>{role}</b> · {html.escape(perms)}")
    return "\n".join(lines)


def set_pending(user_id, action):
    _pending_input[str(user_id)] = action


def clear_pending(user_id):
    _pending_input.pop(str(user_id), None)


def rate_allowed(user_id):
    now = time.monotonic()
    with _rate_lock:
        previous = _last_request.get(str(user_id), 0)
        if now - previous < RATE_LIMIT_SECONDS:
            return False
        _last_request[str(user_id)] = now
    return True


def valid_username(value):
    return bool(re.fullmatch(r"@?[A-Za-z0-9._-]{1,50}", value.strip()))


def configured_api(name):
    url = os.getenv(f"{name}_API_URL", "").strip()
    token = os.getenv(f"{name}_API_TOKEN", "").strip()
    return url, token


def call_configured_api(name, value):
    url, token = configured_api(name)
    if not url:
        raise RuntimeError(f"{name}_API_URL belum dikonfigurasi")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.post(url, json={"input": value}, headers=headers, timeout=60)
    response.raise_for_status()
    return response.json()


def call_nopol_api(value):
    url = os.getenv("NOPOL_API_URL", "https://neosint.online/v1/cek-nopol").strip()
    token = os.getenv("NOPOL_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("NOPOL_API_TOKEN belum dikonfigurasi")
    headers = {"Accept": "application/json", "X-API-Key": token}
    response = requests.get(url, params={"nopol": value.strip()}, headers=headers, timeout=60)
    response.raise_for_status()
    return response.json()


def call_search_api(value):
    url = os.getenv("SEARCH_API_URL", "https://leakosintapi.com/").strip()
    token = os.getenv("SEARCH_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("SEARCH_API_TOKEN belum dikonfigurasi")
    try:
        limit = int(os.getenv("SEARCH_API_LIMIT", "100"))
    except ValueError:
        limit = 100
    limit = max(100, min(limit, 10000))
    payload = {
        "token": token,
        "request": value,
        "limit": limit,
        "lang": os.getenv("SEARCH_API_LANG", "en").strip() or "en",
        "type": "json",
    }
    response = requests.post(url, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()


def callback_handler(cb):
    callback_id = cb.get("id", "")
    data = cb.get("data", "")
    uid = (cb.get("from") or {}).get("id")
    message = cb.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    message_id = message.get("message_id")
    get_user(uid)
    try:
        answer_callback(callback_id)
        if data == "home":
            clear_pending(uid)
            edit_message(chat_id, message_id, "<b>🛰️ GW-PROJECT</b>\n\nPilih layanan dari menu di bawah.", main_menu(uid))
        elif data == "tools":
            clear_pending(uid)
            edit_message(chat_id, message_id, "<b>🧰 ALL TOOLS</b>\n\nPilih layanan yang tersedia.", tools_menu(uid))
        elif data in {"search", "username", "tiktok", "rekening", "ewallet", "nopol", "ai"}:
            clear_pending(uid)
            if not has_permission(uid, data):
                edit_message(chat_id, message_id, "🔒 <b>AKSES DITOLAK</b>\n\nAnda belum mendapat akses untuk tool ini.", {"inline_keyboard": [[button("🔙 KEMBALI", "tools")]]})
                return
            set_pending(uid, data)
            prompts = {
                "search": "🔎 <b>SEARCH</b>\n\nLangsung kirim target pencarian:\n<code>email@domain.com</code>\n<code>6281234567890</code>\n<code>username123</code>\n<code>Nama Lengkap</code>\n<code>B1234XYZ</code>\n<code>3201234567890123</code>\n<code>192.168.1.1</code>\n<code>example.com</code>",
                "username": "👤 <b>CEK USERNAME</b>\n\nSilakan masukkan username.\nContoh: <code>@username</code>",
                "tiktok": "🎵 <b>TIKTOK SCRAPER</b>\n\nKirim URL profil/video TikTok.",
                "rekening": "🏦 <b>CEK REKENING</b>\n\nMasukkan data yang ingin diperiksa.",
                "ewallet": "💳 <b>CEK eWallet</b>\n\nMasukkan data yang ingin diperiksa.",
                "nopol": "🚗 <b>CEK NOPOL</b>\n\nMasukkan nomor polisi kendaraan.\nContoh: <code>B1234XYZ</code>",
                "ai": "🧠 <b>AI ANALYSIS</b>\n\nMasukkan teks/data untuk dianalisis.",
            }
            edit_message(chat_id, message_id, prompts[data], {"inline_keyboard": [[button("🔙 KEMBALI", "tools")]]})
        elif data == "status":
            clear_pending(uid)
            edit_message(chat_id, message_id, status_text(uid), {"inline_keyboard": [[button("🔙 KEMBALI", "home")]]})
        elif data == "settings":
            clear_pending(uid)
            if not is_admin(uid):
                edit_message(chat_id, message_id, "🔒 <b>AKSES DITOLAK</b>", {"inline_keyboard": [[button("🔙 KEMBALI", "home")]]})
                return
            edit_message(chat_id, message_id, "⚙️ <b>PENGATURAN</b>\n\nPilih administrasi yang ingin dikelola.", settings_menu())
        elif data == "users":
            clear_pending(uid)
            if not is_admin(uid):
                edit_message(chat_id, message_id, "🔒 <b>AKSES DITOLAK</b>", {"inline_keyboard": [[button("🔙 KEMBALI", "home")]]})
                return
            edit_message(chat_id, message_id, users_text(), {"inline_keyboard": [[button("🔙 KEMBALI", "settings")]]})
        elif data == "grant_help":
            clear_pending(uid)
            edit_message(chat_id, message_id, "➕ <b>GRANT AKSES</b>\n\nGunakan command:\n<code>/grant USER_ID PERMISSION</code>\n\nPermission: search, ai, username, rekening, ewallet, tiktok, nopol, tools", {"inline_keyboard": [[button("🔙 KEMBALI", "settings")]]})
        elif data == "revoke_help":
            clear_pending(uid)
            edit_message(chat_id, message_id, "🚫 <b>REVOKE AKSES</b>\n\nGunakan command:\n<code>/revoke USER_ID PERMISSION</code>", {"inline_keyboard": [[button("🔙 KEMBALI", "settings")]]})
        elif data == "role_help":
            clear_pending(uid)
            edit_message(chat_id, message_id, "👑 <b>ROLE</b>\n\nGunakan command:\n<code>/role USER_ID admin</code>\natau\n<code>/role USER_ID user</code>", {"inline_keyboard": [[button("🔙 KEMBALI", "settings")]]})
        elif data == "denied":
            answer_callback(callback_id, "Akses belum diberikan")
        else:
            clear_pending(uid)
    except requests.RequestException:
        pass


def handle_message(message):
    user = message.get("from") or {}
    user_id = user.get("id")
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    if user_id is None or chat_id is None:
        return
    get_user(user_id)
    if text.startswith("/start"):
        clear_pending(user_id)
        send_message(chat_id, "<b>🛰️ GW-PROJECT</b>\n\nSelamat datang. Pilih layanan dari menu di bawah.", main_menu(user_id))
        return
    if text == "/id":
        send_message(chat_id, f"🆔 Telegram ID Anda: <code>{html.escape(str(user_id))}</code>")
        return
    if text.startswith("/grant"):
        if not is_admin(user_id):
            send_message(chat_id, "🔒 Akses admin diperlukan.")
            return
        parts = text.split()
        if len(parts) != 3 or parts[2] not in PERMISSIONS:
            send_message(chat_id, "Format: <code>/grant USER_ID PERMISSION</code>")
            return
        target, permission = parts[1], parts[2]
        get_user(target)
        set_permission(target, permission, True)
        audit(user_id, f"grant:{target}:{permission}")
        send_message(chat_id, f"✅ Akses <b>{html.escape(permission)}</b> diberikan ke <code>{html.escape(target)}</code>.")
        return
    if text.startswith("/revoke"):
        if not is_admin(user_id):
            send_message(chat_id, "🔒 Akses admin diperlukan.")
            return
        parts = text.split()
        if len(parts) != 3 or parts[2] not in PERMISSIONS:
            send_message(chat_id, "Format: <code>/revoke USER_ID PERMISSION</code>")
            return
        target, permission = parts[1], parts[2]
        get_user(target)
        set_permission(target, permission, False)
        audit(user_id, f"revoke:{target}:{permission}")
        send_message(chat_id, f"🚫 Akses <b>{html.escape(permission)}</b> dicabut dari <code>{html.escape(target)}</code>.")
        return
    if text.startswith("/role"):
        if not is_admin(user_id):
            send_message(chat_id, "🔒 Akses admin diperlukan.")
            return
        parts = text.split()
        if len(parts) != 3 or parts[2] not in {"admin", "operator", "user"}:
            send_message(chat_id, "Format: <code>/role USER_ID admin|operator|user</code>")
            return
        target, role = parts[1], parts[2]
        get_user(target)
        set_role(target, role)
        audit(user_id, f"role:{target}:{role}")
        send_message(chat_id, f"👑 Role <b>{html.escape(role)}</b> diterapkan ke <code>{html.escape(target)}</code>.")
        return
    if text == "/users":
        if not is_admin(user_id):
            send_message(chat_id, "🔒 Akses admin diperlukan.")
            return
        send_message(chat_id, users_text())
        return
    pending = _pending_input.get(str(user_id))
    if pending:
        clear_pending(user_id)
        if not rate_allowed(user_id):
            send_message(chat_id, "⏳ Tunggu sebentar sebelum melakukan request berikutnya.")
            return
        audit(user_id, f"query:{pending}")
        try:
            if pending == "search":
                result = call_search_api(text)
                send_tool_result(chat_id, "SEARCH", result)
            elif pending == "username":
                if not valid_username(text):
                    send_message(chat_id, "❌ Format username tidak valid.")
                    return
                result = query_username_api(text)
                send_tool_result(chat_id, "CEK USERNAME", result)
            elif pending == "tiktok":
                result = query_tiktok(text)
                send_tool_result(chat_id, "TIKTOK SCRAPER", result)
            elif pending == "nopol":
                result = call_nopol_api(text)
                send_tool_result(chat_id, "CEK NOPOL", result)
            else:
                name = {"rekening": "REKENING", "ewallet": "EWALLET", "ai": "AI"}[pending]
                result = call_configured_api(name, text)
                send_tool_result(chat_id, name, result)
        except requests.RequestException as exc:
            send_tool_error(chat_id, pending.upper(), f"Request API gagal: {exc}")
        except Exception as exc:
            send_tool_error(chat_id, pending.upper(), exc)
        return
    send_message(chat_id, "Gunakan /start untuk membuka menu.")


@app.get("/")
def health():
    return jsonify({"ok": True, "service": "gwprojectbot"})


@app.post("/webhook")
def webhook():
    if WEBHOOK_SECRET:
        supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if supplied != WEBHOOK_SECRET:
            return jsonify({"ok": False}), 403
    update = request.get_json(silent=True) or {}
    if "callback_query" in update:
        callback_handler(update["callback_query"])
    elif "message" in update:
        handle_message(update["message"])
    return jsonify({"ok": True})


with app.app_context():
    init_db()