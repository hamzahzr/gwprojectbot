from pathlib import Path

APP = Path(__file__).resolve().parent / "bot_manager.py"
text = APP.read_text(encoding="utf-8")

old = "INSERT INTO manager_menus(name,description,sort_order,updated_at) VALUES(?,?,?,?,?)"
new = "INSERT INTO manager_menus(name,description,sort_order,updated_at) VALUES(?,?,?,?)"

if old not in text:
    print("No seed SQL placeholder error found; nothing to patch")
else:
    text = text.replace(old, new, 1)
    APP.write_text(text, encoding="utf-8")
    print("bot_manager.py seed SQL patch applied successfully")
