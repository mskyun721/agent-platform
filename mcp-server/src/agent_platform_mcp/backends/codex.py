"""Codex exec JSON mode with sandbox selection."""
from agent_platform_mcp.tools import native_output

name = "codex"
host_files = ("AGENTS.md", ".codex/hooks.json")
observed = True


def command(prompt, workdir, *, model, read_only):
    cmd = ["codex", "exec", "--cd", str(workdir)]
    if model:
        cmd += ["-m", model]
    return cmd + ["--skip-git-repo-check", "--sandbox", "read-only" if read_only else "workspace-write", "--json", prompt]


def parse(stdout):
    body, usage = native_output.codex(stdout)
    return body, usage, False
