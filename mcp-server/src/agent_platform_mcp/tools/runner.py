"""Shared subprocess plumbing for the Codex/Gemini CLI wrapper tools.

Every agent tool (plan/backend/review/audit/qa/release) delegates to an
external CLI the same way: build a command for the chosen backend, verify the
binary exists, run it with a hard timeout inside the workspace, and post-process
stdout. This module owns that plumbing so each tool only defines its prompt,
validation, and artifact handling.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from agent_platform_mcp.config import ROOT, target_project_root

VALID_CLI = {"codex", "gemini"}


def resolve_cli(cli: str) -> str:
    """Map 'auto' to the configured preferred CLI; validate explicit choices."""
    from agent_platform_mcp.config import preferred_cli

    if cli == "auto":
        return preferred_cli()
    if cli not in VALID_CLI:
        raise ValueError(f"cli must be one of ['auto', {', '.join(map(repr, sorted(VALID_CLI)))}]")
    return cli


def workspace_root() -> Path:
    """CLI working directory: the active target project, or the platform repo."""
    return target_project_root() or ROOT


def build_cmd(
    cli: str,
    prompt: str,
    workdir: Path,
    *,
    approval_mode: str = "plan",
    model: str | None = None,
) -> list[str]:
    """Build the CLI invocation for the given backend.

    approval_mode and model only apply to gemini; codex always runs
    `exec --full-auto` scoped to the workspace.
    """
    if cli == "codex":
        return [
            "codex",
            "exec",
            "--cd",
            str(workdir),
            "--skip-git-repo-check",
            "--full-auto",
            prompt,
        ]
    if cli == "gemini":
        cmd = ["gemini"]
        if model:
            cmd += ["-m", model]
        return cmd + ["--approval-mode", approval_mode, "-p", prompt]
    raise ValueError(f"cli must be one of {sorted(VALID_CLI)}")


def run_cli(
    cli: str,
    cmd: list[str],
    workdir: Path,
    timeout_sec: int,
) -> subprocess.CompletedProcess:
    """Run the CLI command with a hard timeout. Raises RuntimeError on
    missing binary or timeout; nonzero exit codes are returned as-is."""
    if shutil.which(cli) is None:
        raise RuntimeError(f"{cli} CLI not found on PATH")
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=str(workdir),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{cli} timed out after {timeout_sec}s") from exc


def preview(text: str, limit: int = 300) -> str:
    """Truncate text for dry-run previews and result summaries."""
    return text[:limit] + ("…" if len(text) > limit else "")


def stderr_tail(proc: subprocess.CompletedProcess) -> str:
    return proc.stderr[-500:] if proc.stderr else ""


def detect_source_hints() -> str:
    """Scan the workspace root for likely source locations."""
    root = workspace_root()
    hints: list[str] = []
    for rel, label in [
        ("src/main/kotlin/", "Kotlin/Spring (Coroutine)"),
        ("src/main/java/", "Java/Spring (Reactor)"),
        ("src/", "generic src tree"),
        ("app/", "app module"),
        ("server/", "server module"),
        ("mcp-server/src/", "Python (mcp-server)"),
    ]:
        if (root / rel).is_dir():
            hints.append(f"{rel} ({label})")
    return ", ".join(hints) if hints else "(auto-detect within repository)"


def coding_style_path(source_hint: str) -> str:
    """Language-specific coding style standard path for a detected source hint."""
    if "Kotlin" in source_hint:
        return "standards/coding-style-kotlin.md"
    if "Java" in source_hint:
        return "standards/coding-style-java.md"
    return "standards/coding-style-kotlin.md"  # default
