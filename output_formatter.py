import html
import re

SENSITIVE_KEYS = re.compile(
    r"(?:password|passwd|pwd|token|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|cookie|session|credential|private[_-]?key|cvv|cvc|otp|pin|security[_-]?code)",
    re.I,
)


def _safe_value(key, value):
    if SENSITIVE_KEYS.search(str(key)):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: _safe_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_value(key, item) for item in value]
    return value


def _render(value, indent=0):
    prefix = "  " * indent
    if isinstance(value, dict):
        lines = []
        items = list(value.items())
        for pos, (key, item) in enumerate(items):
            safe = _safe_value(key, item)
            branch = "└─" if pos == len(items) - 1 else "├─"
            key_html = html.escape(str(key))
            if isinstance(safe, (dict, list)):
                lines.append(f"{prefix}{branch} <b>{key_html}</b>")
                lines.extend(_render(safe, indent + 1))
            else:
                lines.append(f"{prefix}{branch} <b>{key_html}</b>: {html.escape(str(safe))}")
        return lines
    if isinstance(value, list):
        lines = []
        for pos, item in enumerate(value):
            branch = "└─" if pos == len(value) - 1 else "├─"
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{branch} <b>#{pos + 1}</b>")
                lines.extend(_render(_safe_value("item", item), indent + 1))
            else:
                lines.append(f"{prefix}{branch} {html.escape(str(item))}")
        return lines
    return [f"{prefix}{html.escape(str(value))}"]


def format_tool_output(tool_name, result, title="GW-PROJECT RESULT"):
    """Universal Telegram formatter for tool/API responses.

    Keeps the response structure, formats nested dictionaries/lists as a tree,
    and redacts high-risk credential fields consistently for every tool.
    """
    name = html.escape(str(tool_name or "TOOL").upper())
    lines = [
        f"🔎 <b>{html.escape(title)}</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"🧰 Tool: <b>{name}</b>",
        "",
    ]
    safe = _safe_value("root", result)
    lines.extend(_render(safe))
    lines += ["", "━━━━━━━━━━━━━━━━━━", "🛰️ <b>GW-PROJECT</b>"]
    return "\n".join(lines)


def format_error(tool_name, message):
    name = html.escape(str(tool_name or "TOOL").upper())
    return (
        "❌ <b>GW-PROJECT ERROR</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🧰 Tool: <b>{name}</b>\n"
        f"├─ <b>Status</b>: ERROR\n"
        f"└─ <b>Message</b>: {html.escape(str(message))}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🛰️ <b>GW-PROJECT</b>"
    )
