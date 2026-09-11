from pathlib import Path

APP = Path("app.py")
text = APP.read_text(encoding="utf-8")

if "def send_tiktok_file(" not in text:
    start = text.index("def send_long_message(")
    end = text.index("\n\ndef edit_message", start)
    replacement = '''def send_tiktok_file(chat_id, text, input_value):
    """Send the complete formatted public TikTok result as a UTF-8 TXT document."""
    plain = re.sub(r"<[^>]+>", "", text)
    plain = html.unescape(plain).replace("\\r\\n", "\\n").strip()
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(input_value).strip())[:50] or "result"
    filename = f"tiktok_{safe_name}.txt"
    response = requests.post(
        f"{TELEGRAM_API}/sendDocument",
        data={"chat_id": chat_id, "caption": "🎵 TIKTOK SCRAPER — hasil lengkap"},
        files={"document": (filename, plain.encode("utf-8"), "text/plain; charset=utf-8")},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()
'''
    text = text[:start] + replacement + text[end:]

text = text.replace(
    "send_long_message(chat_id, format_tiktok_result(value, result))",
    "send_tiktok_file(chat_id, format_tiktok_result(value, result), value)",
)

APP.write_text(text, encoding="utf-8")
print("TikTok TXT export patch applied")
