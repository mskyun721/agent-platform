"""Backend implementation wrapper for Codex or Gemini CLI."""

from __future__ import annotations

import shutil
import subprocess
import time
from datetime import date
from pathlib import Path
from typing import Any

from agent_platform_mcp.config import ROOT, features_dir, target_project_root
from agent_platform_mcp.observability import end_cli_span, start_cli_span
from agent_platform_mcp.tools.feature import _ensure_safe_name  # noqa: PLC2701

VALID_AI = {"codex", "gemini"}
API_SPEC_FILE = "API-SPEC.md"
DECISIONS_FILE = "DECISIONS.md"
DEFAULT_TIMEOUT_SEC = 1800


def _require_target_project() -> Path:
    target = target_project_root()
    if target is None:
        raise RuntimeError(
            "TARGET_PROJECT is not set. Run project_init or write .active-project first."
        )
    return target


def _build_prompt(feature: str) -> str:
    target = _require_target_project()
    feature_dir = features_dir() / feature
    return (
        f"TARGET_PROJECT: {target}\n"
        f"Feature: {feature}\n\n"
        f"Implement the backend feature described by these artifacts:\n"
        f"- PRD: {feature_dir / 'PRD.md'}\n"
        f"- TASK: {feature_dir / 'TASK.md'}\n\n"
        f"Required outputs under the same feature directory:\n"
        f"- {feature_dir / API_SPEC_FILE}\n"
        f"- {feature_dir / DECISIONS_FILE}\n\n"
        f"Reference standards from the agent-platform repository:\n"
        f"- {ROOT / 'standards/reference/backend-phase-flow.md'}\n"
        f"- {ROOT / 'standards/coding-style-kotlin.md'}\n"
        f"- {ROOT / 'standards/coding-style-java.md'}\n"
        f"- {ROOT / 'standards/api-contract.md'}\n"
        f"- {ROOT / 'standards/test-policy.md'}\n"
        f"- {ROOT / 'standards/security-baseline.md'}\n\n"
        f"Rules:\n"
        f"- Work inside TARGET_PROJECT only for product code and feature artifacts.\n"
        f"- Do not write feature artifacts under the agent-platform repository.\n"
        f"- Follow hexagonal order: Domain -> Application -> Adapter.\n"
        f"- Run focused tests or the smallest available verification command.\n"
        f"- Only assess files that actually exist. Do not invent missing source files.\n"
        f"- Never read or output .env, .pem, .key, credential, or secret files.\n"
        f"- Keep generated artifacts status=draft unless explicitly reviewed by a human.\n\n"
        f"After implementation, print a concise Markdown summary with changed files, "
        f"verification commands, and remaining risks."
    )


def _frontmatter(feature: str, artifact: str, tool: str) -> str:
    today = date.today().isoformat()
    return (
        "---\n"
        "agent: backend\n"
        f"feature: {feature}\n"
        "status: draft\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        f"artifact: {artifact}\n"
        f"tool: {tool}\n"
        "---\n\n"
    )


def _patch_frontmatter(path: Path, feature: str, tool: str) -> None:
    if not path.is_file():
        return
    existing = path.read_text(encoding="utf-8")
    if existing.lstrip().startswith("---"):
        return
    path.write_text(_frontmatter(feature, path.stem, tool) + existing, encoding="utf-8")


def _expected_outputs(feature: str) -> list[str]:
    feature_dir = features_dir() / feature
    return [str(feature_dir / API_SPEC_FILE), str(feature_dir / DECISIONS_FILE)]


def _run_subprocess(
    *,
    feature: str,
    tool: str,
    cmd: list[str],
    cwd: Path,
    timeout_sec: int,
    prompt: str,
) -> dict[str, Any]:
    span = start_cli_span(
        trace_name=f"{tool}-backend",
        span_name=f"{tool}-exec",
        metadata={"feature": feature, "cli": tool},
        prompt=prompt,
    )
    start = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=str(cwd),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        end_cli_span(
            span,
            stdout="",
            stderr=f"timeout after {timeout_sec}s",
            exit_code=None,
            elapsed_sec=float(timeout_sec),
            timed_out=True,
        )
        raise RuntimeError(f"{tool} backend timed out after {timeout_sec}s") from exc

    elapsed = round(time.time() - start, 2)
    end_cli_span(
        span,
        stdout=proc.stdout,
        stderr=proc.stderr,
        exit_code=proc.returncode,
        elapsed_sec=elapsed,
    )

    produced: list[str] = []
    for output in _expected_outputs(feature):
        path = Path(output)
        if path.is_file():
            _patch_frontmatter(path, feature, tool)
            produced.append(output)

    return {
        "feature": feature,
        "ai": tool,
        "exit_code": proc.returncode,
        "produced_files": produced,
        "stderr_tail": proc.stderr[-500:] if proc.stderr else "",
        "summary": (proc.stdout or "")[-800:],
    }


def run_codex(
    feature: str,
    dry_run: bool = False,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    """Run Codex CLI to implement backend code and backend artifacts."""
    _ensure_safe_name(feature)
    target = _require_target_project()
    feature_dir = features_dir() / feature
    if not feature_dir.is_dir():
        raise FileNotFoundError(f"Feature not found: {feature_dir}")

    prompt = _build_prompt(feature)
    cmd = [
        "codex",
        "exec",
        "--cd",
        str(target),
        "--skip-git-repo-check",
        "--full-auto",
        prompt,
    ]
    if dry_run:
        return {
            "feature": feature,
            "ai": "codex",
            "dry_run": True,
            "command": cmd,
            "prompt_preview": prompt[:500] + ("..." if len(prompt) > 500 else ""),
            "expected_outputs": _expected_outputs(feature),
        }
    if shutil.which("codex") is None:
        raise RuntimeError("codex CLI not found on PATH")
    return _run_subprocess(
        feature=feature,
        tool="codex",
        cmd=cmd,
        cwd=target,
        timeout_sec=timeout_sec,
        prompt=prompt,
    )


def run_gemini(
    feature: str,
    dry_run: bool = False,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    """Run Gemini CLI to implement backend code and backend artifacts."""
    _ensure_safe_name(feature)
    target = _require_target_project()
    feature_dir = features_dir() / feature
    if not feature_dir.is_dir():
        raise FileNotFoundError(f"Feature not found: {feature_dir}")

    prompt = _build_prompt(feature)
    cmd = ["gemini", "--approval-mode", "auto_edit", "-p", prompt]
    if dry_run:
        return {
            "feature": feature,
            "ai": "gemini",
            "dry_run": True,
            "command": cmd,
            "prompt_preview": prompt[:500] + ("..." if len(prompt) > 500 else ""),
            "expected_outputs": _expected_outputs(feature),
        }
    if shutil.which("gemini") is None:
        raise RuntimeError("gemini CLI not found on PATH")
    return _run_subprocess(
        feature=feature,
        tool="gemini",
        cmd=cmd,
        cwd=target,
        timeout_sec=timeout_sec,
        prompt=prompt,
    )


def run(
    feature: str,
    ai: str = "codex",
    dry_run: bool = False,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    """Run backend implementation with the selected AI backend."""
    if ai not in VALID_AI:
        raise ValueError(f"ai must be one of {sorted(VALID_AI)}")
    if ai == "gemini":
        return run_gemini(feature, dry_run=dry_run, timeout_sec=timeout_sec)
    return run_codex(feature, dry_run=dry_run, timeout_sec=timeout_sec)
