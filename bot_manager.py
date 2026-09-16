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
:root{font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;color:#eaf1ff;background:#080d19}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 0 0,#1b2c50,#080d19 48%);min-height:100vh}a{color:inherit}.shell{display:flex;min-height:100vh}.side{width:250px;background:#0a1020;border-right:1px solid #263653;padding:24px 16px;position:sticky;top:0;height:100vh}.logo{font-size:19px;font-weight:900}.sub,.muted,.hint{color:#91a4c4;font-size:12px}.nav{display:grid;gap:7px;margin-top:30px}.nav a{padding:12px;border-radius:11px;text-decoration:none;color:#a9b9d3}.nav a:hover,.nav a.active{background:#20365e;color:#fff}.side-bottom{position:absolute;bottom:20px;left:16px;right:16px}.main{flex:1;min-width:0;padding:30px}.top{display:flex;justify-content:space-between;gap:20px;align-items:start;margin-bottom:24px}.eyebrow{font-size:11px;letter-spacing:1.5px;color:#7f9ed1;text-transform:uppercase}.heading{font-size:30px;font-weight:900;margin:6px 0}.pill,.tag{display:inline-block;border:1px solid #33496d;background:#111e35;border-radius:999px;padding:7px 11px;font-size:12px}.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#34d399;margin-right:6px}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}.card{background:linear-gradient(145deg,#14213a,#0e1729);border:1px solid #2b3d5c;border-radius:18px;padding:20px;box-shadow:0 12px 35px #0003}.span2{grid-column:span 2}.span4{grid-column:span 4}.kpi{font-size:31px;font-weight:900;margin-top:10px}.title{font-size:17px;font-weight:800;margin:0 0 5px}.actions{display:flex;gap:9px;flex-wrap:wrap}.btn{display:inline-block;border:1px solid #385078;background:#101c31;color:#edf4ff;border-radius:10px;padding:10px 13px;text-decoration:none;font-size:13px;cursor:pointer}.btn.primary{background:#326ff0;border-color:#4b83ff}.btn.danger{background:#542533;border-color:#8a3d52}.form{display:grid;gap:12px;max-width:700px}.input,.select,.textarea{width:100%;padding:11px 12px;background:#0a1426;color:#eef5ff;border:1px solid #385078;border-radius:10px}.textarea{min-height:100px;resize:vertical}.table-wrap{overflow:auto;border:1px solid #2b3d5c;border-radius:12px}.table{width:100%;border-collapse:collapse;min-width:650px}.table th,.table td{padding:12px 13px;border-bottom:1px solid #263750;text-align:left;font-size:13px;vertical-align:top}.table th{background:#101b30;color:#9db2d5}.alert{padding:12px;border:1px solid #8a3d52;background:#4d2330;border-radius:10px;color:#ffd0d8}.empty{text-align:center;padding:25px;color:#91a4c4}.footer{font-size:11px;color:#7186a8;line-height:1.6;margin-top:18px}@media(max-width:1000px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.span4{grid-column:span 2}}@media(max-width:650px){.shell{display:block}.side{width:auto;height:auto;position:static}.side-bottom{display:none}.main{padding:18px}.top{flex-direction:column}.grid{grid-template-columns:1fr}.span2,.span4{grid-column:span 1}.heading{font-size:25px}}
"""

def db():
    c=sqlite3.connect(DB,timeout=15)
    c.row_factory=sqlite3.Row
    return c

def now(): return int(time.time())

def audit(action):
    ensure()
    with db() as c:c.execute("INSERT INTO audit(user_id,action,created_at) VALUES(?,?,?)",(session.get("manager_user","admin"),action,now()))

def ensure():
    BACKUP_DIR.mkdir(exist_ok=True)
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT,action TEXT,created_at INTEGER)")
        c.execute("CREATE TABLE IF NOT EXISTS manager_menus(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,description TEXT DEFAULT '',active INTEGER DEFAULT 1,sort_order INTEGER DEFAULT 0,updated_at INTEGER)")
        c.execute("CREATE TABLE IF NOT EXISTS manager_buttons(id INTEGER PRIMARY KEY AUTOINCREMENT,menu_id INTEGER NOT NULL,label TEXT NOT NULL,callback TEXT DEFAULT '',button_type TEXT DEFAULT 'callback',url TEXT DEFAULT '',active INTEGER DEFAULT 1,sort_order INTEGER DEFAULT 0,FOREIGN KEY(menu_id) REFERENCES manager_menus(id) ON DELETE CASCADE)")
        c.commit()

def logged(fn):
    @wraps(fn)
    def w(*a,**k):
        if not session.get("manager_auth"): return redirect(url_for("manager.login",next=request.path))
        return fn(*a,**k)
    return w

def page(title,body,active="dashboard"):
    tpl="""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{{title}} · GW Project</title><style>{{css}}</style></head><body><div class='shell'><aside class='side'><div class='logo'>🛰️ GW-PROJECT</div><div class='sub'>BOT MANAGER CONSOLE</div><nav class='nav'>
<a class='{{"active" if active=="dashboard" else ""}}' href='{{url_for("manager.dashboard")}}'>◈ Dashboard</a><a class='{{"active" if active=="users" else ""}}' href='{{url_for("manager.users")}}'>♙ Users & Roles</a><a class='{{"active" if active=="menus" else ""}}' href='{{url_for("manager.menus")}}'>▦ Menu Center</a><a class='{{"active" if active=="config" else ""}}' href='{{url_for("manager.config")}}'>⚙ API Configuration</a><a class='{{"active" if active=="backups" else ""}}' href='{{url_for("manager.backups")}}'>◫ Backup & Rollback</a><a class='{{"active" if active=="logs" else ""}}' href='{{url_for("manager.logs")}}'>≡ Activity Logs</a></nav><div class='side-bottom'><a class='btn' style='width:100%' href='{{url_for("manager.logout")}}'>↪ Logout</a><div class='footer'>Secrets remain in cPanel environment variables.</div></div></aside><main class='main'><div class='top'><div><div class='eyebrow'>GW Project / Control Center</div><div class='heading'>{{title}}</div><div class='muted'>Manage menus, buttons, roles and releases.</div></div><div class='pill'><span class='dot'></span> Application online</div></div>{{body|safe}}</main></div></body></html>"""
    return render_template_string(tpl,title=title,body=body,active=active,css=CSS)

def esc(v): return html.escape(str(v or ""))
def form_input(name,value="",label=None,kind="text"):
    return f"<label>{esc(label or name)}<input class='input' name='{esc(name)}' type='{kind}' value='{esc(value)}' required></label>"

def menu_snapshot():
    ensure()
    with db() as c:
        ms=c.execute("SELECT * FROM manager_menus ORDER BY sort_order,id").fetchall()
        out=[]
        for m in ms:
            bs=c.execute("SELECT * FROM manager_buttons WHERE menu_id=? ORDER BY sort_order,id",(m['id'],)).fetchall()
            out.append({'id':m['id'],'name':m['name'],'description':m['description'],'active':bool(m['active']),'sort_order':m['sort_order'],'buttons':[dict(b) for b in bs]})
        return out

def seed():
    ensure()
    with db() as c:
        if c.execute('SELECT COUNT(*) n FROM manager_menus').fetchone()['n']==0:
            for i,(n,d) in enumerate([('Main Menu','Start / Home'),('Tools','Tool selection'),('Settings','User settings'),('Help','Help and information')]): c.execute('INSERT INTO manager_menus(name,description,sort_order,updated_at) VALUES(?,?,?,?,?)',(n,d,i,now()))
            c.commit()

@manager.route('/login',methods=['GET','POST'])
def login():
    error=''
    if request.method=='POST':
        u=request.form.get('username','');p=request.form.get('password','')
        if LOGIN_PASSWORD and hmac.compare_digest(u,LOGIN_USER) and hmac.compare_digest(p,LOGIN_PASSWORD):
            session['manager_auth']=True;session['manager_user']=u;audit('dashboard_login');return redirect(request.args.get('next') or url_for('manager.dashboard'))
        error='Username atau password salah. Pastikan environment variables cPanel sudah diisi.'
    msg=f"<div class='alert'>{esc(error)}</div>" if error else ''
    return render_template_string("<style>{{css}}</style><main class='main'><div class='card' style='max-width:440px;margin:10vh auto'><div class='logo'>🛰️ GW-PROJECT BOT MANAGER</div><p class='muted'>Secure administrator sign-in</p>{{msg}}<form class='form' method='post'><input class='input' name='username' placeholder='Username' required><input class='input' name='password' type='password' placeholder='Password' required><button class='btn primary'>Sign in</button></form></div></main>",css=CSS,msg=msg)

@manager.get('/logout')
def logout(): session.clear();return redirect(url_for('manager.login'))

@manager.get('/')
@logged
def dashboard():
    seed()
    with db() as c:
        menus=c.execute('SELECT COUNT(*) n FROM manager_menus').fetchone()['n'];buttons=c.execute('SELECT COUNT(*) n FROM manager_buttons').fetchone()['n'];audits=c.execute('SELECT COUNT(*) n FROM audit').fetchone()['n'];users=c.execute("SELECT COUNT(*) n FROM users").fetchone()['n'] if c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone() else 0
    b=f"<div class='grid'><div class='card'><div class='muted'>Menus</div><div class='kpi'>{menus}</div></div><div class='card'><div class='muted'>Buttons</div><div class='kpi'>{buttons}</div></div><div class='card'><div class='muted'>Bot users</div><div class='kpi'>{users}</div></div><div class='card'><div class='muted'>Audit events</div><div class='kpi'>{audits}</div></div><div class='card span2'><h3 class='title'>Quick actions</h3><div class='actions'><a class='btn primary' href='{url_for("manager.menu_new")}'>+ Add menu</a><a class='btn' href='{url_for("manager.menus")}'>Menu Center</a><a class='btn' href='{url_for("manager.backups")}'>Backup / Rollback</a></div></div><div class='card span2'><h3 class='title'>Release status</h3><p class='muted'>Changes are saved as drafts in SQLite. Use Publish to write the active menu configuration to menu_config.json.</p><span class='tag'>Secrets hidden</span> <span class='tag'>Admin protected</span> <span class='tag'>Backup enabled</span></div></div>"
    return page('Dashboard',b)

@manager.get('/menus')
@logged
def menus():
    seed();ms=menu_snapshot();rows=''
    for m in ms:
        rows+=f"<tr><td><strong>{esc(m['name'])}</strong><div class='hint'>{esc(m['description'])}</div></td><td>{len(m['buttons'])}</td><td>{'Active' if m['active'] else 'Disabled'}</td><td><div class='actions'><a class='btn' href='{url_for('manager.menu_edit',menu_id=m['id'])}'>Edit</a><a class='btn' href='{url_for('manager.button_new',menu_id=m['id'])}'>+ Button</a><a class='btn' href='{url_for('manager.preview',menu_id=m['id'])}'>Preview</a><form method='post' action='{url_for('manager.menu_toggle',menu_id=m['id'])}'><button class='btn' type='submit'>{'Disable' if m['active'] else 'Enable'}</button></form></div></td></tr>"
    b=f"<div class='card'><div class='actions' style='justify-content:space-between'><div><h3 class='title'>Menu Center</h3><div class='muted'>Create, edit, reorder, enable or disable menus and buttons.</div></div><a class='btn primary' href='{url_for('manager.menu_new')}'>+ Add menu</a></div><br><div class='table-wrap'><table class='table'><tr><th>Menu</th><th>Buttons</th><th>Status</th><th>Actions</th></tr>{rows or '<tr><td colspan=4 class=empty>No menus.</td></tr>'}</table></div><br><div class='actions'><a class='btn primary' href='{url_for('manager.publish')}'>Publish changes</a><a class='btn' href='{url_for('manager.preview')}'>Preview Telegram</a></div></div>"
    return page('Menu Center',b,'menus')

@manager.route('/menus/new',methods=['GET','POST'])
@logged
def menu_new():
    if request.method=='POST':
        with db() as c:c.execute('INSERT INTO manager_menus(name,description,active,sort_order,updated_at) VALUES(?,?,?,?,?)',(request.form['name'],request.form.get('description',''),1,999,now()))
        audit('menu_created');return redirect(url_for('manager.menus'))
    b=f"<div class='card'><h3 class='title'>Add menu</h3><form class='form' method='post'>{form_input('name',label='Menu name')}{form_input('description',label='Description')}<button class='btn primary'>Save menu</button></form></div>"
    return page('Add Menu',b,'menus')

@manager.route('/menus/<int:menu_id>/edit',methods=['GET','POST'])
@logged
def menu_edit(menu_id):
    with db() as c:m=c.execute('SELECT * FROM manager_menus WHERE id=?',(menu_id,)).fetchone()
    if not m:return 'Menu not found',404
    if request.method=='POST':
        with db() as c:c.execute('UPDATE manager_menus SET name=?,description=?,sort_order=?,updated_at=? WHERE id=?',(request.form['name'],request.form.get('description',''),int(request.form.get('sort_order',0)),now(),menu_id))
        audit('menu_updated');return redirect(url_for('manager.menus'))
    b=f"<div class='card'><h3 class='title'>Edit menu</h3><form class='form' method='post'>{form_input('name',m['name'],'Menu name')}{form_input('description',m['description'],'Description')}{form_input('sort_order',m['sort_order'],'Order','number')}<button class='btn primary'>Save changes</button></form><br><form method='post' action='{url_for('manager.menu_delete',menu_id=menu_id)}'><button class='btn danger'>Delete menu</button></form></div>"
    return page('Edit Menu',b,'menus')

@manager.post('/menus/<int:menu_id>/toggle')
@logged
def menu_toggle(menu_id):
    with db() as c:c.execute('UPDATE manager_menus SET active=CASE active WHEN 1 THEN 0 ELSE 1 END,updated_at=? WHERE id=?',(now(),menu_id))
    audit('menu_toggled');return redirect(url_for('manager.menus'))

@manager.post('/menus/<int:menu_id>/delete')
@logged
def menu_delete(menu_id):
    with db() as c:c.execute('DELETE FROM manager_menus WHERE id=?',(menu_id,))
    audit('menu_deleted');return redirect(url_for('manager.menus'))

@manager.route('/menus/<int:menu_id>/buttons/new',methods=['GET','POST'])
@logged
def button_new(menu_id):
    if request.method=='POST':
        with db() as c:c.execute('INSERT INTO manager_buttons(menu_id,label,callback,button_type,url,active,sort_order) VALUES(?,?,?,?,?,?,?)',(menu_id,request.form['label'],request.form.get('callback',''),request.form.get('button_type','callback'),request.form.get('url',''),1,int(request.form.get('sort_order',999))))
        audit('button_created');return redirect(url_for('manager.menus'))
    b=f"<div class='card'><h3 class='title'>Add button</h3><form class='form' method='post'>{form_input('label',label='Button text')}{form_input('callback',label='Callback data')}{form_input('button_type','callback','Button type')}{form_input('url',label='URL (optional)')}{form_input('sort_order',999,'Order','number')}<button class='btn primary'>Save button</button></form></div>"
    return page('Add Button',b,'menus')

@manager.route('/buttons/<int:button_id>/edit',methods=['GET','POST'])
@logged
def button_edit(button_id):
    with db() as c:b=c.execute('SELECT * FROM manager_buttons WHERE id=?',(button_id,)).fetchone()
    if not b:return 'Button not found',404
    if request.method=='POST':
        with db() as c:c.execute('UPDATE manager_buttons SET label=?,callback=?,button_type=?,url=?,sort_order=?,active=? WHERE id=?',(request.form['label'],request.form.get('callback',''),request.form.get('button_type','callback'),request.form.get('url',''),int(request.form.get('sort_order',0)),1 if request.form.get('active') else 0,button_id))
        audit('button_updated');return redirect(url_for('manager.menus'))
    checked='checked' if b['active'] else ''
    bdy=f"<div class='card'><h3 class='title'>Edit button</h3><form class='form' method='post'>{form_input('label',b['label'],'Button text')}{form_input('callback',b['callback'],'Callback data')}{form_input('button_type',b['button_type'],'Button type')}{form_input('url',b['url'],'URL')}{form_input('sort_order',b['sort_order'],'Order','number')}<label><input type='checkbox' name='active' {checked}> Active</label><button class='btn primary'>Save button</button></form><br><form method='post' action='{url_for('manager.button_delete',button_id=button_id)}'><button class='btn danger'>Delete button</button></form></div>"
    return page('Edit Button',bdy,'menus')

@manager.post('/buttons/<int:button_id>/delete')
@logged
def button_delete(button_id):
    with db() as c:c.execute('DELETE FROM manager_buttons WHERE id=?',(button_id,))
    audit('button_deleted');return redirect(url_for('manager.menus'))

@manager.get('/preview')
@logged
def preview():
    ms=menu_snapshot();selected=request.args.get('menu_id');m=next((x for x in ms if str(x['id'])==selected),ms[0] if ms else None)
    if not m:return page('Telegram Preview',"<div class='card empty'>No menu available.</div>",'menus')
    buttons=''.join(f"<div class='btn' style='margin:5px'>{esc(x['label'])}</div>" for x in m['buttons'] if x['active'])
    b=f"<div class='card' style='max-width:560px'><div class='muted'>Telegram preview · {esc(m['name'])}</div><h3 class='title'>{esc(m['description'] or m['name'])}</h3><div style='background:#17243a;padding:18px;border-radius:12px'>{buttons or '<span class=muted>No active buttons</span>'}</div><br><a class='btn' href='{url_for('manager.menus')}'>Back to editor</a></div>"
    return page('Telegram Preview',b,'menus')

@manager.post('/publish')
@manager.get('/publish')
@logged
def publish():
    ensure();stamp=time.strftime('%Y%m%d_%H%M%S');backup=BACKUP_DIR/f'menu_config_{stamp}.json'
    if PUBLISHED.exists():shutil.copy2(PUBLISHED,backup)
    PUBLISHED.write_text(json.dumps({'version':stamp,'published_at':now(),'menus':menu_snapshot()},ensure_ascii=False,indent=2),encoding='utf-8')
    audit('menu_published');return redirect(url_for('manager.backups'))

@manager.get('/backups')
@logged
def backups():
    files=sorted(BACKUP_DIR.glob('menu_config_*.json'),reverse=True);rows=''.join(f"<tr><td>{esc(x.name)}</td><td>{time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(x.stat().st_mtime))}</td><td><form method='post' action='{url_for('manager.rollback')}?file={esc(x.name)}'><button class='btn'>Rollback</button></form></td></tr>" for x in files)
    b=f"<div class='card'><h3 class='title'>Backup & Rollback</h3><p class='muted'>Every publish keeps the previous menu_config.json. Drafts remain in gwproject.db.</p><div class='actions'><a class='btn primary' href='{url_for('manager.publish')}'>Publish current draft</a></div><br><div class='table-wrap'><table class='table'><tr><th>Backup</th><th>Created</th><th>Action</th></tr>{rows or '<tr><td colspan=3 class=empty>No backups yet.</td></tr>'}</table></div></div>"
    return page('Backup & Rollback',b,'backups')

@manager.post('/rollback')
@logged
def rollback():
    name=Path(request.args.get('file','')).name;src=BACKUP_DIR/name
    if src.exists() and name.startswith('menu_config_'):shutil.copy2(src,PUBLISHED);audit('menu_rollback')
    return redirect(url_for('manager.backups'))

@manager.get('/users')
@logged
def users():
    with db() as c:
        exists=c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone();rows=c.execute('SELECT user_id,role,permissions FROM users ORDER BY rowid DESC LIMIT 300').fetchall() if exists else []
    trs=''.join(f"<tr><td>{esc(r['user_id'])}</td><td>{esc(r['role'])}</td><td>{esc(r['permissions'])}</td><td><a class='btn' href='{url_for('manager.user_edit',user_id=r['user_id'])}'>Edit role</a></td></tr>" for r in rows)
    return page('Users & Roles',f"<div class='card'><h3 class='title'>Users & Roles</h3><div class='muted'>Administrator can edit role and permissions.</div><br><div class='table-wrap'><table class='table'><tr><th>User ID</th><th>Role</th><th>Permissions</th><th>Action</th></tr>{trs or '<tr><td colspan=4 class=empty>No users found.</td></tr>'}</table></div></div>",'users')

@manager.route('/users/<user_id>/edit',methods=['GET','POST'])
@logged
def user_edit(user_id):
    with db() as c:r=c.execute('SELECT user_id,role,permissions FROM users WHERE user_id=?',(user_id,)).fetchone()
    if not r:return 'User not found',404
    if request.method=='POST':
        with db() as c:c.execute('UPDATE users SET role=?,permissions=? WHERE user_id=?',(request.form['role'],request.form.get('permissions',''),user_id))
        audit('user_role_updated');return redirect(url_for('manager.users'))
    b=f"<div class='card'><h3 class='title'>Edit user {esc(user_id)}</h3><form class='form' method='post'>{form_input('role',r['role'],'Role')}{form_input('permissions',r['permissions'],'Permissions') }<button class='btn primary'>Save role</button></form></div>"
    return page('Edit Role',b,'users')

@manager.get('/config')
@logged
def config():
    names=['BOT_TOKEN','WEBHOOK_SECRET','ADMIN_IDS','SEARCH_API_URL','SEARCH_API_TOKEN','SEARCH_API_LIMIT','USERNAME_API_URL','USERNAME_API_TOKEN','TIKTOK_API_URL','TIKTOK_API_TOKEN']
    rows=''.join(f"<tr><td>{n}</td><td>{esc(os.getenv(n)) if n.endswith('_URL') or n in ('ADMIN_IDS','SEARCH_API_LIMIT') else ('[SET]' if os.getenv(n) else '[NOT SET]')}</td></tr>" for n in names)
    return page('API Configuration',f"<div class='card'><h3 class='title'>API Configuration</h3><p class='muted'>Edit secret values only in cPanel Environment Variables.</p><div class='table-wrap'><table class='table'><tr><th>Variable</th><th>Status / value</th></tr>{rows}</table></div></div>",'config')

@manager.get('/logs')
@logged
def logs():
    ensure()
    with db() as c:rows=c.execute('SELECT user_id,action,created_at FROM audit ORDER BY id DESC LIMIT 300').fetchall()
    trs=''.join(f"<tr><td>{time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(r['created_at']))}</td><td>{esc(r['user_id'])}</td><td>{esc(r['action'])}</td></tr>" for r in rows)
    return page('Activity Logs',f"<div class='card'><h3 class='title'>Activity Logs</h3><div class='table-wrap'><table class='table'><tr><th>Time</th><th>User</th><th>Action</th></tr>{trs or '<tr><td colspan=3 class=empty>No logs.</td></tr>'}</table></div></div>",'logs')

@manager.get('/api/health')
@logged
def api_health(): return jsonify({'ok':True,'service':'gwprojectbot-manager','time':now()})
