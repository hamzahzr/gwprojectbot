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
ADMIN_IDS = {x.strip() for x in os.getenv("ADMIN_IDS", "654083689").split(",") if x.strip()}
MAX_QUERY_LENGTH = int(os.getenv("MAX_QUERY_LENGTH", "120"))
API_LIMIT = min(max(int(os.getenv("API_LIMIT", "100")), 100), 10000)
RATE_LIMIT_SECONDS = float(os.getenv("RATE_LIMIT_SECONDS", "3"))
DB_PATH = os.path.join(os.path.dirname(__file__), "gwproject.db")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
_last_request = {}
_pending_input = {}
_rate_lock = Lock()
_db_lock = Lock()

PERMISSIONS = ("search", "ai", "history", "tools")


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
            conn.execute("INSERT INTO users(user_id, role, permissions) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET role='admin'", (uid, "admin", ",".join(PERMISSIONS)))
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
    return permission in [p for p in row["permissions"].split(",") if p]


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


def edit_message(chat_id, message_id, text, markup=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if markup is not None:
        payload["reply_markup"] = markup
    return telegram("editMessageText", payload)


def answer_callback(callback_id, text=""):
    telegram("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


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
        [button("🏦 CEK REKENING", "rekening")],
        [button("💳 CEK EWALLET", "ewallet")],
        [button("🧠 AI ANALYSIS", "ai")],
        [button("🔙 KEMBALI", "home")],
    ]}


def settings_menu():
    return {"inline_keyboard": [
        [button("👥 DAFTAR PENGGUNA", "users")],
        [button("➕ / GRANT AKSES", "grant_help")],
        [button("🚫 / REVOKE AKSES", "revoke_help")],
        [button("👑 / ROLE", "role_help")],
        [button("🔙 KEMBALI", "home")],
    ]}


def detect_query_type(query):
    value = query.strip()
    if re.fullmatch(r"\+?[0-9][0-9 .()-]{7,19}", value): return "Nomor HP"
    if re.fullmatch(r"[0-9]{16}", value): return "NIK"
    if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value): return "Email"
    if re.fullmatch(r"@?[A-Za-z0-9_.-]{3,64}", value): return "Username"
    return "Nama"


def allowed_query(query):
    if not query or len(query) > MAX_QUERY_LENGTH: return False
    if any(ch in query for ch in ["\n", "\r", "<", ">"]): return False
    return bool(re.fullmatch(r"[A-Za-z0-9@+_.()\- /]{3,120}", query))


def rate_allowed(user_id):
    now = time.monotonic()
    with _rate_lock:
        previous = _last_request.get(user_id, 0)
        if now - previous < RATE_LIMIT_SECONDS: return False
        _last_request[user_id] = now
    return True


def query_api(query):
    payload = {"token": API_TOKEN, "request": query, "limit": API_LIMIT, "lang": os.getenv("API_LANG", "en"), "type": "json"}
    response = requests.post(API_URL, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()


def _pretty_key(key):
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(key)).replace("_", " ").replace("-", " ")
    return " ".join(text.split()).title()


def _compact_value(value):
    if isinstance(value, dict):
        return " | ".join(f"{_pretty_key(k)}: {v}" for k, v in value.items() if v not in (None, "", [], {}))
    if isinstance(value, list): return ", ".join(str(v) for v in value)
    return value


def _plain_value(value):
    if isinstance(value, (dict, list)): value = _compact_value(value)
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def _format_record(record, number):
    lines = [f"📄 RECORD #{number}", "────────────────────────────────"]
    if isinstance(record, dict):
        fields = [(_pretty_key(k), _plain_value(v)) for k, v in record.items() if v not in (None, "", [], {})]
        width = min(max((len(k) for k, _ in fields), default=10), 22)
        for key, value in fields: lines.append(f"{key:<{width}} : {value}")
    else: lines.append(f"Value{' ':<15}: {_plain_value(record)}")
    return "\n".join(lines)


def format_simple_result(query, result):
    if not isinstance(result, dict): return ["❌ Data tidak dapat ditampilkan."]
    if result.get("Error code"): return ["❌ Pencarian gagal. Silakan coba lagi."]
    listing = result.get("List")
    if not isinstance(listing, dict): return ["<b>GWPROJECT RESULT</b>\n\nTidak ada data ditemukan."]
    sources, total = [], 0
    for source_name, source_data in listing.items():
        if str(source_name).lower() == "no results found": continue
        records = source_data if isinstance(source_data, list) else [source_data]
        records = [r for r in records if r not in (None, "", [], {})]
        if records: sources.append((str(source_name), records)); total += len(records)
    if not sources: return ["<b>GWPROJECT RESULT</b>\n\nTidak ada data ditemukan."]
    header = ("<b>╔══════════════════════════════════╗</b>\n<b>║          GWPROJECT RESULT        ║</b>\n<b>╚══════════════════════════════════╝</b>\n\n" + f"🔎 <b>QUERY</b>\n<code>{html.escape(detect_query_type(query))}  {html.escape(query)}</code>\n\n")
    chunks, current, record_no = [], header, 0
    for source_index, (source_name, records) in enumerate(sources, 1):
        block = f"📁 <b>SOURCE #{source_index}</b>\n<code>{html.escape(source_name)}</code>\n\n"
        if len(current) + len(block) > 3800 and current != header: chunks.append(current.rstrip()); current = ""
        current += block
        for record in records:
            record_no += 1
            block = f"<pre>{html.escape(_format_record(record, record_no))}</pre>\n\n"
            if len(current) + len(block) > 3800 and current: chunks.append(current.rstrip()); current = ""
            current += block
    summary = f"📊 <b>SUMMARY</b>\n────────────────────────────────\nSources : {len(sources)}\nRecords : {total}"
    if len(current) + len(summary) > 3900 and current: chunks.append(current.rstrip()); current = ""
    current += summary; chunks.append(current.rstrip())
    return chunks


def status_text(user_id):
    row = get_user(user_id)
    role = "ADMIN" if is_admin(user_id) else row["role"].upper()
    perms = "Semua akses" if role == "ADMIN" else (", ".join(row["permissions"].split(",")) or "Belum ada akses")
    return f"ℹ️ <b>STATUS GWPROJECT</b>\n\n👤 ID: <code>{user_id}</code>\n🛡️ Role: <b>{role}</b>\n🔐 Akses: <b>{html.escape(perms)}</b>"


def users_text():
    with _db_lock:
        conn = db(); rows = conn.execute("SELECT user_id, role, permissions FROM users ORDER BY rowid DESC LIMIT 30").fetchall(); conn.close()
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


def callback_handler(cb):
    callback_id = cb.get("id", "")
    data = cb.get("data", "")
    user = cb.get("from") or {}
    uid = user.get("id")
    message = cb.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    message_id = message.get("message_id")
    get_user(uid)
    try:
        answer_callback(callback_id)
        if data == "home":
            clear_pending(uid)
            edit_message(chat_id, message_id, "<b>🛰️ GW-PROJECT</b>\n\nPrivate operations console\n\nPilih layanan dari menu di bawah.", main_menu(uid))
        elif data == "tools":
            clear_pending(uid)
            edit_message(chat_id, message_id, "<b>🧰 ALL TOOLS</b>\n\nPilih layanan yang tersedia.", tools_menu(uid))
        elif data == "ai":
            clear_pending(uid)
            if not has_permission(uid, "ai"): edit_message(chat_id, message_id, "🔒 <b>AKSES DITOLAK</b>\n\nAnda belum mendapat akses AI Analysis.", {"inline_keyboard": [[button("🔙 KEMBALI", "tools")]]})
            else:
                set_pending(uid, "ai")
                edit_message(chat_id, message_id, "🧠 <b>AI ANALYSIS</b>\n\nSilakan kirim pertanyaan atau teks yang ingin dianalisis.", {"inline_keyboard": [[button("🔙 KEMBALI", "tools")]]})
        elif data == "search":
            clear_pending(uid)
            if not has_permission(uid, "search"): edit_message(chat_id, message_id, "🔒 <b>AKSES DITOLAK</b>\n\nAnda belum mendapat akses Pencarian.", {"inline_keyboard": [[button("🔙 KEMBALI", "tools")]]})
            else:
                set_pending(uid, "search")
                edit_message(chat_id, message_id, "🔎 <b>SEARCH</b>\n\nSilakan masukkan data yang ingin dicari.\nTidak perlu menggunakan command.", {"inline_keyboard": [[button("🔙 KEMBALI", "tools")]]})
        elif data == "username":
            clear_pending(uid)
            if not has_permission(uid, "search"): edit_message(chat_id, message_id, "🔒 <b>AKSES DITOLAK</b>\n\nAnda belum mendapat akses Cek Username.", {"inline_keyboard": [[button("🔙 KEMBALI", "tools")]]})
            else:
                set_pending(uid, "username")
                edit_message(chat_id, message_id, "👤 <b>CEK USERNAME</b>\n\nSilakan masukkan username yang ingin diperiksa.\nContoh: <code>@username</code>", {"inline_keyboard": [[button("🔙 KEMBALI", "tools")]]})
        elif data == "rekening":
            clear_pending(uid)
            set_pending(uid, "rekening")
            edit_message(chat_id, message_id, "🏦 <b>CEK REKENING</b>\n\nSilakan masukkan nomor rekening.\nAPI akan disambungkan setelah endpoint diberikan.", {"inline_keyboard": [[button("🔙 KEMBALI", "tools")]]})
        elif data == "ewallet":
            clear_pending(uid)
            set_pending(uid, "ewallet")
            edit_message(chat_id, message_id, "💳 <b>CEK EWALLET</b>\n\nSilakan masukkan nomor e-wallet.\nAPI akan disambungkan setelah endpoint diberikan.", {"inline_keyboard": [[button("🔙 KEMBALI", "tools")]]})
        elif data == "history":
            clear_pending(uid)
            if not has_permission(uid, "history"): edit_message(chat_id, message_id, "🔒 <b>AKSES DITOLAK</b>\n\nAnda belum mendapat akses Riwayat.", {"inline_keyboard": [[button("🔙 KEMBALI", "home")]]})
            else: edit_message(chat_id, message_id, "📚 <b>RIWAYAT</b>\n\nAktivitas Anda tercatat untuk audit. Detail pencarian sensitif tidak ditampilkan di menu riwayat.", {"inline_keyboard": [[button("🔙 KEMBALI", "home")]]})
        elif data == "settings":
            clear_pending(uid)
            if not is_admin(uid): edit_message(chat_id, message_id, "🔒 Akses admin diperlukan.", {"inline_keyboard": [[button("🔙 KEMBALI", "home")]]})
            else: edit_message(chat_id, message_id, "⚙️ <b>PENGATURAN AKSES</b>\n\nKelola pengguna dan izin dari menu ini.\n\nContoh:\n<code>/grant 123456789 search</code>\n<code>/revoke 123456789 search</code>\n<code>/role 123456789 operator</code>", settings_menu())
        elif data == "users":
            if not is_admin(uid): return
            edit_message(chat_id, message_id, users_text(), {"inline_keyboard": [[button("🔙 KEMBALI", "settings")]]})
        elif data == "grant_help":
            edit_message(chat_id, message_id, "➕ <b>GRANT AKSES</b>\n\n<code>/grant USER_ID search</code>\n<code>/grant USER_ID ai</code>\n<code>/grant USER_ID history</code>\n<code>/grant USER_ID tools</code>", {"inline_keyboard": [[button("🔙 KEMBALI", "settings")]]})
        elif data == "revoke_help":
            edit_message(chat_id, message_id, "🚫 <b>REVOKE AKSES</b>\n\n<code>/revoke USER_ID search</code>\n<code>/revoke USER_ID ai</code>\n<code>/revoke USER_ID history</code>\n<code>/revoke USER_ID tools</code>", {"inline_keyboard": [[button("🔙 KEMBALI", "settings")]]})
        elif data == "role_help":
            edit_message(chat_id, message_id, "👑 <b>ROLE</b>\n\n<code>/role USER_ID admin</code>\n<code>/role USER_ID operator</code>\n<code>/role USER_ID user</code>", {"inline_keyboard": [[button("🔙 KEMBALI", "settings")]]})
        elif data == "status":
            clear_pending(uid)
            edit_message(chat_id, message_id, status_text(uid), {"inline_keyboard": [[button("🔙 KEMBALI", "home")]]})
        elif data == "denied":
            answer_callback(callback_id, "Akses belum diberikan")
    except requests.RequestException:
        pass


@app.get("/")
def home():
    return jsonify({"status": "ok", "service": "GWProject Telegram Bot"})


@app.post("/webhook")
def webhook():
    if WEBHOOK_SECRET and request.headers.get("X-Telegram-Bot-Api-Secret-Token", "") != WEBHOOK_SECRET:
        return jsonify({"ok": False}), 403
    update = request.get_json(silent=True) or {}
    if update.get("callback_query"):
        callback_handler(update["callback_query"])
        return jsonify({"ok": True})

    message = update.get("message") or {}
    chat = message.get("chat") or {}
    user = message.get("from") or {}
    chat_id = chat.get("id")
    user_id = user.get("id", chat_id)
    text = (message.get("text") or "").strip()
    if not chat_id or not text: return jsonify({"ok": True})
    get_user(user_id)

    if text == "/id":
        send_message(chat_id, f"🆔 Telegram User ID Anda:\n\n<code>{user_id}</code>\n\nRole: <b>{'ADMIN' if is_admin(user_id) else get_user(user_id)['role'].upper()}</b>")
        return jsonify({"ok": True})

    if text.startswith("/start"):
        clear_pending(user_id)
        send_message(chat_id, "<b>🛰️ GW-PROJECT</b>\n\nPrivate operations console\n\nPilih layanan dari menu di bawah.\nSetiap request dicatat untuk audit dan akses dikontrol berdasarkan role/izin.", main_menu(user_id))
        return jsonify({"ok": True})

    if text.startswith("/grant ") or text.startswith("/revoke "):
        clear_pending(user_id)
        if not is_admin(user_id):
            send_message(chat_id, "🔒 Akses admin diperlukan."); return jsonify({"ok": True})
        parts = text.split()
        if len(parts) != 3 or parts[2] not in PERMISSIONS:
            send_message(chat_id, "Format: <code>/grant USER_ID search</code>\nAkses: search, ai, history, tools"); return jsonify({"ok": True})
        target, perm = parts[1], parts[2]
        get_user(target); set_permission(target, perm, text.startswith("/grant"))
        send_message(chat_id, f"{'✅ Akses diberikan' if text.startswith('/grant') else '🚫 Akses dicabut'}\nUser: <code>{html.escape(target)}</code>\nAkses: <b>{perm}</b>")
        return jsonify({"ok": True})

    if text.startswith("/role "):
        clear_pending(user_id)
        if not is_admin(user_id): send_message(chat_id, "🔒 Akses admin diperlukan."); return jsonify({"ok": True})
        parts = text.split()
        if len(parts) != 3 or parts[2] not in ("admin", "operator", "user"):
            send_message(chat_id, "Format: <code>/role USER_ID admin|operator|user</code>"); return jsonify({"ok": True})
        target, role = parts[1], parts[2]
        get_user(target); set_role(target, role)
        send_message(chat_id, f"✅ Role <b>{role.upper()}</b> diberikan ke <code>{html.escape(target)}</code>")
        return jsonify({"ok": True})

    if text.startswith("/users"):
        clear_pending(user_id)
        if is_admin(user_id): send_message(chat_id, users_text())
        else: send_message(chat_id, "🔒 Akses admin diperlukan.")
        return jsonify({"ok": True})

    pending = _pending_input.get(str(user_id))
    if pending in ("search", "username"):
        if not has_permission(user_id, "search"):
            clear_pending(user_id)
            send_message(chat_id, "🔒 <b>Akses Pencarian belum diberikan.</b>\nHubungi admin untuk mendapatkan izin.")
            return jsonify({"ok": True})
        query = text
        if pending == "username" and query.startswith("@"):
            query = query[1:]
        if not allowed_query(query):
            send_message(chat_id, "❌ Format input tidak valid. Silakan kirim data yang benar.")
            return jsonify({"ok": True})
        if not rate_allowed(user_id):
            send_message(chat_id, "⏱️ Tunggu beberapa detik sebelum pencarian berikutnya.")
            return jsonify({"ok": True})
        clear_pending(user_id)
        audit(user_id, "username_search" if pending == "username" else "search")
        send_message(chat_id, "🔎 <b>Mencari...</b>")
        try:
            result = query_api(query)
            for chunk in format_simple_result(query, result): send_message(chat_id, chunk)
        except requests.RequestException: send_message(chat_id, "❌ Server tidak dapat dihubungi.")
        except (ValueError, TypeError): send_message(chat_id, "❌ Respons server tidak valid.")
        except Exception: send_message(chat_id, "❌ Terjadi kesalahan. Silakan coba lagi.")
        return jsonify({"ok": True})

    if text.startswith("/cek"):
        if not has_permission(user_id, "search"):
            send_message(chat_id, "🔒 <b>Akses Pencarian belum diberikan.</b>\nHubungi admin untuk mendapatkan izin."); return jsonify({"ok": True})
        query = text[4:].strip()
        if not allowed_query(query): send_message(chat_id, "❌ Format pencarian tidak valid."); return jsonify({"ok": True})
        if not rate_allowed(user_id): send_message(chat_id, "⏱️ Tunggu beberapa detik sebelum pencarian berikutnya."); return jsonify({"ok": True})
        audit(user_id, "search")
        send_message(chat_id, "🔎 <b>Mencari...</b>")
        try:
            result = query_api(query)
            for chunk in format_simple_result(query, result): send_message(chat_id, chunk)
        except requests.RequestException: send_message(chat_id, "❌ Server tidak dapat dihubungi.")
        except (ValueError, TypeError): send_message(chat_id, "❌ Respons server tidak valid.")
        except Exception: send_message(chat_id, "❌ Terjadi kesalahan. Silakan coba lagi.")
        return jsonify({"ok": True})

    send_message(chat_id, "Gunakan <code>/start</code> untuk membuka menu.", main_menu(user_id))
    return jsonify({"ok": True})


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))