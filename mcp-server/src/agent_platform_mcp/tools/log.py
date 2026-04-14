"""claude_log.md append helper."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agent_platform_mcp.config import LOG_FILE, VALID_AGENTS


def append(message: str, agent: str | None = None, feature: str | None = None) -> dict[str, Any]:
    if agent is not None and agent not in VALID_AGENTS:
        raise ValueError(f"Unknown agent '{agent}'")
    if not message or not message.strip():
        raise ValueError("message must be non-empty")

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tag_parts = [p for p in (agent, feature) if p]
    tag = f" [{' · '.join(tag_parts)}]" if tag_parts else ""
    line = f"- {ts}{tag} {message.strip()}\n"

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line)

    return {"path": str(LOG_FILE), "line": line.rstrip("\n")}
