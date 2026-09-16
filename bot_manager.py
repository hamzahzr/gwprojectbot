import hashlib
import hmac
import html
import os
import sqlite3
import time
from functools import wraps
from flask import Blueprint, jsonify, redirect, render_template_string, request, session, url_for

MANAGER_DB_PATH = os.path.join(os.path.dirname(__file__), "gwproject.db")
manager = Blueprint("manager", __name__, url_prefix="/manager")

LOGIN_USER = os.getenv("DASHBOARD_USERNAME", "admin").strip()
LOGIN_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "").strip()

CSS = """
:root{font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0b1020;color:#eef2ff}*{box-sizing:border-box}body{margin:0;background:linear-gradient(135deg,#080c17,#10172b);min-height:100vh}.wrap{max-width:1180px;margin:auto;padding:28px}.top{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:22px}.brand{font-size:24px;font-weight:800}.muted{color:#94a3b8}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.card{background:rgba(17,24,39,.88);border:1px solid #26324d;border-radius:16px;padding:18px;box-shadow:0 10px 35px rgba(0,0,0,.22)}.span{grid-column:span 2}.row{display:flex;gap:10px;flex-wrap:wrap}.kpi{font-size:30px;font-weight:800;margin-top:8px}.btn,.input{border:1px solid #334155;border-radius:10px;padding:10px 13px;background:#111827;color:#fff}.btn{cursor:pointer;text-decoration:none;display:inline-block}.btn.primary{background:#2563eb;border-color:#2563eb}.table{width:100%;border-collapse:collapse}.table th,.table td{padding:10px;border-bottom:1px solid #243047;text-align:left;font-size:14px}.nav{display:flex;gap:8px;flex-wrap:wrap}.nav a{color:#cbd5e1;text-decoration:none;padding:8px 10px;border-radius:8px}.login{max-width:420px;margin:10vh auto}.form{display:grid;gap:12px}.alert{padding:11px;border-radius:9px;background:#3f1d1d;color:#fecaca}.small{font-size:12px}@media(max-width:900px){.grid{grid-template-columns:repeat(2,1fr)}.span{grid-column:span 2}}@media(max-width:600px){.wrap{padding:14px}.grid{grid-template-columns:1fr}.span{grid-column:span 1}.top{align-items:flex-start;flex-direction:column}}
"""


def conn():
    database = sqlite3.connect(MANAGER_DB_PATH, timeout=10)
    database.row_factory = sqlite3.Row
    return database


def audit(user, action):
    with conn() as database:
        database.execute("CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, action TEXT, created_at INTEGER)")
        database.execute("INSERT INTO audit(user_id, action, created_at) VALUES(?,?,?)", (user, action, int(time.time())))


def logged_in(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if not session.get("manager_auth"):
            return redirect(url_for("manager.login", next=request.path))
        return function(*args, **kwargs)
    return wrapper


def layout(title, body):
    template = """
<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{{title}} · GW Project</title><style>{{css}}</style></head><body><div class='wrap'>
<div class='top'><div><div class='brand'>🛰️ GW-PROJECT BOT MANAGER</div><div class='muted'>Single-bot admin console</div></div><div class='nav'>{% if auth %}<a href='{{url_for("manager.dashboard")}}'>Dashboard</a><a href='{{url_for("manager.users")}}'>Users</a><a href='{{url_for("manager.config")}}'>Configuration</a><a href='{{url_for("manager.logs")}}'>Logs</a><a href='{{url_for("manager.logout")}}'>Logout</a>{% endif %}</div></div>
{{body|safe}}
</div></body></html>
"""
    return render_template_string(template, title=title, css=CSS, body=body, auth=bool(session.get("manager_auth")))


@manager.route("/login", methods=["GET", "POST"])
def login():
    error_message = ""
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if LOGIN_USER and LOGIN_PASSWORD and hmac.compare_digest(username, LOGIN_USER) and hmac.compare_digest(password, LOGIN_PASSWORD):
            session["manager_auth"] = True
            session["manager_user"] = username
            audit(username, "dashboard_login")
            return redirect(request.args.get("next") or url_for("manager.dashboard"))
        error_message = "Username atau password salah. Pastikan DASHBOARD_USERNAME dan DASHBOARD_PASSWORD diset di environment server."

    error_html = ""
    if error_message:
        error_html = "<div class='alert'>" + html.escape(error_message) + "</div>"

    body = (
        "<div class='login card'><h2>Login Bot Manager</h2>"
        + error_html
        + "<form class='form' method='post'>"
        + "<input class='input' name='username' placeholder='Username' autocomplete='username' required>"
        + "<input class='input' name='password' type='password' placeholder='Password' autocomplete='current-password' required>"
        + "<button class='btn primary' type='submit'>Login</button>"
        + "</form><p class='muted small'>Credentials dibaca dari environment server; tidak disimpan di GitHub.</p></div>"
    )
    return layout("Login", body)


@manager.get("/logout")
def logout():
    if session.get("manager_user"):
        audit(session.get("manager_user"), "dashboard_logout")
    session.clear()
    return redirect(url_for("manager.login"))


@manager.get("/")
@logged_in
def dashboard():
    with conn() as database:
        users_table = database.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
        audit_table = database.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='audit'").fetchone()
        users = database.execute("SELECT COUNT(*) n FROM users").fetchone()["n"] if users_table else 0
        admins = database.execute("SELECT COUNT(*) n FROM users WHERE role='admin'").fetchone()["n"] if users else 0
        audits = database.execute("SELECT COUNT(*) n FROM audit").fetchone()["n"] if audit_table else 0
    body = f"""
<div class='grid'>
<div class='card'><div class='muted'>Bot</div><div class='kpi'>ONLINE APP</div><div class='small muted'>/webhook</div></div>
<div class='card'><div class='muted'>Users</div><div class='kpi'>{users}</div></div>
<div class='card'><div class='muted'>Admins</div><div class='kpi'>{admins}</div></div>
<div class='card'><div class='muted'>Audit events</div><div class='kpi'>{audits}</div></div>
<div class='card span'><h3>Quick actions</h3><div class='row'><a class='btn primary' href='{url_for("manager.users")}'>Manage users</a><a class='btn' href='{url_for("manager.config")}'>Inspect configuration</a><a class='btn' href='{url_for("manager.logs")}'>View logs</a></div></div>
<div class='card span'><h3>Runtime</h3><table class='table'><tr><th>Application</th><td>GW Project Bot</td></tr><tr><th>Manager URL</th><td>/manager</td></tr><tr><th>Webhook URL</th><td>/webhook</td></tr><tr><th>Database</th><td>gwproject.db</td></tr></table></div>
</div>"""
    return layout("Dashboard", body)


@manager.get("/users")
@logged_in
def users():
    with conn() as database:
        table_exists = database.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
        rows = database.execute("SELECT user_id, role, permissions FROM users ORDER BY rowid DESC LIMIT 200").fetchall() if table_exists else []
    rows_html = ''.join("<tr><td class='mono'>" + html.escape(str(row['user_id'])) + "</td><td>" + html.escape(str(row['role'])) + "</td><td>" + html.escape(str(row['permissions'] or '-')) + "</td></tr>" for row in rows)
    body = "<div class='card'><h2>Users & Permissions</h2><p class='muted'>Tampilan baca-saja untuk mencegah perubahan akses yang tidak disengaja.</p><table class='table'><tr><th>User ID</th><th>Role</th><th>Permissions</th></tr>" + (rows_html or '<tr><td colspan=3>Belum ada pengguna.</td></tr>') + "</table></div>"
    return layout("Users", body)


@manager.get("/config")
@logged_in
def config():
    names = ["BOT_TOKEN", "WEBHOOK_SECRET", "ADMIN_IDS", "RATE_LIMIT_SECONDS", "SEARCH_API_URL", "SEARCH_API_TOKEN", "SEARCH_API_LIMIT", "SEARCH_API_LANG", "REKENING_API_URL", "REKENING_API_TOKEN", "EWALLET_API_URL", "EWALLET_API_TOKEN", "AI_API_URL", "AI_API_TOKEN", "TIKTOK_API_URL", "TIKTOK_API_TOKEN", "USERNAME_API_URL", "USERNAME_API_TOKEN", "NOPOL_API_URL", "NOPOL_API_TOKEN"]
    rows = []
    for name in names:
        value = os.getenv(name, "")
        shown = "[SET]" if value else "[NOT SET]"
        if name.endswith("_URL") or name in {"ADMIN_IDS", "RATE_LIMIT_SECONDS", "SEARCH_API_LIMIT", "SEARCH_API_LANG"}:
            shown = html.escape(value or "[NOT SET]")
        rows.append("<tr><td class='mono'>" + name + "</td><td>" + shown + "</td></tr>")
    body = "<div class='card'><h2>Server Configuration</h2><p class='muted'>Secret values are intentionally hidden. Edit them through cPanel Environment Variables.</p><table class='table'><tr><th>Variable</th><th>Value</th></tr>" + ''.join(rows) + "</table></div>"
    return layout("Configuration", body)


@manager.get("/logs")
@logged_in
def logs():
    with conn() as database:
        table_exists = database.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='audit'").fetchone()
        rows = database.execute("SELECT user_id, action, created_at FROM audit ORDER BY id DESC LIMIT 200").fetchall() if table_exists else []
    rows_html = ''.join("<tr><td>" + html.escape(str(row['created_at'])) + "</td><td>" + html.escape(str(row['user_id'])) + "</td><td>" + html.escape(str(row['action'])) + "</td></tr>" for row in rows)
    body = "<div class='card'><h2>Activity Log</h2><table class='table'><tr><th>Timestamp</th><th>User</th><th>Action</th></tr>" + (rows_html or '<tr><td colspan=3>Belum ada log.</td></tr>') + "</table></div>"
    return layout("Logs", body)


@manager.get("/api/health")
@logged_in
def api_health():
    return jsonify({"ok": True, "service": "gwprojectbot-manager", "time": int(time.time())})
