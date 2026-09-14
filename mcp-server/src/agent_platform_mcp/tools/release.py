"""Release/CICD wrapper — delegates to the Codex CLI."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from agent_platform_mcp.config import ROOT, cli_model, docs_dir
from agent_platform_mcp.tools import runner
from agent_platform_mcp.tools.feature import _ensure_safe_name  # noqa: PLC2701

VALID_ACTION = {"pr-body", "release-note", "checklist", "all"}
RELEASE_FILE = "RELEASE-NOTE.md"
PR_BODY_FILE = "PR-BODY.md"
CHECKLIST_FILE = "DEPLOY-CHECKLIST.md"
DEFAULT_TIMEOUT_SEC = 600

_ACTION_OUTPUTS: dict[str, list[str]] = {
    "pr-body": [PR_BODY_FILE],
    "release-note": [RELEASE_FILE],
    "checklist": [CHECKLIST_FILE],
    "all": [PR_BODY_FILE, RELEASE_FILE, CHECKLIST_FILE],
}


def _build_prompt(feature: str, action: str, context: runner.ProjectContext) -> str:
    feature_dir = runner.feature_directory(feature, context)
    action_desc = {
        "pr-body": "GitHub PR body 작성 (templates/PR-TEMPLATE.md 구조 준수)",
        "release-note": "RELEASE-NOTE.md 작성 (Semantic Versioning, 마이그레이션, 롤백 포함)",
        "checklist": "배포 체크리스트 작성 (모니터링/알람/카나리/롤백 트리거)",
        "all": "PR body + RELEASE-NOTE + 배포 체크리스트 통합 생성",
    }[action]

    return runner.role_prompt("cicd", task=(
        f"agent-platform '{feature}' 기능의 배포 산출물을 작성해줘.\n\n"
        f"작업: {action_desc}\n\n"
        f"입력 컨텍스트 (실제 존재하며 해당 작업과 관련된 것만):\n"
        f"- 요구사항: {feature_dir}/PRD.md\n"
        f"- API 명세: {feature_dir}/API-SPEC.md\n"
        f"- 아키텍처 결정: {feature_dir}/DECISIONS.md\n"
        f"- 리뷰 결과: {feature_dir}/REVIEW.md\n"
        f"- 보안 감사: {feature_dir}/SECURITY-AUDIT.md\n"
        f"- 테스트 계획: {feature_dir}/TEST-PLAN.md\n"
        f"- 커밋 내역: `git log --oneline` 로 최근 변경 확인\n"
        f"- 템플릿: {ROOT / 'templates/PR-TEMPLATE.md'}, {ROOT / 'templates/RELEASE-NOTE.md'}\n"
        f"- 규약: {ROOT / 'standards/commit-convention.md'}\n\n"
        f"산출물 (각 파일은 Front-matter 포함, status=draft):\n"
        f"- action=pr-body → {feature_dir}/{PR_BODY_FILE} 작성\n"
        f"- action=release-note → {feature_dir}/{RELEASE_FILE} 작성\n"
        f"- action=checklist → {feature_dir}/{CHECKLIST_FILE} 작성\n"
        f"- action=all → 위 3개 모두 작성\n\n"
        f"지침:\n"
        f"- PR 제목은 Conventional Commits 형식, 70자 이내\n"
        f"- RELEASE-NOTE: Breaking change, 마이그레이션, 롤백 절차 명확히\n"
        f"- 체크리스트: 모니터링 대시보드/알람/롤백 명령까지 구체 명시\n"
        f"- Status 는 draft 로 설정 — 최종 승인은 사람이 함\n\n"
        f"출력 (stdout): 생성한 파일 목록과 주요 결정사항 요약."
    ), context=f"TARGET_PROJECT: {context.path}\nArtifact directory: {feature_dir}\nOutput transport: files; stdout summary. Generate documents only; do not push, create PRs, merge, or deploy." + "\n\n" + runner.context_block(feature, context.path)[0])


def _frontmatter(feature: str, action: str, path_stem: str, tool: str) -> str:
    today = date.today().isoformat()
    return (
        "---\n"
        "agent: cicd\n"
        f"feature: {feature}\n"
        "status: draft\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        f"action: {action}\n"
        f"artifact: {path_stem}\n"
        f"tool: {tool}\n"
        "---\n\n"
    )


def _patch_frontmatter(path: Path, feature: str, action: str, tool: str) -> None:
    if not path.is_file():
        return
    existing = path.read_text(encoding="utf-8")
    if existing.lstrip().startswith("---"):
        return
    path.write_text(
        _frontmatter(feature, action, path.stem, tool=tool) + existing,
        encoding="utf-8",
    )


def _run_release(
    feature: str,
    action: str,
    cli: str,
    dry_run: bool,
    timeout_sec: int,
    model: str | None = None,
    *, context: runner.ProjectContext,
) -> dict[str, Any]:
    _ensure_safe_name(feature)
    if action not in VALID_ACTION:
        raise ValueError(f"action must be one of {sorted(VALID_ACTION)}")

    feature_dir = runner.feature_directory(feature, context)
    if not feature_dir.is_dir():
        raise FileNotFoundError(f"Feature not found: {feature_dir}")

    prompt = _build_prompt(feature, action, context)
    workdir = context.path
    cmd = runner.build_cmd(cli, prompt, workdir, model=model)

    if dry_run:
        result: dict[str, Any] = {
            "feature": feature,
            "action": action,
            "dry_run": True,
            "command": cmd,
            "prompt_preview": runner.preview(prompt),
            "prompt_sources": runner.prompt_sources("cicd") + runner.context_block(feature, context.path)[1],
            "expected_outputs": [
                str(feature_dir / f) for f in _ACTION_OUTPUTS[action]
            ],
        }
        if model:
            result["model"] = model
        return result

    proc = runner.run_cli(cli, cmd, workdir, timeout_sec)
    runner.feature_directory(feature, context)

    # Ensure front-matter on artifacts the CLI may have produced.
    produced: list[str] = []
    for fname, act in [
        (PR_BODY_FILE, "pr-body"),
        (RELEASE_FILE, "release-note"),
        (CHECKLIST_FILE, "checklist"),
    ]:
        path = feature_dir / fname
        if path.is_file():
            _patch_frontmatter(path, feature, act, tool=cli)
            produced.append(str(path))

    result = {
        "feature": feature,
        "action": action,
        "exit_code": proc.returncode,
        "produced_files": produced,
        "stderr_tail": runner.stderr_tail(proc),
        "summary": (proc.stdout or "")[-800:],
    }
    if model:
        result["model"] = model
    return result


def run(
    feature: str,
    action: str = "all",
    cli: str = "auto",
    model: str | None = None,
    dry_run: bool = False,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Produce CICD artifacts (PR body / RELEASE-NOTE / checklist) with the selected CLI."""
    chosen = runner.resolve_cli(cli)
    # Explicit model wins; otherwise the per-CLI pin from .agent-config.json, if any.
    resolved_model = model or cli_model(chosen)
    context = runner.resolve_project(root)
    from agent_platform_mcp.tools import observation
    return runner.context_result(context, observation.observed(
        context, feature, "cicd", chosen, dry_run, lambda: _run_release(feature, action, chosen, dry_run, timeout_sec, model=resolved_model, context=context), model=resolved_model))
