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
:root{--bg:#080d19;--panel:#111b2f;--panel2:#16243d;--line:#2b4165;--text:#edf4ff;--muted:#91a4c4;--blue:#3478f6;--green:#34d399;--red:#ef6b83}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px Inter,system-ui,Arial,sans-serif}a{color:inherit}.shell{display:flex;min-height:100vh}.side{width:248px;flex:0 0 248px;background:#0b1222;border-right:1px solid #263653;padding:24px 16px}.logo{font-size:20px;font-weight:850;letter-spacing:-.4px}.muted,.hint{color:var(--muted);font-size:12px}.nav{display:grid;gap:6px;margin-top:28px}.nav a{padding:12px;border-radius:10px;text-decoration:none;color:#a9b9d3}.nav a.active,.nav a:hover{background:#20365e;color:#fff}.main{flex:1;min-width:0;padding:30px;max-width:1500px}.top{display:flex;justify-content:space-between;gap:18px;margin-bottom:24px}.heading{font-size:31px;font-weight:850;letter-spacing:-.8px;margin:6px 0}.pill,.tag{display:inline-block;border:1px solid #33496d;background:#111e35;border-radius:999px;padding:7px 11px;font-size:12px}.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--green);margin-right:6px}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}.card{background:linear-gradient(145deg,#14213a,#0e1729);border:1px solid var(--line);border-radius:16px;padding:20px}.span2{grid-column:span 2}.kpi{font-size:31px;font-weight:850;margin-top:8px}.title{font-size:18px;font-weight:800;margin:0 0 8px}.actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.btn{display:inline-block;border:1px solid #385078;background:#101c31;color:var(--text);border-radius:9px;padding:9px 12px;text-decoration:none;font-size:13px;cursor:pointer}.btn.primary{background:var(--blue);border-color:#5a91ff}.btn.danger{background:#542533;border-color:#8a3d52}.btn.small{padding:6px 9px;font-size:12px}.form{display:grid;gap:13px;max-width:850px}.field{display:grid;gap:6px;color:#b7c8e4;font-size:13px}.input,.select,.textarea{width:100%;padding:11px 12px;background:#0a1426;color:#eef5ff;border:1px solid #385078;border-radius:9px}.textarea{min-height:130px;resize:vertical}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:11px}.table{width:100%;border-collapse:collapse;min-width:760px}.table th,.table td{padding:13px;border-bottom:1px solid #263750;text-align:left;vertical-align:middle}.table th{background:#101b30;color:#9db2d5;font-size:12px}.table tr:last-child td{border-bottom:0}.alert{padding:12px;border:1px solid #8a3d52;background:#4d2330;border-radius:9px;color:#ffd0d8}.success{padding:12px;border:1px solid #276749;background:#123b2d;border-radius:9px;color:#b9f6d0}.status{font-size:12px;border-radius:999px;padding:5px 9px;border:1px solid #385078;background:#111e35}.status.on{color:#a9f6d0;border-color:#276749;background:#123b2d}.status.off{color:#ffd0d8;border-color:#8a3d52;background:#4d2330}.preview{background:#17243b;border:1px solid #2b4165;border-radius:15px;padding:18px;max-width:760px}.tgbtn{display:inline-block;border:1px solid #45628d;border-radius:10px;padding:11px 14px;margin:5px;background:#101c31}.section-head{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap}.notice{margin-bottom:16px}.subcard{background:#0d1729;border:1px solid #2b4165;border-radius:12px;padding:15px;margin-top:14px}.danger-text{color:#ff9bad}@media(max-width:950px){.shell{display:block}.side{width:auto}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:560px){.main{padding:16px}.top{display:block}.grid{grid-template-columns:1fr}.span2{grid-column:span 1}.heading{font-size:25px}.card{padding:15px}}
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
        conn.execute("INSERT INTO audit(user_id,action,created_at) VALUES(?,?,?)",(session.get("manager_user","admin"),action,now()))
        conn.commit()


def logged(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("manager_auth"):
            return redirect(url_for("manager.login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def page(title, body, active="dashboard", notice=""):
    template="""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{{title}} · GW Project</title><style>{{css}}</style></head><body><div class='shell'><aside class='side'><div class='logo'>🛰️ GW-PROJECT</div><div class='muted'>BOT MANAGER CONSOLE</div><nav class='nav'><a class='{{"active" if active=="dashboard" else ""}}' href='{{url_for("manager.dashboard")}}'>◈ Dashboard</a><a class='{{"active" if active=="users" else ""}}' href='{{url_for("manager.users")}}'>♙ Users & Roles</a><a class='{{"active" if active=="menus" else ""}}' href='{{url_for("manager.menus")}}'>▦ Menu Center</a><a class='{{"active" if active=="config" else ""}}' href='{{url_for("manager.config")}}'>⚙ API Configuration</a><a class='{{"active" if active=="backups" else ""}}' href='{{url_for("manager.backups")}}'>◫ Backup & Rollback</a><a class='{{"active" if active=="logs" else ""}}' href='{{url_for("manager.logs")}}'>≡ Activity Logs</a></nav><br><a class='btn' href='{{url_for("manager.logout")}}'>↪ Logout</a></aside><main class='main'><div class='top'><div><div class='muted'>GW Project / Control Center</div><div class='heading'>{{title}}</div><div class='muted'>Kelola menu, tombol, callback, urutan, publish dan backup bot.</div></div><div class='pill'><span class='dot'></span> Application online</div></div>{%if notice%}<div class='success notice'>{{notice|safe}}</div>{%endif%}{{body|safe}}</main></div></body></html>"""
    return render_template_string(template,title=title,body=body,active=active,css=CSS,notice=notice)


def field(name,value="",label=None,kind="text",required=False,placeholder=""):
    req=" required" if required else ""
    return f"<label class='field'>{esc(label or name)}<input class='input' name='{esc(name)}' type='{esc(kind)}' value='{esc(value)}' placeholder='{esc(placeholder)}'{req}></label>"


def seed():
    ensure()
    with db() as conn:
        if conn.execute("SELECT COUNT(*) FROM manager_menus").fetchone()[0]==0:
            for i,(name,desc) in enumerate((("Main Menu","Menu utama bot"),("Tools","Daftar tools aktif"),("Settings","Pengaturan bot"),("Help","Help and information"))):
                conn.execute("INSERT INTO manager_menus(name,description,sort_order,updated_at) VALUES(?,?,?,?,?)",(name,desc,i,now()))
            conn.commit()


def snapshot():
    ensure(); out=[]
    with db() as conn:
        menus=conn.execute("SELECT * FROM manager_menus ORDER BY sort_order,id").fetchall()
        for m in menus:
            bs=conn.execute("SELECT * FROM manager_buttons WHERE menu_id=? ORDER BY sort_order,id",(m['id'],)).fetchall()
            out.append({"id":m['id'],"name":m['name'],"description":m['description'],"active":bool(m['active']),"sort_order":m['sort_order'],"buttons":[dict(b) for b in bs]})
    return out


@manager.route('/login',methods=['GET','POST'])
def login():
    error=''
    if request.method=='POST':
        u=request.form.get('username',''); p=request.form.get('password','')
        if LOGIN_PASSWORD and hmac.compare_digest(u,LOGIN_USER) and hmac.compare_digest(p,LOGIN_PASSWORD):
            session['manager_auth']=True; session['manager_user']=u; audit('dashboard_login')
            return redirect(request.args.get('next') or url_for('manager.dashboard'))
        error='Username atau password salah. Atur DASHBOARD_USERNAME dan DASHBOARD_PASSWORD di cPanel.'
    msg=f"<div class='alert'>{esc(error)}</div>" if error else ''
    body=f"<div class='card' style='max-width:440px;margin:10vh auto'><div class='logo'>🛰️ GW-PROJECT BOT MANAGER</div><p class='muted'>Secure administrator sign-in</p>{msg}<form class='form' method='post'>{field('username',label='Username',required=True)}{field('password',label='Password',kind='password',required=True)}<button class='btn primary'>Sign in</button></form></div>"
    return render_template_string("<style>{{css}}</style><main class='main'>"+body+"</main>",css=CSS)


@manager.get('/logout')
def logout():
    session.clear(); return redirect(url_for('manager.login'))


@manager.get('/')
@logged
def dashboard():
    seed()
    with db() as conn:
        mc=conn.execute('SELECT COUNT(*) FROM manager_menus').fetchone()[0]; bc=conn.execute('SELECT COUNT(*) FROM manager_buttons').fetchone()[0]; ac=conn.execute('SELECT COUNT(*) FROM audit').fetchone()[0]
        uc=conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone() else 0
    body="<div class='grid'>"+''.join(f"<div class='card'><div class='muted'>{l}</div><div class='kpi'>{v}</div></div>" for l,v in (("Menus",mc),("Buttons",bc),("Bot users",uc),("Audit events",ac)))
    body+="<div class='card span2'><h3 class='title'>Quick actions</h3><div class='actions'><a class='btn primary' href='"+url_for('manager.menu_new')+"'>＋ Tambah menu</a><a class='btn' href='"+url_for('manager.menus')+"'>Menu Center</a><a class='btn' href='"+url_for('manager.backups')+"'>Backup / Rollback</a></div></div><div class='card span2'><h3 class='title'>Release status</h3><p class='muted'>Perubahan disimpan sebagai draft di SQLite. Publish membuat backup otomatis dan menulis menu_config.json.</p><span class='tag'>Secrets hidden</span> <span class='tag'>Admin protected</span> <span class='tag'>Backup enabled</span></div></div>"
    return page('Dashboard',body)


@manager.get('/menus')
@logged
def menus():
    seed(); rows=''
    for m in snapshot():
        status=f"<span class='status {'on' if m['active'] else 'off'}'>{'Aktif' if m['active'] else 'Nonaktif'}</span>"; toggle='Nonaktifkan' if m['active'] else 'Aktifkan'
        rows+=f"<tr><td><strong>{esc(m['name'])}</strong><div class='hint'>{esc(m['description'])}</div></td><td>{len(m['buttons'])}</td><td>{status}</td><td><div class='actions'><a class='btn small' href='{url_for('manager.menu_edit',menu_id=m['id'])}'>Edit menu</a><a class='btn small' href='{url_for('manager.button_new',menu_id=m['id'])}'>＋ Tombol</a><a class='btn small' href='{url_for('manager.preview',menu_id=m['id'])}'>Preview</a><form method='post' action='{url_for('manager.menu_toggle',menu_id=m['id'])}'><button class='btn small' type='submit'>{toggle}</button></form></div></td></tr>"
    body="<div class='card'><div class='section-head'><div><h3 class='title'>Menu Center</h3><div class='muted'>Pilih menu untuk mengatur teks, tombol, callback, urutan dan status.</div></div><a class='btn primary' href='"+url_for('manager.menu_new')+"'>＋ Tambah menu</a></div><br><div class='table-wrap'><table class='table'><tr><th>Menu</th><th>Tombol</th><th>Status</th><th>Aksi</th></tr>"+(rows or "<tr><td colspan='4'>Belum ada menu.</td></tr>")+"</table></div><br><div class='actions'><a class='btn primary' href='"+url_for('manager.publish')+"'>Publish perubahan</a><a class='btn' href='"+url_for('manager.preview')+"'>Preview Telegram</a></div></div>"
    return page('Menu Center',body,'menus')


@manager.route('/menus/new',methods=['GET','POST'])
@logged
def menu_new():
    if request.method=='POST':
        with db() as conn: conn.execute('INSERT INTO manager_menus(name,description,active,sort_order,updated_at) VALUES(?,?,?,?,?)',(request.form.get('name','').strip(),request.form.get('description','').strip(),1,int(request.form.get('sort_order','0') or 0),now())); conn.commit()
        audit('menu_created'); return redirect(url_for('manager.menus'))
    body="<div class='card'><h3 class='title'>Tambah menu</h3><p class='muted'>Buat menu baru yang nantinya bisa diberi banyak tombol.</p><form class='form' method='post'>"+field('name',label='Nama menu',required=True)+field('description',label='Deskripsi',required=False)+field('sort_order',0,'Urutan menu','number')+"<button class='btn primary'>Simpan menu</button></form></div>"
    return page('Tambah Menu',body,'menus')


@manager.route('/menus/<int:menu_id>/edit',methods=['GET','POST'])
@logged
def menu_edit(menu_id):
    with db() as conn: m=conn.execute('SELECT * FROM manager_menus WHERE id=?',(menu_id,)).fetchone()
    if not m:return 'Menu tidak ditemukan',404
    if request.method=='POST':
        with db() as conn: conn.execute('UPDATE manager_menus SET name=?,description=?,sort_order=?,active=?,updated_at=? WHERE id=?',(request.form.get('name','').strip(),request.form.get('description','').strip(),int(request.form.get('sort_order','0') or 0),1 if request.form.get('active') else 0,now(),menu_id)); conn.commit()
        audit('menu_updated'); return redirect(url_for('manager.menu_edit',menu_id=menu_id))
    bs=snapshot(); current=next(x for x in bs if x['id']==menu_id)
    buttons=''
    for b in current['buttons']:
        buttons+=f"<tr><td>{esc(b['label'])}</td><td><code>{esc(b['callback'])}</code></td><td>{esc(b['button_type'])}</td><td>{b['sort_order']}</td><td><span class='status {'on' if b['active'] else 'off'}'>{'Aktif' if b['active'] else 'Nonaktif'}</span></td><td><div class='actions'><a class='btn small' href='{url_for('manager.button_edit',button_id=b['id'])}'>Edit</a><form method='post' action='{url_for('manager.button_toggle',button_id=b['id'])}'><button class='btn small' type='submit'>{'Nonaktifkan' if b['active'] else 'Aktifkan'}</button></form><form method='post' action='{url_for('manager.button_delete',button_id=b['id'])}'><button class='btn small danger' type='submit'>Hapus</button></form></div></td></tr>"
    body="<div class='card'><div class='section-head'><div><h3 class='title'>Edit menu</h3><div class='muted'>Atur identitas dan urutan menu. Tombol diatur pada tabel di bawah.</div></div><a class='btn' href='"+url_for('manager.preview',menu_id=menu_id)+"'>Preview menu</a></div><br><form class='form' method='post'>"+field('name',m['name'],'Nama menu',required=True)+field('description',m['description'],'Deskripsi',required=False)+field('sort_order',m['sort_order'],'Urutan menu','number')+"<label class='field'><span>Status</span><span><input type='checkbox' name='active' "+('checked' if m['active'] else '')+"> Aktif</span></label><div class='actions'><button class='btn primary'>Simpan perubahan</button><a class='btn' href='"+url_for('manager.menus')+"'>Kembali</a></div></form></div><div class='card'><div class='section-head'><div><h3 class='title'>Tombol menu</h3><div class='muted'>Edit teks tombol, callback/URL, tipe dan urutan.</div></div><a class='btn primary' href='"+url_for('manager.button_new',menu_id=menu_id)+"'>＋ Tambah tombol</a></div><br><div class='table-wrap'><table class='table'><tr><th>Teks</th><th>Callback</th><th>Tipe</th><th>Urutan</th><th>Status</th><th>Aksi</th></tr>"+(buttons or "<tr><td colspan='6'>Belum ada tombol.</td></tr>")+"</table></div></div>"
    return page('Edit Menu',body,'menus')


@manager.post('/menus/<int:menu_id>/toggle')
@logged
def menu_toggle(menu_id):
    with db() as conn: conn.execute('UPDATE manager_menus SET active=CASE active WHEN 1 THEN 0 ELSE 1 END,updated_at=? WHERE id=?',(now(),menu_id)); conn.commit()
    audit('menu_status_changed'); return redirect(url_for('manager.menus'))


@manager.post('/menus/<int:menu_id>/delete')
@logged
def menu_delete(menu_id):
    with db() as conn: conn.execute('DELETE FROM manager_menus WHERE id=?',(menu_id,)); conn.commit()
    audit('menu_deleted'); return redirect(url_for('manager.menus'))


@manager.route('/menus/<int:menu_id>/buttons/new',methods=['GET','POST'])
@logged
def button_new(menu_id):
    with db() as conn: m=conn.execute('SELECT * FROM manager_menus WHERE id=?',(menu_id,)).fetchone()
    if not m:return 'Menu tidak ditemukan',404
    if request.method=='POST':
        with db() as conn: conn.execute('INSERT INTO manager_buttons(menu_id,label,callback,button_type,url,active,sort_order) VALUES(?,?,?,?,?,?,?)',(menu_id,request.form.get('label','').strip(),request.form.get('callback','').strip(),request.form.get('button_type','callback'),request.form.get('url','').strip(),1,int(request.form.get('sort_order','0') or 0))); conn.commit()
        audit('button_created'); return redirect(url_for('manager.menu_edit',menu_id=menu_id))
    body="<div class='card'><h3 class='title'>Tambah tombol</h3><p class='muted'>Menu tujuan: "+esc(m['name'])+"</p><form class='form' method='post'>"+field('label',label='Teks tombol',required=True)+field('callback',label='Callback',placeholder='contoh: open_tools',required=False)+field('url',label='URL jika tipe URL',placeholder='https://...',required=False)+"<label class='field'>Tipe<select class='select' name='button_type'><option value='callback'>Callback</option><option value='url'>URL</option></select></label>"+field('sort_order',0,'Urutan tombol','number')+"<button class='btn primary'>Simpan tombol</button></form></div>"
    return page('Tambah Tombol',body,'menus')


@manager.route('/buttons/<int:button_id>/edit',methods=['GET','POST'])
@logged
def button_edit(button_id):
    with db() as conn: b=conn.execute('SELECT * FROM manager_buttons WHERE id=?',(button_id,)).fetchone()
    if not b:return 'Tombol tidak ditemukan',404
    if request.method=='POST':
        with db() as conn: conn.execute('UPDATE manager_buttons SET label=?,callback=?,button_type=?,url=?,sort_order=?,active=? WHERE id=?',(request.form.get('label','').strip(),request.form.get('callback','').strip(),request.form.get('button_type','callback'),request.form.get('url','').strip(),int(request.form.get('sort_order','0') or 0),1 if request.form.get('active') else 0,button_id)); conn.commit()
        audit('button_updated'); return redirect(url_for('manager.menu_edit',menu_id=b['menu_id']))
    body="<div class='card'><h3 class='title'>Edit tombol</h3><form class='form' method='post'>"+field('label',b['label'],'Teks tombol',required=True)+field('callback',b['callback'],'Callback',required=False)+field('url',b['url'],'URL',required=False)+"<label class='field'>Tipe<select class='select' name='button_type'><option value='callback' "+('selected' if b['button_type']=='callback' else '')+">Callback</option><option value='url' "+('selected' if b['button_type']=='url' else '')+">URL</option></select></label>"+field('sort_order',b['sort_order'],'Urutan tombol','number')+"<label class='field'><span>Status</span><span><input type='checkbox' name='active' "+('checked' if b['active'] else '')+"> Aktif</span></label><div class='actions'><button class='btn primary'>Simpan perubahan</button><a class='btn' href='"+url_for('manager.menu_edit',menu_id=b['menu_id'])+"'>Kembali</a></div></form></div>"
    return page('Edit Tombol',body,'menus')


@manager.post('/buttons/<int:button_id>/toggle')
@logged
def button_toggle(button_id):
    with db() as conn:
        b=conn.execute('SELECT menu_id FROM manager_buttons WHERE id=?',(button_id,)).fetchone(); conn.execute('UPDATE manager_buttons SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?',(button_id,)); conn.commit()
    audit('button_status_changed'); return redirect(url_for('manager.menu_edit',menu_id=b['menu_id']))


@manager.post('/buttons/<int:button_id>/delete')
@logged
def button_delete(button_id):
    with db() as conn:
        b=conn.execute('SELECT menu_id FROM manager_buttons WHERE id=?',(button_id,)).fetchone(); conn.execute('DELETE FROM manager_buttons WHERE id=?',(button_id,)); conn.commit()
    audit('button_deleted'); return redirect(url_for('manager.menu_edit',menu_id=b['menu_id']))


@manager.get('/preview')
@manager.get('/preview/<int:menu_id>')
@logged
def preview(menu_id=None):
    items=snapshot(); m=next((x for x in items if x['id']==menu_id),None) if menu_id else (items[0] if items else None)
    if not m:return page('Telegram Preview',"<div class='card'>Belum ada menu.</div>",'menus')
    buttons=''.join("<span class='tgbtn'>"+esc(b['label'])+"</span>" for b in m['buttons'] if b['active'])
    body="<div class='card'><div class='muted'>Simulasi tampilan Telegram</div><div class='preview'><div class='muted'>GW-PROJECT BOT</div><h2>"+esc(m['name'])+"</h2><p>"+esc(m['description'])+"</p><div>"+buttons+"</div></div><br><a class='btn' href='"+url_for('manager.menu_edit',menu_id=m['id'])+"'>Kembali ke editor</a></div>"
    return page('Telegram Preview',body,'menus')


@manager.get('/publish')
@logged
def publish():
    ensure(); BACKUP_DIR.mkdir(exist_ok=True)
    if PUBLISHED.exists():shutil.copy2(PUBLISHED,BACKUP_DIR/('menu_config_'+str(now())+'.json'))
    PUBLISHED.write_text(json.dumps(snapshot(),ensure_ascii=False,indent=2),encoding='utf-8'); audit('configuration_published')
    return redirect(url_for('manager.menus'))


@manager.get('/backups')
@logged
def backups():
    files=sorted(BACKUP_DIR.glob('menu_config_*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    rows=''.join("<tr><td>"+esc(p.name)+"</td><td>"+time.strftime('%Y-%m-%d %H:%M',time.localtime(p.stat().st_mtime))+"</td><td><form method='post' action='"+url_for('manager.rollback',filename=p.name)+"'><button class='btn small'>Rollback</button></form></td></tr>" for p in files)
    body="<div class='card'><h3 class='title'>Backup & Rollback</h3><p class='muted'>Publish otomatis membuat salinan konfigurasi aktif sebelum ditimpa.</p><div class='table-wrap'><table class='table'><tr><th>File backup</th><th>Dibuat</th><th>Aksi</th></tr>"+(rows or "<tr><td colspan='3'>Belum ada backup.</td></tr>")+"</table></div></div>"
    return page('Backup & Rollback',body,'backups')


@manager.post('/backups/<path:filename>/rollback')
@logged
def rollback(filename):
    candidate=(BACKUP_DIR/filename).resolve()
    if candidate.parent!=BACKUP_DIR.resolve() or not candidate.name.startswith('menu_config_') or not candidate.exists():return 'Backup tidak ditemukan',404
    shutil.copy2(candidate,PUBLISHED); audit('configuration_rollback'); return redirect(url_for('manager.backups'))


@manager.route('/config',methods=['GET','POST'])
@logged
def config():
    if request.method=='POST':
        with db() as conn: conn.execute("INSERT INTO manager_config(id,api_name,api_base_url,api_key_env,updated_at) VALUES(1,?,?,?,?) ON CONFLICT(id) DO UPDATE SET api_name=excluded.api_name,api_base_url=excluded.api_base_url,api_key_env=excluded.api_key_env,updated_at=excluded.updated_at",(request.form.get('api_name','').strip(),request.form.get('api_base_url','').strip(),request.form.get('api_key_env','').strip(),now())); conn.commit()
        audit('api_configuration_updated'); return redirect(url_for('manager.config'))
    with db() as conn: row=conn.execute('SELECT * FROM manager_config WHERE id=1').fetchone()
    v=row or {'api_name':'','api_base_url':'','api_key_env':''}
    body="<div class='card'><h3 class='title'>API Configuration</h3><p class='muted'>Isi URL dan nama environment variable saja. Jangan masukkan token/API key asli ke dashboard atau GitHub.</p><form class='form' method='post'>"+field('api_name',v['api_name'],'Nama API',required=False)+field('api_base_url',v['api_base_url'],'Base URL',required=False)+field('api_key_env',v['api_key_env'],'Nama variable secret',required=False)+"<button class='btn primary'>Simpan konfigurasi</button></form></div>"
    return page('API Configuration',body,'config')


@manager.get('/users')
@logged
def users():
    body="<div class='card'><h3 class='title'>Users & Roles</h3><p class='muted'>Akses dashboard ini menggunakan DASHBOARD_USERNAME dan DASHBOARD_PASSWORD dari Environment Variables cPanel. Admin Telegram tetap dikendalikan oleh ADMIN_IDS pada bot.</p><div class='actions'><span class='tag'>Administrator protected</span><span class='tag'>Secrets not exposed</span></div></div>"
    return page('Users & Roles',body,'users')


@manager.get('/logs')
@logged
def logs():
    ensure()
    with db() as conn: rows=conn.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 200').fetchall()
    body="<div class='card'><h3 class='title'>Activity Logs</h3><div class='table-wrap'><table class='table'><tr><th>User</th><th>Action</th><th>Waktu</th></tr>"+''.join("<tr><td>"+esc(r['user_id'])+"</td><td>"+esc(r['action'])+"</td><td>"+time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(r['created_at']))+"</td></tr>" for r in rows)+"</table></div></div>"
    return page('Activity Logs',body,'logs')
