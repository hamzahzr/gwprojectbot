import html
import hmac
import json
import os
import shutil
import sqlite3
import time
from functools import wraps
from pathlib import Path

from flask import Blueprint, jsonify, redirect, render_template_string, request, session, url_for

BASE = Path(__file__).resolve().parent
DB = BASE / "gwproject.db"
PUBLISHED = BASE / "menu_config.json"
BACKUP_DIR = BASE / "manager_backups"
manager = Blueprint("manager", __name__, url_prefix="/manager")
LOGIN_USER = os.getenv("DASHBOARD_USERNAME", "admin").strip()
LOGIN_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "").strip()

CSS = """
*{box-sizing:border-box}body{margin:0;background:#080d19;color:#eaf1ff;font:14px system-ui,Arial,sans-serif}a{color:inherit}.shell{display:flex;min-height:100vh}.side{width:245px;background:#0b1222;border-right:1px solid #263653;padding:24px 16px}.logo{font-size:19px;font-weight:800}.muted,.hint{color:#91a4c4;font-size:12px}.nav{display:grid;gap:7px;margin-top:28px}.nav a{padding:12px;border-radius:10px;text-decoration:none;color:#a9b9d3}.nav a.active,.nav a:hover{background:#20365e;color:white}.main{flex:1;min-width:0;padding:30px}.top{display:flex;justify-content:space-between;gap:16px;margin-bottom:24px}.heading{font-size:30px;font-weight:800;margin:6px 0}.pill,.tag{display:inline-block;border:1px solid #33496d;background:#111e35;border-radius:999px;padding:7px 11px;font-size:12px}.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#34d399;margin-right:6px}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}.card{background:linear-gradient(145deg,#14213a,#0e1729);border:1px solid #2b3d5c;border-radius:16px;padding:20px}.span2{grid-column:span 2}.kpi{font-size:30px;font-weight:800;margin-top:8px}.title{font-size:17px;font-weight:800;margin:0 0 8px}.actions{display:flex;gap:8px;flex-wrap:wrap}.btn{display:inline-block;border:1px solid #385078;background:#101c31;color:#edf4ff;border-radius:9px;padding:9px 12px;text-decoration:none;font-size:13px;cursor:pointer}.btn.primary{background:#326ff0;border-color:#4b83ff}.btn.danger{background:#542533;border-color:#8a3d52}.form{display:grid;gap:12px;max-width:700px}.input{width:100%;padding:11px 12px;background:#0a1426;color:#eef5ff;border:1px solid #385078;border-radius:9px}.table-wrap{overflow:auto;border:1px solid #2b3d5c;border-radius:10px}.table{width:100%;border-collapse:collapse;min-width:650px}.table th,.table td{padding:12px;border-bottom:1px solid #263750;text-align:left}.table th{background:#101b30;color:#9db2d5}.alert{padding:12px;border:1px solid #8a3d52;background:#4d2330;border-radius:9px;color:#ffd0d8}@media(max-width:850px){.shell{display:block}.side{width:auto}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.span2{grid-column:span 2}}@media(max-width:520px){.main{padding:16px}.top{display:block}.grid{grid-template-columns:1fr}.span2{grid-column:span 1}.heading{font-size:24px}}
"""


def db():
    conn = sqlite3.connect(DB, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def now():
    return int(time.time())


def esc(value):
    return html.escape(str(value or ""), quote=True)


def ensure():
    BACKUP_DIR.mkdir(exist_ok=True)
    with db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT,action TEXT,created_at INTEGER)")
        conn.execute("CREATE TABLE IF NOT EXISTS manager_menus(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,description TEXT DEFAULT '',active INTEGER DEFAULT 1,sort_order INTEGER DEFAULT 0,updated_at INTEGER)")
        conn.execute("CREATE TABLE IF NOT EXISTS manager_buttons(id INTEGER PRIMARY KEY AUTOINCREMENT,menu_id INTEGER NOT NULL,label TEXT NOT NULL,callback TEXT DEFAULT '',button_type TEXT DEFAULT 'callback',url TEXT DEFAULT '',active INTEGER DEFAULT 1,sort_order INTEGER DEFAULT 0,FOREIGN KEY(menu_id) REFERENCES manager_menus(id) ON DELETE CASCADE)")
        conn.commit()


def audit(action):
    ensure()
    with db() as conn:
        conn.execute("INSERT INTO audit(user_id,action,created_at) VALUES(?,?,?)", (session.get("manager_user", "admin"), action, now()))
        conn.commit()


def logged(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("manager_auth"):
            return redirect(url_for("manager.login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def page(title, body, active="dashboard"):
    template = """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{{ title }} · GW Project</title><style>{{ css }}</style></head><body><div class='shell'><aside class='side'><div class='logo'>🛰️ GW-PROJECT</div><div class='muted'>BOT MANAGER CONSOLE</div><nav class='nav'><a class='{{ "active" if active == "dashboard" else "" }}' href='{{ url_for("manager.dashboard") }}'>◈ Dashboard</a><a class='{{ "active" if active == "users" else "" }}' href='{{ url_for("manager.users") }}'>♙ Users & Roles</a><a class='{{ "active" if active == "menus" else "" }}' href='{{ url_for("manager.menus") }}'>▦ Menu Center</a><a class='{{ "active" if active == "config" else "" }}' href='{{ url_for("manager.config") }}'>⚙ API Configuration</a><a class='{{ "active" if active == "backups" else "" }}' href='{{ url_for("manager.backups") }}'>◫ Backup & Rollback</a><a class='{{ "active" if active == "logs" else "" }}' href='{{ url_for("manager.logs") }}'>≡ Activity Logs</a></nav><br><a class='btn' href='{{ url_for("manager.logout") }}'>↪ Logout</a></aside><main class='main'><div class='top'><div><div class='muted'>GW Project / Control Center</div><div class='heading'>{{ title }}</div><div class='muted'>Manage menus, buttons, roles and releases.</div></div><div class='pill'><span class='dot'></span> Application online</div></div>{{ body|safe }}</main></div></body></html>"""
    return render_template_string(template, title=title, body=body, active=active, css=CSS)


def input_html(name, value="", label=None, kind="text", required=True):
    req = " required" if required else ""
    return "<label>" + esc(label or name) + "<input class='input' name='" + esc(name) + "' type='" + esc(kind) + "' value='" + esc(value) + "'" + req + "></label>"


def menu_snapshot():
    ensure()
    with db() as conn:
        menus = conn.execute("SELECT * FROM manager_menus ORDER BY sort_order,id").fetchall()
        result = []
        for menu in menus:
            buttons = conn.execute("SELECT * FROM manager_buttons WHERE menu_id=? ORDER BY sort_order,id", (menu["id"],)).fetchall()
            result.append({"id": menu["id"], "name": menu["name"], "description": menu["description"], "active": bool(menu["active"]), "sort_order": menu["sort_order"], "buttons": [dict(button) for button in buttons]})
        return result


def seed():
    ensure()
    with db() as conn:
        count = conn.execute("SELECT COUNT(*) AS n FROM manager_menus").fetchone()["n"]
        if count == 0:
            defaults = [("Main Menu", "Start / Home"), ("Tools", "Tool selection"), ("Settings", "User settings"), ("Help", "Help and information")]
            for index, item in enumerate(defaults):
                conn.execute("INSERT INTO manager_menus(name,description,sort_order,updated_at) VALUES(?,?,?,?)", (item[0], item[1], index, now()))
            conn.commit()


@manager.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if LOGIN_PASSWORD and hmac.compare_digest(username, LOGIN_USER) and hmac.compare_digest(password, LOGIN_PASSWORD):
            session["manager_auth"] = True
            session["manager_user"] = username
            audit("dashboard_login")
            return redirect(request.args.get("next") or url_for("manager.dashboard"))
        error = "Username atau password salah. Isi DASHBOARD_USERNAME dan DASHBOARD_PASSWORD di cPanel."
    message = "<div class='alert'>" + esc(error) + "</div>" if error else ""
    template = "<style>{{ css }}</style><main class='main'><div class='card' style='max-width:440px;margin:10vh auto'><div class='logo'>🛰️ GW-PROJECT BOT MANAGER</div><p class='muted'>Secure administrator sign-in</p>{{ message }}<form class='form' method='post'><input class='input' name='username' placeholder='Username' required><input class='input' name='password' type='password' placeholder='Password' required><button class='btn primary'>Sign in</button></form></div></main>"
    return render_template_string(template, css=CSS, message=message)


@manager.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("manager.login"))


@manager.get("/")
@logged
def dashboard():
    seed()
    with db() as conn:
        menus_count = conn.execute("SELECT COUNT(*) AS n FROM manager_menus").fetchone()["n"]
        buttons_count = conn.execute("SELECT COUNT(*) AS n FROM manager_buttons").fetchone()["n"]
        audit_count = conn.execute("SELECT COUNT(*) AS n FROM audit").fetchone()["n"]
        user_exists = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
        users_count = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] if user_exists else 0
    body = "<div class='grid'>"
    for label, value in [("Menus", menus_count), ("Buttons", buttons_count), ("Bot users", users_count), ("Audit events", audit_count)]:
        body += "<div class='card'><div class='muted'>" + label + "</div><div class='kpi'>" + str(value) + "</div></div>"
    body += "<div class='card span2'><h3 class='title'>Quick actions</h3><div class='actions'><a class='btn primary' href='" + url_for("manager.menu_new") + "'>+ Add menu</a><a class='btn' href='" + url_for("manager.menus") + "'>Menu Center</a><a class='btn' href='" + url_for("manager.backups") + "'>Backup / Rollback</a></div></div>"
    body += "<div class='card span2'><h3 class='title'>Release status</h3><p class='muted'>Changes are saved as drafts in SQLite. Publish writes the active menu configuration to menu_config.json.</p><span class='tag'>Secrets hidden</span> <span class='tag'>Admin protected</span> <span class='tag'>Backup enabled</span></div></div>"
    return page("Dashboard", body)


@manager.get("/menus")
@logged
def menus():
    seed()
    rows = ""
    for menu in menu_snapshot():
        edit_url = url_for("manager.menu_edit", menu_id=menu["id"])
        button_url = url_for("manager.button_new", menu_id=menu["id"])
        preview_url = url_for("manager.preview", menu_id=menu["id"])
        toggle_url = url_for("manager.menu_toggle", menu_id=menu["id"])
        status = "Active" if menu["active"] else "Disabled"
        toggle_text = "Disable" if menu["active"] else "Enable"
        rows += "<tr><td><strong>" + esc(menu["name"]) + "</strong><div class='hint'>" + esc(menu["description"]) + "</div></td><td>" + str(len(menu["buttons"])) + "</td><td>" + status + "</td><td><div class='actions'><a class='btn' href='" + edit_url + "'>Edit</a><a class='btn' href='" + button_url + "'>+ Button</a><a class='btn' href='" + preview_url + "'>Preview</a><form method='post' action='" + toggle_url + "'><button class='btn' type='submit'>" + toggle_text + "</button></form></div></td></tr>"
    body = "<div class='card'><div class='actions'><div><h3 class='title'>Menu Center</h3><div class='muted'>Create, edit, reorder, enable or disable menus and buttons.</div></div><a class='btn primary' href='" + url_for("manager.menu_new") + "'>+ Add menu</a></div><br><div class='table-wrap'><table class='table'><tr><th>Menu</th><th>Buttons</th><th>Status</th><th>Actions</th></tr>" + (rows or "<tr><td colspan='4'>No menus.</td></tr>") + "</table></div><br><div class='actions'><a class='btn primary' href='" + url_for("manager.publish") + "'>Publish changes</a><a class='btn' href='" + url_for("manager.preview") + "'>Preview Telegram</a></div></div>"
    return page("Menu Center", body, "menus")


@manager.route("/menus/new", methods=["GET", "POST"])
@logged
def menu_new():
    if request.method == "POST":
        with db() as conn:
            conn.execute("INSERT INTO manager_menus(name,description,active,sort_order,updated_at) VALUES(?,?,?,?,?)", (request.form["name"], request.form.get("description", ""), 1, 999, now()))
            conn.commit()
        audit("menu_created")
        return redirect(url_for("manager.menus"))
    body = "<div class='card'><h3 class='title'>Add menu</h3><form class='form' method='post'>" + input_html("name", label="Menu name") + input_html("description", label="Description", required=False) + "<button class='btn primary'>Save menu</button></form></div>"
    return page("Add Menu", body, "menus")


@manager.route("/menus/<int:menu_id>/edit", methods=["GET", "POST"])
@logged
def menu_edit(menu_id):
    with db() as conn:
        menu = conn.execute("SELECT * FROM manager_menus WHERE id=?", (menu_id,)).fetchone()
    if not menu:
        return "Menu not found", 404
    if request.method == "POST":
        with db() as conn:
            conn.execute("UPDATE manager_menus SET name=?,description=?,sort_order=?,updated_at=? WHERE id=?", (request.form["name"], request.form.get("description", ""), int(request.form.get("sort_order", 0)), now(), menu_id))
            conn.commit()
        audit("menu_updated")
        return redirect(url_for("manager.menus"))
    delete_url = url_for("manager.menu_delete", menu_id=menu_id)
    body = "<div class='card'><h3 class='title'>Edit menu</h3><form class='form' method='post'>" + input_html("name", menu["name"], "Menu name") + input_html("description", menu["description"], "Description", required=False) + input_html("sort_order", menu["sort_order"], "Order", "number") + "<button class='btn primary'>Save changes</button></form><br><form method='post' action='" + delete_url + "'><button class='btn danger'>Delete menu</button></form></div>"
    return page("Edit Menu", body, "menus")


@manager.post("/menus/<int:menu_id>/toggle")
@logged
def menu_toggle(menu_id):
    with db() as conn:
        conn.execute("UPDATE manager_menus SET active=CASE active WHEN 1 THEN 0 ELSE 1 END,updated_at=? WHERE id=?", (now(), menu_id))
        conn.commit()
    audit("menu_toggled")
    return redirect(url_for("manager.menus"))


@manager.post("/menus/<int:menu_id>/delete")
@logged
def menu_delete(menu_id):
    with db() as conn:
        conn.execute("DELETE FROM manager_menus WHERE id=?", (menu_id,))
        conn.commit()
    audit("menu_deleted")
    return redirect(url_for("manager.menus"))


@manager.route("/menus/<int:menu_id>/buttons/new", methods=["GET", "POST"])
@logged
def button_new(menu_id):
    if request.method == "POST":
        with db() as conn:
            conn.execute("INSERT INTO manager_buttons(menu_id,label,callback,button_type,url,active,sort_order) VALUES(?,?,?,?,?,?,?)", (menu_id, request.form["label"], request.form.get("callback", ""), request.form.get("button_type", "callback"), request.form.get("url", ""), 1, int(request.form.get("sort_order", 999))))
            conn.commit()
        audit("button_created")
        return redirect(url_for("manager.menus"))
    body = "<div class='card'><h3 class='title'>Add button</h3><form class='form' method='post'>" + input_html("label", label="Button text") + input_html("callback", label="Callback data", required=False) + input_html("button_type", "callback", "Button type") + input_html("url", label="URL", required=False) + input_html("sort_order", 999, "Order", "number") + "<button class='btn primary'>Save button</button></form></div>"
    return page("Add Button", body, "menus")


@manager.route("/buttons/<int:button_id>/edit", methods=["GET", "POST"])
@logged
def button_edit(button_id):
    with db() as conn:
        button = conn.execute("SELECT * FROM manager_buttons WHERE id=?", (button_id,)).fetchone()
    if not button:
        return "Button not found", 404
    if request.method == "POST":
        active = 1 if request.form.get("active") else 0
        with db() as conn:
            conn.execute("UPDATE manager_buttons SET label=?,callback=?,button_type=?,url=?,sort_order=?,active=? WHERE id=?", (request.form["label"], request.form.get("callback", ""), request.form.get("button_type", "callback"), request.form.get("url", ""), int(request.form.get("sort_order", 0)), active, button_id))
            conn.commit()
        audit("button_updated")
        return redirect(url_for("manager.menus"))
    checked = " checked" if button["active"] else ""
    delete_url = url_for("manager.button_delete", button_id=button_id)
    body = "<div class='card'><h3 class='title'>Edit button</h3><form class='form' method='post'>" + input_html("label", button["label"], "Button text") + input_html("callback", button["callback"], "Callback data", required=False) + input_html("button_type", button["button_type"], "Button type") + input_html("url", button["url"], "URL", required=False) + input_html("sort_order", button["sort_order"], "Order", "number") + "<label><input type='checkbox' name='active'" + checked + "> Active</label><button class='btn primary'>Save button</button></form><br><form method='post' action='" + delete_url + "'><button class='btn danger'>Delete button</button></form></div>"
    return page("Edit Button", body, "menus")


@manager.post("/buttons/<int:button_id>/delete")
@logged
def button_delete(button_id):
    with db() as conn:
        conn.execute("DELETE FROM manager_buttons WHERE id=?", (button_id,))
        conn.commit()
    audit("button_deleted")
    return redirect(url_for("manager.menus"))


@manager.get("/preview")
@logged
def preview():
    menus_data = menu_snapshot()
    selected = request.args.get("menu_id")
    menu = next((item for item in menus_data if str(item["id"]) == selected), menus_data[0] if menus_data else None)
    if not menu:
        return page("Telegram Preview", "<div class='card'>No menu available.</div>", "menus")
    buttons = "".join("<span class='btn' style='margin:4px'>" + esc(item["label"]) + "</span>" for item in menu["buttons"] if item["active"])
    body = "<div class='card' style='max-width:600px'><div class='muted'>Telegram preview · " + esc(menu["name"]) + "</div><h3 class='title'>" + esc(menu["description"] or menu["name"]) + "</h3><div style='background:#17243a;padding:18px;border-radius:12px'>" + (buttons or "<span class='muted'>No active buttons</span>") + "</div><br><a class='btn' href='" + url_for("manager.menus") + "'>Back to editor</a></div>"
    return page("Telegram Preview", body, "menus")


@manager.route("/publish", methods=["GET", "POST"])
@logged
def publish():
    ensure()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup = BACKUP_DIR / ("menu_config_" + stamp + ".json")
    if PUBLISHED.exists():
        shutil.copy2(PUBLISHED, backup)
    PUBLISHED.write_text(json.dumps({"version": stamp, "published_at": now(), "menus": menu_snapshot()}, ensure_ascii=False, indent=2), encoding="utf-8")
    audit("menu_published")
    return redirect(url_for("manager.backups"))


@manager.get("/backups")
@logged
def backups():
    files = sorted(BACKUP_DIR.glob("menu_config_*.json"), reverse=True)
    rows = ""
    for item in files:
        rollback_url = url_for("manager.rollback") + "?file=" + esc(item.name)
        rows += "<tr><td>" + esc(item.name) + "</td><td>" + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(item.stat().st_mtime)) + "</td><td><form method='post' action='" + rollback_url + "'><button class='btn'>Rollback</button></form></td></tr>"
    body = "<div class='card'><h3 class='title'>Backup & Rollback</h3><p class='muted'>Every publish keeps the previous menu_config.json.</p><a class='btn primary' href='" + url_for("manager.publish") + "'>Publish current draft</a><br><br><div class='table-wrap'><table class='table'><tr><th>Backup</th><th>Created</th><th>Action</th></tr>" + (rows or "<tr><td colspan='3'>No backups yet.</td></tr>") + "</table></div></div>"
    return page("Backup & Rollback", body, "backups")


@manager.post("/rollback")
@logged
def rollback():
    name = Path(request.args.get("file", "")).name
    source = BACKUP_DIR / name
    if source.exists() and name.startswith("menu_config_"):
        shutil.copy2(source, PUBLISHED)
        audit("menu_rollback")
    return redirect(url_for("manager.backups"))


@manager.get("/users")
@logged
def users():
    with db() as conn:
        exists = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
        rows = conn.execute("SELECT user_id,role,permissions FROM users ORDER BY rowid DESC LIMIT 300").fetchall() if exists else []
    html_rows = "".join("<tr><td>" + esc(row["user_id"]) + "</td><td>" + esc(row["role"]) + "</td><td>" + esc(row["permissions"]) + "</td><td><a class='btn' href='" + url_for("manager.user_edit", user_id=row["user_id"]) + "'>Edit role</a></td></tr>" for row in rows)
    body = "<div class='card'><h3 class='title'>Users & Roles</h3><div class='muted'>Administrator can edit role and permissions.</div><br><div class='table-wrap'><table class='table'><tr><th>User ID</th><th>Role</th><th>Permissions</th><th>Action</th></tr>" + (html_rows or "<tr><td colspan='4'>No users found.</td></tr>") + "</table></div></div>"
    return page("Users & Roles", body, "users")


@manager.route("/users/<user_id>/edit", methods=["GET", "POST"])
@logged
def user_edit(user_id):
    with db() as conn:
        row = conn.execute("SELECT user_id,role,permissions FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        return "User not found", 404
    if request.method == "POST":
        with db() as conn:
            conn.execute("UPDATE users SET role=?,permissions=? WHERE user_id=?", (request.form["role"], request.form.get("permissions", ""), user_id))
            conn.commit()
        audit("user_role_updated")
        return redirect(url_for("manager.users"))
    body = "<div class='card'><h3 class='title'>Edit user " + esc(user_id) + "</h3><form class='form' method='post'>" + input_html("role", row["role"], "Role") + input_html("permissions", row["permissions"], "Permissions", required=False) + "<button class='btn primary'>Save role</button></form></div>"
    return page("Edit Role", body, "users")


@manager.get("/config")
@logged
def config():
    names = ["BOT_TOKEN", "WEBHOOK_SECRET", "ADMIN_IDS", "SEARCH_API_URL", "SEARCH_API_TOKEN", "SEARCH_API_LIMIT", "USERNAME_API_URL", "USERNAME_API_TOKEN", "TIKTOK_API_URL", "TIKTOK_API_TOKEN"]
    rows = ""
    for name in names:
        value = os.getenv(name)
        shown = value if name.endswith("_URL") or name in ("ADMIN_IDS", "SEARCH_API_LIMIT") else ("[SET]" if value else "[NOT SET]")
        rows += "<tr><td>" + name + "</td><td>" + esc(shown) + "</td></tr>"
    body = "<div class='card'><h3 class='title'>API Configuration</h3><p class='muted'>Edit secret values only in cPanel Environment Variables.</p><div class='table-wrap'><table class='table'><tr><th>Variable</th><th>Status / value</th></tr>" + rows + "</table></div></div>"
    return page("API Configuration", body, "config")


@manager.get("/logs")
@logged
def logs():
    ensure()
    with db() as conn:
        rows = conn.execute("SELECT user_id,action,created_at FROM audit ORDER BY id DESC LIMIT 300").fetchall()
    html_rows = "".join("<tr><td>" + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(row["created_at"])) + "</td><td>" + esc(row["user_id"]) + "</td><td>" + esc(row["action"]) + "</td></tr>" for row in rows)
    body = "<div class='card'><h3 class='title'>Activity Logs</h3><div class='table-wrap'><table class='table'><tr><th>Time</th><th>User</th><th>Action</th></tr>" + (html_rows or "<tr><td colspan='3'>No logs.</td></tr>") + "</table></div></div>"
    return page("Activity Logs", body, "logs")


@manager.get("/api/health")
@logged
def api_health():
    return jsonify({"ok": True, "service": "gwprojectbot-manager", "time": now()})
