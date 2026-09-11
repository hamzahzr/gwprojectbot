from pathlib import Path

APP = Path("app.py")
text = APP.read_text(encoding="utf-8")

# Keep TikTok results in Telegram chat. If an older deployment added
# send_tiktok_file(), remove that helper and restore send_long_message().
if "def send_tiktok_file(" in text:
    start = text.index("def send_tiktok_file(")
    end = text.index("\n\ndef edit_message", start)
    text = text[:start] + text[end:]

text = text.replace(
    "send_tiktok_file(chat_id, format_tiktok_result(value, result), value)",
    "send_long_message(chat_id, format_tiktok_result(value, result))",
)

APP.write_text(text, encoding="utf-8")
print("TikTok chat output patch applied")
