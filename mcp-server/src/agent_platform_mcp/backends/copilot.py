"""GitHub Copilot CLI prompt mode (flags observed on 1.0.95, 2026-10-22).

JSONL output is undocumented, so wrappers use silent text output and report usage as unavailable.
The workspace .mcp.json is auto-loaded by Copilot; wrappers disable the platform server to prevent re-delegation.
"""
from agent_platform_mcp.backends.base import UNAVAILABLE

name = "copilot"
host_files = ("AGENTS.md", ".github/agents", ".mcp.json")
observed = False


def command(prompt, workdir, *, model, read_only):
    cmd = ["copilot", "-s", "--no-ask-user", "--no-color", "--disable-mcp-server", "agent-platform",
           "--deny-tool", "shell"]
    cmd += ["--deny-tool", "write"] if read_only else []
    if model:
        cmd += ["--model", model]
    cmd += [] if read_only else ["--allow-tool", "write"]
    return cmd + ["-p", prompt]


def parse(stdout):
    text = stdout.strip()
    return text, UNAVAILABLE, not text
