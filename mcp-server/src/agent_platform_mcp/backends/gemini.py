"""Gemini CLI headless JSON mode (flags observed on 0.62.0, 2026-10-22); no MCP or extensions in wrappers."""
import json

from agent_platform_mcp.backends.base import UNAVAILABLE
from agent_platform_mcp.events import Usage, validate_usage

name = "gemini"
host_files = ("GEMINI.md", ".gemini/settings.json", ".gemini/commands")
observed = False


def command(prompt, workdir, *, model, read_only):
    cmd = ["gemini", "-o", "json", "--approval-mode", "plan" if read_only else "auto_edit",
           "-e", "none", "--allowed-mcp-server-names", "none"]
    if model:
        cmd += ["-m", model]
    return cmd + ["-p", prompt]


def parse(stdout):
    try:
        row = json.loads(stdout)
    except ValueError:
        return "", UNAVAILABLE, True
    if not isinstance(row, dict) or row.get("error") or not isinstance(row.get("response"), str):
        return "", UNAVAILABLE, True
    models = (row.get("stats") or {}).get("models") or {}
    tokens = [m.get("tokens") for m in models.values() if isinstance(m, dict) and isinstance(m.get("tokens"), dict)]
    if not tokens:
        return row["response"], UNAVAILABLE, False

    def total(key):
        values = [t.get(key) for t in tokens]
        return None if any(type(v) is not int for v in values) else sum(values)

    usage = Usage(total("prompt"), total("candidates"), total("cached"), None, "gemini-json", "partial")
    return row["response"], UNAVAILABLE if validate_usage(usage) else usage, False
