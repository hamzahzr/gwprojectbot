import ast
import json
import sqlite3
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
APP_FILE = BASE / "app.py"
DB_FILE = BASE / "gwproject.db"
BACKUP_DIR = BASE / "manager_backups"


def literal(node):
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def extract_menu(function_node):
    buttons = []
    for node in ast.walk(function_node):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "button":
            continue
        if len(node.args) < 2:
            continue
        label = literal(node.args[0])
        callback = literal(node.args[1])
        if isinstance(label, str) and isinstance(callback, str):
            buttons.append({"label": label, "callback": callback})
    return buttons


def extract_active_menus():
    tree = ast.parse(APP_FILE.read_text(encoding="utf-8"), filename=str(APP_FILE))
    wanted = {
        "main_menu": ("Main Menu", "Menu utama bot"),
        "tools_menu": ("Tools", "Daftar tools aktif"),
        "settings_menu": ("Settings", "Pengaturan bot"),
    }
    found = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            name, description = wanted[node.name]
            found[node.name] = {
                "name": name,
                "description": description,
                "active": True,
                "sort_order": len(found),
                "buttons": extract_menu(node),
            }
    return list(found.values())


def backup_database():
    BACKUP_DIR.mkdir(exist_ok=True)
    if DB_FILE.exists():
        target = BACKUP_DIR / f"before_sync_{int(time.time())}.db"
        target.write_bytes(DB_FILE.read_bytes())
        return target.name
    return None


def sync():
    menus = extract_active_menus()
    if not menus:
        raise RuntimeError("Tidak menemukan main_menu/tools_menu/settings_menu di app.py")

    backup = backup_database()
    conn = sqlite3.connect(DB_FILE, timeout=20)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS manager_menus(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,description TEXT DEFAULT '',active INTEGER DEFAULT 1,sort_order INTEGER DEFAULT 0,updated_at INTEGER)")
        conn.execute("CREATE TABLE IF NOT EXISTS manager_buttons(id INTEGER PRIMARY KEY AUTOINCREMENT,menu_id INTEGER NOT NULL,label TEXT NOT NULL,callback TEXT DEFAULT '',button_type TEXT DEFAULT 'callback',url TEXT DEFAULT '',active INTEGER DEFAULT 1,sort_order INTEGER DEFAULT 0,FOREIGN KEY(menu_id) REFERENCES manager_menus(id) ON DELETE CASCADE)")
        for index, menu in enumerate(menus):
            row = conn.execute("SELECT id FROM manager_menus WHERE name=? ORDER BY id LIMIT 1", (menu["name"],)).fetchone()
            if row:
                menu_id = row[0]
                conn.execute("UPDATE manager_menus SET description=?,active=1,sort_order=?,updated_at=? WHERE id=?", (menu["description"], index, int(time.time()), menu_id))
                conn.execute("DELETE FROM manager_buttons WHERE menu_id=?", (menu_id,))
            else:
                cur = conn.execute("INSERT INTO manager_menus(name,description,active,sort_order,updated_at) VALUES(?,?,?,?,?)", (menu["name"], menu["description"], 1, index, int(time.time())))
                menu_id = cur.lastrowid
            for order, item in enumerate(menu["buttons"]):
                conn.execute("INSERT INTO manager_buttons(menu_id,label,callback,button_type,url,active,sort_order) VALUES(?,?,?,?,?,?,?)", (menu_id, item["label"], item["callback"], "callback", "", 1, order))
        conn.commit()
    finally:
        conn.close()

    report = {"status": "ok", "menus": [{"name": m["name"], "buttons": len(m["buttons"])} for m in menus], "backup": backup}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sync()
