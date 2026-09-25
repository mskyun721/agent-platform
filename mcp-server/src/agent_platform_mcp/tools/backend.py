"""Backend implementation wrapper for the Codex CLI."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from agent_platform_mcp.config import ROOT, docs_dir, target_project_root
from agent_platform_mcp.tools import runner
from agent_platform_mcp.tools.feature import _ensure_safe_name  # noqa: PLC2701

API_SPEC_FILE = "API-SPEC.md"
DECISIONS_FILE = "DECISIONS.md"
DEFAULT_TIMEOUT_SEC = 1800


def _build_prompt(feature: str, context: runner.ProjectContext) -> str:
    target = context.path
    feature_dir = runner.feature_directory(feature, context)
    return runner.role_prompt("backend", task=(
        f"TARGET_PROJECT: {target}\n"
        f"Feature: {feature}\n\n"
        f"Implement the backend feature described by these artifacts:\n"
        f"- PRD: {feature_dir / 'PRD.md'}\n"
        f"- TASK: {feature_dir / 'TASK.md'}\n\n"
        f"Required outputs under the same feature directory:\n"
        f"- {feature_dir / API_SPEC_FILE}\n"
        f"- {feature_dir / DECISIONS_FILE}\n\n"
        f"Structure rules (read first, they override platform standards):\n"
        f"- {target / 'ARCHITECTURE.md'}\n\n"
        f"Reference standards from the agent-platform repository:\n"
        f"- {ROOT / 'standards/reference/backend-phase-flow.md'}\n"
        f"- {ROOT / 'standards/coding-style-kotlin.md'}\n"
        f"- {ROOT / 'standards/coding-style-java.md'}\n"
        f"- {ROOT / 'standards/api-contract.md'}\n"
        f"- {ROOT / 'standards/test-policy.md'}\n"
        f"- {ROOT / 'standards/security-baseline.md'}\n\n"
        f"Rules:\n"
        f"- Work inside TARGET_PROJECT only for product code and feature artifacts.\n"
        f"- Platform artifacts are permitted only when TARGET_PROJECT explicitly selects that platform checkout.\n"
        f"- Split work into independently reviewable features; use project-appropriate architecture within each feature.\n"
        f"- Run focused tests or the smallest available verification command.\n"
        f"- Only assess files that actually exist. Do not invent missing source files.\n"
        f"- Never read or output .env, .pem, .key, credential, or secret files.\n"
        f"- Keep generated artifacts status=draft unless explicitly reviewed by a human.\n\n"
        f"After implementation, print a concise Markdown summary with changed files, "
        f"verification commands, and remaining risks."
    ), context=f"TARGET_PROJECT: {target}\nArtifact directory: {feature_dir}\nOutput transport: files; stdout summary." + "\n\n" + runner.context_block(feature, context.path)[0])


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


def _expected_outputs(feature: str, context: runner.ProjectContext) -> list[str]:
    feature_dir = runner.feature_directory(feature, context)
    return [str(feature_dir / API_SPEC_FILE), str(feature_dir / DECISIONS_FILE)]


def _run_backend(
    feature: str,
    cli: str,
    dry_run: bool,
    timeout_sec: int,
    *, context: runner.ProjectContext, model: str | None = None,
) -> dict[str, Any]:
    _ensure_safe_name(feature)
    target = context.path
    feature_dir = runner.feature_directory(feature, context)
    if not feature_dir.is_dir():
        raise FileNotFoundError(f"Feature not found: {feature_dir}")

    prompt = _build_prompt(feature, context)
    cmd = runner.build_cmd(cli, prompt, target, model=model)

    if dry_run:
        return {
            "feature": feature,
            "ai": cli,
            "dry_run": True,
            "command": cmd,
            "prompt_preview": runner.preview(prompt, 500),
            "prompt_sources": runner.prompt_sources("backend") + runner.context_block(feature, context.path)[1],
            "expected_outputs": _expected_outputs(feature, context),
        }

    proc = runner.run_cli(cli, cmd, target, timeout_sec)
    runner.feature_directory(feature, context)

    produced: list[str] = []
    for output in _expected_outputs(feature, context):
        path = Path(output)
        if path.is_file():
            _patch_frontmatter(path, feature, cli)
            produced.append(output)

    return {
        "feature": feature,
        "ai": cli,
        "exit_code": proc.returncode,
        "produced_files": produced,
        "stderr_tail": runner.stderr_tail(proc),
        "summary": (proc.stdout or "")[-800:],
    }


def run(
    feature: str,
    cli: str = "auto",
    dry_run: bool = False,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    root: str | Path | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Implement backend code/artifacts with the selected CLI."""
    context = runner.resolve_project(root)
    return runner.execute(context, feature, "backend", cli, model, dry_run,
        lambda chosen, selected: _run_backend(feature, chosen, dry_run, timeout_sec, context=context, model=selected))
