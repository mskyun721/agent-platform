"""Metadata projection for Codex exec JSON observed on CLI 0.154.0 (2026-09-14)."""

import json
from uuid import UUID

from agent_platform_mcp.events import Usage, validate_usage


def codex(stdout: str) -> tuple[str, Usage]:
    unavailable = Usage(None, None, None, None, "unavailable", "unavailable")
    rows = []
    malformed = False
    for line in stdout.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            malformed = True
            continue
        if isinstance(value, dict) and isinstance(value.get("type"), str):
            rows.append(value)
    if not rows:
        return stdout, unavailable
    messages = [row["item"]["text"] for row in rows if row["type"] == "item.completed"
                and isinstance(row.get("item"), dict) and row["item"].get("type") == "agent_message"
                and isinstance(row["item"].get("text"), str)]
    body = messages[-1] if messages else ""
    completed = [row for row in rows if row["type"] == "turn.completed"]
    if malformed or len(completed) != 1 or not isinstance(completed[0].get("usage"), dict):
        return body, unavailable
    usage = completed[0]["usage"]
    sessions = [row.get("thread_id") for row in rows if row["type"] == "thread.started"]
    if len(sessions) != 1:
        return body, unavailable
    try:
        source = "codex-json:" + str(UUID(sessions[0])) + ":turn-0"
    except (ValueError, TypeError, AttributeError):
        return body, unavailable
    values = [usage.get(key) for key in ("input_tokens", "output_tokens", "cached_input_tokens", "cache_write_input_tokens")]
    if all(value is None for value in values):
        return body, unavailable
    completeness = "full" if all(value is not None for value in values) else "partial"
    projected = Usage(*values, source, completeness)
    return body, unavailable if validate_usage(projected) else projected


def claude(stdout: str) -> tuple[str, Usage, bool]:
    """Project a Claude print JSON result; malformed responses cannot report success."""
    unavailable = Usage(None, None, None, None, 'unavailable', 'unavailable')
    try:
        row = json.loads(stdout)
        if not isinstance(row, dict) or row.get('type') != 'result' or not isinstance(row.get('result'), str):
            return '', unavailable, True
        failed = row.get('is_error') is not False or row.get('subtype') != 'success'
        native = row.get('usage')
        if not isinstance(native, dict):
            return row['result'], unavailable, failed
        counts = [native.get(k) for k in ('input_tokens','output_tokens','cache_read_input_tokens','cache_creation_input_tokens')]
        usage = Usage(*counts, 'claude-json', 'full' if all(v is not None for v in counts) else 'partial')
        return row['result'], unavailable if validate_usage(usage) else usage, failed
    except (ValueError, TypeError):
        return '', unavailable, True
