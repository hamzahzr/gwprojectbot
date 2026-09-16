import html
import hmac
import json
import os
import shutil
import sqlite3
import time
from functools import wraps
from pathlib import Path

from flask import Blueprint, redirect, render_template_string, request, session, url_for

BASE = Path(__file__).resolve().parent
DB = BASE / "gwproject.db"
PUBLISHED = BASE / "menu_config.json"
BACKUP_DIR = BASE / "manager_backups"
manager = Blueprint("manager", __name__, url_prefix="/manager")
LOGIN_USER = os.getenv("DASHBOARD_USERNAME", "admin").strip()
LOGIN_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "").strip()

CSS = """
*{box-sizing:border-box}body{margin:0;background:#080d19;color:#edf4ff;font:14px Inter,system-ui,Arial,sans-serif}a{color:inherit}.shell{display:flex;min-height:100vh}.side{width:245px;flex:0 0 245px;background:#0b1222;border-right:1px solid #263653;padding:24px 16px}.logo{font-size:19px;font-weight:800}.muted,.hint{color:#91a4c4;font-size:12px}.nav{display:grid;gap:7px;margin-top:28px}.nav a{padding:12px;border-radius:10px;text-decoration:none;color:#a9b9d3}.nav a.active,.nav a:hover{background:#20365e;color:#fff}.main{flex:1;min-width:0;padding:30px}.top{display:flex;justify-content:space-between;gap:16px;margin-bottom:24px}.heading{font-size:30px;font-weight:800;margin:6px 0}.pill,.tag{display:inline-block;border:1px solid #33496d;background:#111e35;border-radius:999px;padding:7px 11px;font-size:12px}.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#34d399;margin-right:6px}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}.card{background:linear-gradient(145deg,#14213a,#0e1729);border:1px solid #2b3d5c;border-radius:16px;padding:20px}.span2{grid-column:span 2}.kpi{font-size:30px;font-weight:800;margin-top:8px}.title{font-size:17px;font-weight:800;margin:0 0 8px}.actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.btn{display:inline-block;border:1px solid #385078;background:#101c31;color:#edf4ff;border-radius:9px;padding:9px 12px;text-decoration:none;font-size:13px;cursor:pointer}.btn.primary{background:#326ff0;border-color:#4b83ff}.btn.danger{background:#542533;border-color:#8a3d52}.form{display:grid;gap:12px;max-width:760px}.input,.select,.textarea{width:100%;padding:11px 12px;background:#0a1426;color:#eef5ff;border:1px solid #385078;border-radius:9px}.textarea{min-height:120px;resize:vertical}.table-wrap{overflow:auto;border:1px solid #2b3d5c;border-radius:10px}.table{width:100%;border-collapse:collapse;min-width:720px}.table th,.table td{padding:12px;border-bottom:1px solid #263750;text-align:left}.table th{background:#101b30;color:#9db2d5}.alert{padding:12px;border:1px solid #8a3d52;background:#4d2330;border-radius:9px;color:#ffd0d8}.success{padding:12px;border:1px solid #276749;background:#123b2d;border-radius:9px;color:#b9f6d0}.preview{background:#17243b;border-radius:14px;padding:16px;max-width:620px}.tgbtn{display:inline-block;border:1px solid #45628d;border-radius:10px;padding:10px 14px;margin:5px;background:#101c31}.switch{display:flex;gap:8px;align-items:center}@media(max-width:850px){.shell{display:block}.side{width:auto}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:520px){.main{padding:16px}.top{display:block}.grid{grid-template-columns:1fr}.span2{grid-column:span 1}.heading{font-size:24px}}
"""


def db():
    conn = sqlite3.connect(DB, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
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
        conn.execute("CREATE TABLE IF NOT EXISTS manager_config(id INTEGER PRIMARY KEY CHECK(id=1),api_name TEXT DEFAULT '',api_base_url TEXT DEFAULT '',api_key_env TEXT DEFAULT '',updated_at INTEGER)")
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


def page(title, body, active="dashboard", notice=""):
    template = """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{{ title }} · GW Project</title><style>{{ css }}</style></head><body><div class='shell'><aside class='side'><div class='logo'>🛰️ GW-PROJECT</div><div class='muted'>BOT MANAGER CONSOLE</div><nav class='nav'><a class='{{ 'active' if active == 'dashboard' else '' }}' href='{{ url_for('manager.dashboard') }}'>◈ Dashboard</a><a class='{{ 'active' if active == 'users' else '' }}' href='{{ url_for('manager.users') }}'>♙ Users & Roles</a><a class='{{ 'active' if active == 'menus' else '' }}' href='{{ url_for('manager.menus') }}'>▦ Menu Center</a><a class='{{ 'active' if active == 'config' else '' }}' href='{{ url_for('manager.config') }}'>⚙ API Configuration</a><a class='{{ 'active' if active == 'backups' else '' }}' href='{{ url_for('manager.backups') }}'>◫ Backup & Rollback</a><a class='{{ 'active' if active == 'logs' else '' }}' href='{{ url_for('manager.logs') }}'>≡ Activity Logs</a></nav><br><a class='btn' href='{{ url_for('manager.logout') }}'>↪ Logout</a></aside><main class='main'><div class='top'><div><div class='muted'>GW Project / Control Center</div><div class='heading'>{{ title }}</div><div class='muted'>Manage menus, buttons, roles and releases.</div></div><div class='pill'><span class='dot'></span> Application online</div></div>{% if notice %}<div class='success'>{{ notice|safe }}</div><br>{% endif %}{{ body|safe }}</main></div></body></html>"""
    return render_template_string(template, title=title, body=body, active=active, css=CSS, notice=notice)


def field(name, value="", label=None, kind="text", required=True):
    req = " required" if required else ""
    return "<label>" + esc(label or name) + "<input class='input' name='" + esc(name) + "' type='" + esc(kind) + "' value='" + esc(value) + "'" + req + "></label>"


def seed():
    ensure()
    with db() as conn:
        if conn.execute("SELECT COUNT(*) FROM manager_menus").fetchone()[0] == 0:
            for index, (name, desc) in enumerate((("Main Menu", "Menu utama bot"), ("Tools", "Daftar tools aktif"), ("Settings", "Pengaturan bot"), ("Help", "Help and information"))):
                conn.execute("INSERT INTO manager_menus(name,description,sort_order,updated_at) VALUES(?,?,?,?,?)", (name, desc, index, now()))
            conn.commit()


def snapshot():
    ensure()
    with db() as conn:
        menus = conn.execute("SELECT * FROM manager_menus ORDER BY sort_order,id").fetchall()
        out = []
        for m in menus:
            buttons = conn.execute("SELECT * FROM manager_buttons WHERE menu_id=? ORDER BY sort_order,id", (m["id"],)).fetchall()
            out.append({"id": m["id"], "name": m["name"], "description": m["description"], "active": bool(m["active"]), "sort_order": m["sort_order"], "buttons": [dict(b) for b in buttons]})
        return out


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
    msg = "<div class='alert'>" + esc(error) + "</div>" if error else ""
    body = "<div class='card' style='max-width:440px;margin:10vh auto'><div class='logo'>🛰️ GW-PROJECT BOT MANAGER</div><p class='muted'>Secure administrator sign-in</p>" + msg + "<form class='form' method='post'><input class='input' name='username' placeholder='Username' required><input class='input' name='password' type='password' placeholder='Password' required><button class='btn primary'>Sign in</button></form></div>"
    return render_template_string("<style>{{ css }}</style><main class='main'>" + body + "</main>", css=CSS)


@manager.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("manager.login"))


@manager.get("/")
@logged
def dashboard():
    seed()
    with db() as conn:
        menus_count = conn.execute("SELECT COUNT(*) FROM manager_menus").fetchone()[0]
        buttons_count = conn.execute("SELECT COUNT(*) FROM manager_buttons").fetchone()[0]
        audit_count = conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
        users_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone() else 0
    body = "<div class='grid'>"
    for label, value in (("Menus", menus_count), ("Buttons", buttons_count), ("Bot users", users_count), ("Audit events", audit_count)):
        body += "<div class='card'><div class='muted'>" + label + "</div><div class='kpi'>" + str(value) + "</div></div>"
    body += "<div class='card span2'><h3 class='title'>Quick actions</h3><div class='actions'><a class='btn primary' href='" + url_for('manager.menu_new') + "'>+ Add menu</a><a class='btn' href='" + url_for('manager.menus') + "'>Menu Center</a><a class='btn' href='" + url_for('manager.backups') + "'>Backup / Rollback</a></div></div>"
    body += "<div class='card span2'><h3 class='title'>Release status</h3><p class='muted'>Draft tersimpan di SQLite. Publish membuat backup lalu menulis menu_config.json.</p><span class='tag'>Secrets hidden</span> <span class='tag'>Admin protected</span> <span class='tag'>Backup enabled</span></div></div>"
    return page("Dashboard", body)


@manager.get("/menus")
@logged
def menus():
    seed(); rows = ""
    for m in snapshot():
        status = "Active" if m["active"] else "Disabled"
        toggle = "Disable" if m["active"] else "Enable"
        rows += "<tr><td><strong>" + esc(m["name"]) + "</strong><div class='hint'>" + esc(m["description"]) + "</div></td><td>" + str(len(m["buttons"])) + "</td><td>" + status + "</td><td><div class='actions'><a class='btn' href='" + url_for('manager.menu_edit', menu_id=m['id']) + "'>Edit</a><a class='btn' href='" + url_for('manager.button_new', menu_id=m['id']) + "'>+ Button</a><a class='btn' href='" + url_for('manager.preview', menu_id=m['id']) + "'>Preview</a><form method='post' action='" + url_for('manager.menu_toggle', menu_id=m['id']) + "'><button class='btn' type='submit'>" + toggle + "</button></form></div></td></tr>"
    body = "<div class='card'><div class='actions'><div><h3 class='title'>Menu Center</h3><div class='muted'>Create, edit, reorder, enable or disable menus and buttons.</div></div><a class='btn primary' href='" + url_for('manager.menu_new') + "'>+ Add menu</a></div><br><div class='table-wrap'><table class='table'><tr><th>Menu</th><th>Buttons</th><th>Status</th><th>Actions</th></tr>" + (rows or "<tr><td colspan='4'>No menus.</td></tr>") + "</table></div><br><div class='actions'><a class='btn primary' href='" + url_for('manager.publish') + "'>Publish changes</a><a class='btn' href='" + url_for('manager.preview') + "'>Preview Telegram</a></div></div>"
    return page("Menu Center", body, "menus")


@manager.route("/menus/new", methods=["GET", "POST"])
@logged
def menu_new():
    if request.method == "POST":
        with db() as conn:
            conn.execute("INSERT INTO manager_menus(name,description,active,sort_order,updated_at) VALUES(?,?,?,?,?)", (request.form["name"].strip(), request.form.get("description", "").strip(), 1, 999, now()))
            conn.commit()
        audit("menu_created"); return redirect(url_for("manager.menus"))
    body = "<div class='card'><h3 class='title'>Add menu</h3><form class='form' method='post'>" + field("name", label="Menu name") + field("description", label="Description", required=False) + "<button class='btn primary'>Save menu</button></form></div>"
    return page("Add Menu", body, "menus")


@manager.route("/menus/<int:menu_id>/edit", methods=["GET", "POST"])
@logged
def menu_edit(menu_id):
    with db() as conn: menu = conn.execute("SELECT * FROM manager_menus WHERE id=?", (menu_id,)).fetchone()
    if not menu: return "Menu not found", 404
    if request.method == "POST":
        with db() as conn:
            conn.execute("UPDATE manager_menus SET name=?,description=?,sort_order=?,updated_at=? WHERE id=?", (request.form["name"].strip(), request.form.get("description", "").strip(), int(request.form.get("sort_order", 0)), now(), menu_id)); conn.commit()
        audit("menu_updated"); return redirect(url_for("manager.menus"))
    body = "<div class='card'><h3 class='title'>Edit menu</h3><form class='form' method='post'>" + field("name", menu["name"], "Menu name") + field("description", menu["description"], "Description", required=False) + field("sort_order", menu["sort_order"], "Order", "number") + "<button class='btn primary'>Save changes</button></form><br><form method='post' action='" + url_for('manager.menu_delete', menu_id=menu_id) + "'><button class='btn danger'>Delete menu</button></form></div>"
    return page("Edit Menu", body, "menus")


@manager.post("/menus/<int:menu_id>/toggle")
@logged
def menu_toggle(menu_id):
    with db() as conn: conn.execute("UPDATE manager_menus SET active=CASE active WHEN 1 THEN 0 ELSE 1 END,updated_at=? WHERE id=?", (now(), menu_id)); conn.commit()
    audit("menu_toggled"); return redirect(url_for("manager.menus"))


@manager.post("/menus/<int:menu_id>/delete")
@logged
def menu_delete(menu_id):
    with db() as conn: conn.execute("DELETE FROM manager_menus WHERE id=?", (menu_id,)); conn.commit()
    audit("menu_deleted"); return redirect(url_for("manager.menus"))


@manager.route("/menus/<int:menu_id>/buttons/new", methods=["GET", "POST"])
@logged
def button_new(menu_id):
    if request.method == "POST":
        with db() as conn:
            conn.execute("INSERT INTO manager_buttons(menu_id,label,callback,button_type,url,active,sort_order) VALUES(?,?,?,?,?,?,?)", (menu_id, request.form["label"].strip(), request.form.get("callback", "").strip(), request.form.get("button_type", "callback"), request.form.get("url", "").strip(), 1, int(request.form.get("sort_order", 0)))); conn.commit()
        audit("button_created"); return redirect(url_for("manager.menus"))
    body = "<div class='card'><h3 class='title'>Add button</h3><form class='form' method='post'>" + field("label", label="Button text") + field("callback", label="Callback", required=False) + field("url", label="URL", required=False) + "<label>Type<select class='select' name='button_type'><option value='callback'>Callback</option><option value='url'>URL</option></select></label>" + field("sort_order", 0, "Order", "number") + "<button class='btn primary'>Save button</button></form></div>"
    return page("Add Button", body, "menus")


@manager.route("/buttons/<int:button_id>/edit", methods=["GET", "POST"])
@logged
def button_edit(button_id):
    with db() as conn: b = conn.execute("SELECT * FROM manager_buttons WHERE id=?", (button_id,)).fetchone()
    if not b: return "Button not found", 404
    if request.method == "POST":
        with db() as conn:
            conn.execute("UPDATE manager_buttons SET label=?,callback=?,button_type=?,url=?,sort_order=?,active=? WHERE id=?", (request.form["label"].strip(), request.form.get("callback", "").strip(), request.form.get("button_type", "callback"), request.form.get("url", "").strip(), int(request.form.get("sort_order", 0)), 1 if request.form.get("active") else 0, button_id)); conn.commit()
        audit("button_updated"); return redirect(url_for("manager.menus"))
    body = "<div class='card'><h3 class='title'>Edit button</h3><form class='form' method='post'>" + field("label", b["label"], "Button text") + field("callback", b["callback"], "Callback", required=False) + field("url", b["url"], "URL", required=False) + "<label>Type<select class='select' name='button_type'><option value='callback' " + ("selected" if b["button_type"] == "callback" else "") + ">Callback</option><option value='url' " + ("selected" if b["button_type"] == "url" else "") + ">URL</option></select></label>" + field("sort_order", b["sort_order"], "Order", "number") + "<label class='switch'><input type='checkbox' name='active' " + ("checked" if b["active"] else "") + "> Active</label><button class='btn primary'>Save button</button></form></div>"
    return page("Edit Button", body, "menus")


@manager.get("/preview")
@manager.get("/preview/<int:menu_id>")
@logged
def preview(menu_id=None):
    items = snapshot(); m = next((x for x in items if x["id"] == menu_id), None) if menu_id else (items[0] if items else None)
    if not m: return page("Telegram Preview", "<div class='card'>No menu available.</div>", "menus")
    buttons = "".join("<span class='tgbtn'>" + esc(b["label"]) + "</span>" for b in m["buttons"] if b["active"])
    body = "<div class='preview'><div class='muted'>Telegram preview · " + esc(m["name"]) + "</div><h2>" + esc(m["name"]) + "</h2><p>" + esc(m["description"]) + "</p>" + buttons + "</div><br><a class='btn' href='" + url_for('manager.menus') + "'>Back to editor</a>"
    return page("Telegram Preview", body, "menus")


@manager.get("/publish")
@logged
def publish():
    ensure(); BACKUP_DIR.mkdir(exist_ok=True)
    if PUBLISHED.exists(): shutil.copy2(PUBLISHED, BACKUP_DIR / ("menu_config_" + str(now()) + ".json"))
    PUBLISHED.write_text(json.dumps(snapshot(), ensure_ascii=False, indent=2), encoding="utf-8")
    audit("configuration_published"); return redirect(url_for("manager.menus"))


@manager.get("/backups")
@logged
def backups():
    files = sorted(BACKUP_DIR.glob("menu_config_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    rows = "".join("<tr><td>" + esc(p.name) + "</td><td>" + time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime)) + "</td><td><form method='post' action='" + url_for('manager.rollback', filename=p.name) + "'><button class='btn'>Rollback</button></form></td></tr>" for p in files)
    body = "<div class='card'><h3 class='title'>Backup & Rollback</h3><p class='muted'>Publish otomatis membuat backup konfigurasi aktif.</p><div class='table-wrap'><table class='table'><tr><th>Backup</th><th>Created</th><th>Action</th></tr>" + (rows or "<tr><td colspan='3'>No backups yet.</td></tr>") + "</table></div></div>"
    return page("Backup & Rollback", body, "backups")


@manager.post("/backups/<path:filename>/rollback")
@logged
def rollback(filename):
    candidate = (BACKUP_DIR / filename).resolve()
    if candidate.parent != BACKUP_DIR.resolve() or not candidate.name.startswith("menu_config_") or not candidate.exists(): return "Backup not found", 404
    shutil.copy2(candidate, PUBLISHED); audit("configuration_rollback"); return redirect(url_for("manager.backups"))


@manager.get("/config")
@logged
def config():
    with db() as conn: row = conn.execute("SELECT * FROM manager_config WHERE id=1").fetchone()
    values = row or {"api_name":"", "api_base_url":"", "api_key_env":""}
    if request.method == "POST": pass
    body = "<div class='card'><h3 class='title'>API Configuration</h3><p class='muted'>Simpan nama environment variable saja. Jangan masukkan token atau secret ke dashboard.</p><form class='form' method='post'>" + field("api_name", values["api_name"], "API name", required=False) + field("api_base_url", values["api_base_url"], "Base URL", required=False) + field("api_key_env", values["api_key_env"], "Secret variable name", required=False) + "<button class='btn primary'>Save configuration</button></form></div>"
    return page("API Configuration", body, "config")


@manager.post("/config")
@logged
def config_save():
    with db() as conn:
        conn.execute("INSERT INTO manager_config(id,api_name,api_base_url,api_key_env,updated_at) VALUES(1,?,?,?,?) ON CONFLICT(id) DO UPDATE SET api_name=excluded.api_name,api_base_url=excluded.api_base_url,api_key_env=excluded.api_key_env,updated_at=excluded.updated_at", (request.form.get("api_name", "").strip(), request.form.get("api_base_url", "").strip(), request.form.get("api_key_env", "").strip(), now())); conn.commit()
    audit("api_configuration_updated"); return redirect(url_for("manager.config"))


@manager.get("/users")
@logged
def users():
    body = "<div class='card'><h3 class='title'>Users & Roles</h3><p class='muted'>Dashboard login dikendalikan oleh DASHBOARD_USERNAME dan DASHBOARD_PASSWORD di cPanel. Jangan menyimpan password di GitHub.</p><span class='tag'>Administrator protected</span></div>"
    return page("Users & Roles", body, "users")


@manager.get("/logs")
@logged
def logs():
    ensure()
    with db() as conn: rows = conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 200").fetchall()
    body = "<div class='card'><h3 class='title'>Activity Logs</h3><div class='table-wrap'><table class='table'><tr><th>User</th><th>Action</th><th>Time</th></tr>" + "".join("<tr><td>" + esc(r["user_id"]) + "</td><td>" + esc(r["action"]) + "</td><td>" + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["created_at"])) + "</td></tr>" for r in rows) + "</table></div></div>"
    return page("Activity Logs", body, "logs")
