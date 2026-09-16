import html
import hmac
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
:root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#e8eefc;background:#080d19}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 10% 0%,#17264a 0,#0b1120 38%,#080d19 100%)}
a{color:inherit}.shell{display:flex;min-height:100vh}.side{width:248px;background:rgba(8,13,25,.86);border-right:1px solid #25314a;padding:24px 16px;position:sticky;top:0;height:100vh}.logo{font-weight:900;font-size:19px;letter-spacing:-.6px}.sub{color:#8da0bf;font-size:12px;margin-top:5px}.nav{margin-top:32px;display:grid;gap:7px}.nav a{display:flex;gap:11px;align-items:center;text-decoration:none;color:#9eacc6;padding:12px 13px;border-radius:12px;font-size:14px}.nav a:hover,.nav a.active{background:#1b2d50;color:#fff}.side-bottom{position:absolute;bottom:22px;left:16px;right:16px}.main{flex:1;min-width:0;padding:28px 34px}.top{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:26px}.eyebrow{color:#7792c1;font-size:12px;text-transform:uppercase;letter-spacing:1.6px}.heading{font-size:29px;font-weight:850;letter-spacing:-1px;margin:6px 0}.muted{color:#91a0bb}.pill{display:inline-flex;align-items:center;gap:7px;border:1px solid #30415f;background:#111b2e;border-radius:999px;padding:8px 12px;font-size:12px;color:#b8c7df}.dot{width:8px;height:8px;border-radius:50%;background:#35d399;box-shadow:0 0 12px #35d399}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}.card{background:linear-gradient(145deg,rgba(20,31,52,.96),rgba(13,21,37,.96));border:1px solid #293854;border-radius:18px;padding:20px;box-shadow:0 14px 45px rgba(0,0,0,.18)}.kpi{font-size:31px;font-weight:850;letter-spacing:-1px;margin:12px 0 4px}.kpi-label{font-size:13px;color:#9eacc6}.span2{grid-column:span 2}.span4{grid-column:span 4}.section-title{font-size:16px;font-weight:800;margin:0 0 5px}.section-sub{font-size:12px;color:#8495b2;margin-bottom:18px}.actions{display:flex;gap:10px;flex-wrap:wrap}.btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;border:1px solid #344665;background:#101a2d;color:#e7efff;border-radius:10px;padding:10px 13px;text-decoration:none;font-size:13px;cursor:pointer}.btn:hover{border-color:#5475ad}.btn.primary{background:linear-gradient(135deg,#3978ff,#2455cf);border-color:#3978ff}.btn.danger{background:#4a202b;border-color:#743245}.table-wrap{overflow:auto;border:1px solid #293854;border-radius:12px}.table{width:100%;border-collapse:collapse;min-width:500px}.table th,.table td{padding:13px 14px;border-bottom:1px solid #26344d;text-align:left;font-size:13px}.table th{color:#8ea2c4;font-weight:700;background:#101a2c}.table tr:last-child td{border-bottom:0}.tag{display:inline-block;padding:5px 8px;border-radius:7px;background:#172b49;color:#a9c7ff;font-size:11px}.form{display:grid;gap:12px;max-width:560px}.input,.select{width:100%;background:#0c1526;color:#eaf1ff;border:1px solid #344665;border-radius:10px;padding:12px}.alert{padding:12px;border-radius:10px;background:#48212b;color:#ffc5d0;border:1px solid #743245;font-size:13px}.login{max-width:440px;margin:10vh auto}.login .logo{margin-bottom:24px}.empty{padding:30px;text-align:center;color:#8ea2c4}.footer-note{font-size:11px;color:#7083a2;margin-top:20px;line-height:1.6}
@media(max-width:1000px){.side{width:210px}.main{padding:24px}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.span4{grid-column:span 2}}
@media(max-width:650px){.shell{display:block}.side{position:static;width:auto;height:auto;border-right:0;border-bottom:1px solid #25314a;padding:18px}.nav{display:flex;overflow:auto;margin-top:18px}.nav a{white-space:nowrap}.side-bottom{display:none}.main{padding:18px}.top{align-items:flex-start;flex-direction:column}.grid{grid-template-columns:1fr}.span2,.span4{grid-column:span 1}.heading{font-size:25px}}
"""


def conn():
    database = sqlite3.connect(MANAGER_DB_PATH, timeout=10)
    database.row_factory = sqlite3.Row
    return database


def ensure_tables():
    with conn() as database:
        database.execute("CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, action TEXT, created_at INTEGER)")
        database.commit()


def audit(user, action):
    ensure_tables()
    with conn() as database:
        database.execute("INSERT INTO audit(user_id, action, created_at) VALUES(?,?,?)", (str(user), action, int(time.time())))
        database.commit()


def logged_in(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if not session.get("manager_auth"):
            return redirect(url_for("manager.login", next=request.path))
        return function(*args, **kwargs)
    return wrapper


def layout(title, content, active="dashboard"):
    template = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{ title }} · GW Project</title><style>{{ css }}</style></head>
<body><div class="shell"><aside class="side"><div class="logo">🛰️ GW-PROJECT</div><div class="sub">BOT MANAGER CONSOLE</div><nav class="nav">
<a class="{{ 'active' if active=='dashboard' else '' }}" href="{{ url_for('manager.dashboard') }}">◈ <span>Dashboard</span></a>
<a class="{{ 'active' if active=='users' else '' }}" href="{{ url_for('manager.users') }}">♙ <span>Users & Roles</span></a>
<a class="{{ 'active' if active=='menus' else '' }}" href="{{ url_for('manager.menus') }}">▦ <span>Menu Center</span></a>
<a class="{{ 'active' if active=='config' else '' }}" href="{{ url_for('manager.config') }}">⚙ <span>API Configuration</span></a>
<a class="{{ 'active' if active=='logs' else '' }}" href="{{ url_for('manager.logs') }}">≡ <span>Activity Logs</span></a>
<a class="{{ 'active' if active=='settings' else '' }}" href="{{ url_for('manager.settings') }}">⌘ <span>System Settings</span></a>
</nav><div class="side-bottom"><a class="btn" style="width:100%" href="{{ url_for('manager.logout') }}">↪ Logout</a><div class="footer-note">Secrets stay in cPanel environment variables. This console never displays token values.</div></div></aside>
<main class="main"><div class="top"><div><div class="eyebrow">GW Project / Control Center</div><div class="heading">{{ title }}</div><div class="muted" style="font-size:13px">Manage your bot from one secure workspace.</div></div><div class="pill"><span class="dot"></span> Application online</div></div>{{ content|safe }}</main></div></body></html>
"""
    return render_template_string(template, title=title, css=CSS, content=content, active=active)


@manager.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        valid = bool(LOGIN_USER and LOGIN_PASSWORD) and hmac.compare_digest(username, LOGIN_USER) and hmac.compare_digest(password, LOGIN_PASSWORD)
        if valid:
            session["manager_auth"] = True
            session["manager_user"] = username
            audit(username, "dashboard_login")
            return redirect(request.args.get("next") or url_for("manager.dashboard"))
        error = "Username atau password salah. Periksa environment variables di cPanel."
    error_html = "<div class='alert'>" + html.escape(error) + "</div>" if error else ""
    content = "<div class='card login'><div class='logo'>🛰️ GW-PROJECT BOT MANAGER</div><p class='muted'>Secure administrator sign-in</p>" + error_html + "<form class='form' method='post'><input class='input' name='username' placeholder='Username' autocomplete='username' required><input class='input' name='password' type='password' placeholder='Password' autocomplete='current-password' required><button class='btn primary' type='submit'>Sign in to dashboard</button></form><div class='footer-note'>Credentials are read from server environment variables and are not stored in GitHub.</div></div>"
    return render_template_string("<style>" + CSS + "</style><main class='main'>" + content + "</main>", css=CSS)


@manager.get("/logout")
def logout():
    if session.get("manager_user"):
        audit(session.get("manager_user"), "dashboard_logout")
    session.clear()
    return redirect(url_for("manager.login"))


@manager.get("/")
@logged_in
def dashboard():
    ensure_tables()
    with conn() as database:
        users_table = database.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
        users_count = database.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] if users_table else 0
        admins_count = database.execute("SELECT COUNT(*) AS n FROM users WHERE role='admin'").fetchone()["n"] if users_table else 0
        audits_count = database.execute("SELECT COUNT(*) AS n FROM audit").fetchone()["n"]
    content = f"""
<div class='grid'><div class='card'><div class='kpi-label'>Bot status</div><div class='kpi'>ONLINE</div><div class='muted' style='font-size:12px'>Webhook active</div></div><div class='card'><div class='kpi-label'>Registered users</div><div class='kpi'>{users_count}</div><div class='muted' style='font-size:12px'>From bot database</div></div><div class='card'><div class='kpi-label'>Administrators</div><div class='kpi'>{admins_count}</div><div class='muted' style='font-size:12px'>Role-based access</div></div><div class='card'><div class='kpi-label'>Audit events</div><div class='kpi'>{audits_count}</div><div class='muted' style='font-size:12px'>Recorded activities</div></div>
<div class='card span2'><h3 class='section-title'>Quick actions</h3><div class='section-sub'>Jump directly to the most-used management areas.</div><div class='actions'><a class='btn primary' href='{url_for("manager.users")}'>Manage users</a><a class='btn' href='{url_for("manager.menus")}'>Open menu center</a><a class='btn' href='{url_for("manager.config")}'>Inspect API config</a><a class='btn' href='{url_for("manager.logs")}'>View activity</a></div></div>
<div class='card span2'><h3 class='section-title'>Runtime overview</h3><div class='section-sub'>Current application wiring.</div><div class='table-wrap'><table class='table'><tr><th>Application</th><td>GW Project Bot</td></tr><tr><th>Manager URL</th><td>/manager</td></tr><tr><th>Webhook URL</th><td>/webhook</td></tr><tr><th>Database</th><td>gwproject.db</td></tr><tr><th>Python</th><td>3.10 compatible</td></tr></table></div></div>
<div class='card span4'><h3 class='section-title'>Security status</h3><div class='section-sub'>Recommended server-side checks.</div><div class='actions'><span class='tag'>Secrets hidden</span><span class='tag'>Session protected</span><span class='tag'>SQLite timeout enabled</span><span class='tag'>Audit logging enabled</span></div></div></div>"""
    return layout("Dashboard", content, "dashboard")


@manager.get("/users")
@logged_in
def users():
    with conn() as database:
        exists = database.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
        rows = database.execute("SELECT user_id, role, permissions FROM users ORDER BY rowid DESC LIMIT 200").fetchall() if exists else []
    rows_html = "".join("<tr><td>" + html.escape(str(r["user_id"])) + "</td><td><span class='tag'>" + html.escape(str(r["role"])) + "</span></td><td>" + html.escape(str(r["permissions"] or "-")) + "</td></tr>" for r in rows)
    content = "<div class='card'><h3 class='section-title'>Users & Roles</h3><div class='section-sub'>Read-only view of users currently stored by the bot.</div><div class='table-wrap'><table class='table'><tr><th>User ID</th><th>Role</th><th>Permissions</th></tr>" + (rows_html or "<tr><td colspan='3' class='empty'>No users found.</td></tr>") + "</table></div></div>"
    return layout("Users & Roles", content, "users")


@manager.get("/menus")
@logged_in
def menus():
    menu_items = [("Main Menu", "Start / Home", "main_menu"), ("Tools", "Tool selection", "tools_menu"), ("Settings", "User settings", "settings_menu"), ("Help", "Help and information", "help_handler")]
    rows = "".join("<tr><td>" + html.escape(a) + "</td><td>" + html.escape(b) + "</td><td><span class='tag'>" + html.escape(c) + "</span></td><td><span class='muted'>Code-managed</span></td></tr>" for a,b,c in menu_items)
    content = "<div class='card'><h3 class='section-title'>Menu Center</h3><div class='section-sub'>Central overview of menu handlers. Editing is intentionally separated from live bot execution until a persistent menu schema is enabled.</div><div class='table-wrap'><table class='table'><tr><th>Menu</th><th>Description</th><th>Handler</th><th>Status</th></tr>" + rows + "</table></div><div class='footer-note'>Next integration step: connect these handlers to a menu_items table so changes can be published without editing Python source.</div></div>"
    return layout("Menu Center", content, "menus")


@manager.get("/config")
@logged_in
def config():
    names = ["BOT_TOKEN", "WEBHOOK_SECRET", "ADMIN_IDS", "RATE_LIMIT_SECONDS", "SEARCH_API_URL", "SEARCH_API_TOKEN", "SEARCH_API_LIMIT", "SEARCH_API_LANG", "REKENING_API_URL", "REKENING_API_TOKEN", "EWALLET_API_URL", "EWALLET_API_TOKEN", "AI_API_URL", "AI_API_TOKEN", "TIKTOK_API_URL", "TIKTOK_API_TOKEN", "USERNAME_API_URL", "USERNAME_API_TOKEN", "NOPOL_API_URL", "NOPOL_API_TOKEN"]
    rows = []
    for name in names:
        value = os.getenv(name, "")
        shown = html.escape(value or "[NOT SET]") if name.endswith("_URL") or name in {"ADMIN_IDS", "RATE_LIMIT_SECONDS", "SEARCH_API_LIMIT", "SEARCH_API_LANG"} else ("[SET]" if value else "[NOT SET]")
        rows.append("<tr><td>" + name + "</td><td>" + shown + "</td></tr>")
    content = "<div class='card'><h3 class='section-title'>API Configuration</h3><div class='section-sub'>Secret values are masked. Update variables from cPanel → Setup Python App.</div><div class='table-wrap'><table class='table'><tr><th>Environment variable</th><th>Value / status</th></tr>" + "".join(rows) + "</table></div></div>"
    return layout("API Configuration", content, "config")


@manager.get("/logs")
@logged_in
def logs():
    ensure_tables()
    with conn() as database:
        rows = database.execute("SELECT user_id, action, created_at FROM audit ORDER BY id DESC LIMIT 200").fetchall()
    rows_html = "".join("<tr><td>" + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(r["created_at"]))) + "</td><td>" + html.escape(str(r["user_id"])) + "</td><td>" + html.escape(str(r["action"])) + "</td></tr>" for r in rows)
    content = "<div class='card'><h3 class='section-title'>Activity Logs</h3><div class='section-sub'>Latest administrator and manager events.</div><div class='table-wrap'><table class='table'><tr><th>Time</th><th>User</th><th>Action</th></tr>" + (rows_html or "<tr><td colspan='3' class='empty'>No activity recorded.</td></tr>") + "</table></div></div>"
    return layout("Activity Logs", content, "logs")


@manager.get("/settings")
@logged_in
def settings():
    content = "<div class='grid'><div class='card span2'><h3 class='section-title'>System Settings</h3><div class='section-sub'>Deployment and security information.</div><div class='table-wrap'><table class='table'><tr><th>Dashboard username</th><td>Configured via environment</td></tr><tr><th>Password</th><td>Never displayed</td></tr><tr><th>Session secret</th><td>Use DASHBOARD_SESSION_SECRET in cPanel</td></tr><tr><th>Database</th><td>gwproject.db</td></tr></table></div></div><div class='card span2'><h3 class='section-title'>Deployment checklist</h3><div class='section-sub'>Keep these items configured before production use.</div><div class='actions'><span class='tag'>HTTPS enabled</span><span class='tag'>Strong dashboard password</span><span class='tag'>Private environment secrets</span><span class='tag'>Regular database backup</span></div></div></div>"
    return layout("System Settings", content, "settings")


@manager.get("/api/health")
@logged_in
def api_health():
    return jsonify({"ok": True, "service": "gwprojectbot-manager", "time": int(time.time())})
