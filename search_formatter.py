"""Safe, readable formatter for GW-PROJECT API responses.

This module keeps the response structure visible while redacting high-risk
credential fields before sending API output to Telegram.
"""

import html
import re

DIVIDER = "━━━━━━━━━━━━━━━━━━"
SENSITIVE_KEYS = re.compile(
    r"(?:password|passwd|pwd|token|secret|api[_-]?key|access[_-]?token|"
    r"refresh[_-]?token|authorization|cookie|session|credential|private[_-]?key|"
    r"cvv|cvc|otp|pin|security[_-]?code)",
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
        for index, (key, item) in enumerate(items):
            safe_item = _safe_value(key, item)
            branch = "└─" if index == len(items) - 1 else "├─"
            key_text = html.escape(str(key))
            if isinstance(safe_item, (dict, list)):
                lines.append(f"{prefix}{branch} <b>{key_text}</b>")
                lines.extend(_render(safe_item, indent + 1))
            else:
                lines.append(
                    f"{prefix}{branch} <b>{key_text}</b>: "
                    f"{html.escape(str(safe_item))}"
                )
        return lines
    if isinstance(value, list):
        lines = []
        for index, item in enumerate(value, 1):
            branch = "└─" if index == len(value) else "├─"
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{branch} <b>#{index}</b>")
                lines.extend(_render(item, indent + 1))
            else:
                lines.append(f"{prefix}{branch} {html.escape(str(item))}")
        return lines
    return [f"{prefix}{html.escape(str(value))}"]


def format_search_result(result):
    """Format an API result for Telegram HTML parse mode."""
    if not isinstance(result, dict):
        return (
            "🔎 <b>GW-PROJECT RESULT</b>\n"
            f"{DIVIDER}\n\n"
            "Format response API tidak dikenali.\n\n"
            f"{DIVIDER}\n"
            "🛰️ <b>GW-PROJECT</b>"
        )

    safe_result = _safe_value("root", result)
    lines = ["🔎 <b>GW-PROJECT RESULT</b>", DIVIDER]

    # Keep common summary fields at the top when present.
    summary_keys = ("status", "message", "count", "total", "success")
    for key in summary_keys:
        if key in safe_result and isinstance(safe_result[key], (str, int, float, bool)):
            lines.append(f"📌 <b>{html.escape(key.title())}</b>: {html.escape(str(safe_result[key]))}")

    if len(lines) > 2:
        lines.append("")

    # Render remaining fields in a compact tree so nested databases/records
    # remain readable instead of being dumped as one large JSON line.
    body = {k: v for k, v in safe_result.items() if k not in summary_keys}
    if body:
        lines.extend(_render(body))
    else:
        lines.append("Tidak ada detail tambahan.")

    lines.extend(["", DIVIDER, "🛰️ <b>GW-PROJECT</b>"])
    return "\n".join(lines)
