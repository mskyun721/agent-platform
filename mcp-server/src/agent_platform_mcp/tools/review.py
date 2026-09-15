"""Code review wrapper — delegates to the selected AI CLI."""

from __future__ import annotations

from pathlib import Path
from datetime import date
from typing import Any

from agent_platform_mcp.config import ROOT, docs_dir
from agent_platform_mcp.config import STRUCTURE_DOC
from agent_platform_mcp.tools import runner, stdout_artifacts
from agent_platform_mcp.tools.feature import _ensure_safe_name  # noqa: PLC2701

VALID_FOCUS = {"all", "security", "performance", "style", "structure"}
REVIEW_FILE = "REVIEW.md"
DEFAULT_TIMEOUT_SEC = 600


def _build_prompt(feature: str, focus: str, context: runner.ProjectContext) -> str:
    feature_dir = runner.feature_directory(feature, context)
    source_hint = runner.detect_source_hints(context.path)
    style_path = runner.coding_style_path(source_hint)
    focus_desc = {
        "all": "전반적 코드 품질 (보안/성능/가독성/아키텍처)",
        "security": "OWASP Top 10, 입력 검증, 시크릿 노출, 권한 체크",
        "performance": "N+1 쿼리, 블로킹 호출, 불필요한 I/O, 메모리 누수",
        "style": f"언어별 컨벤션, {style_path} 준수",
        "structure": f"{context.path / STRUCTURE_DOC} 의 레이어·의존·배치 규칙 준수 (현황은 graphify 로 확인)",
    }[focus]

    return runner.role_prompt("reviewer", task=(
        f"agent-platform 프로젝트의 '{feature}' 기능을 리뷰해줘.\n\n"
        f"입력 컨텍스트:\n"
        f"- 요구사항: {feature_dir}/PRD.md\n"
        f"- API 명세: {feature_dir}/API-SPEC.md (없을 수 있음)\n"
        f"- 아키텍처 결정: {feature_dir}/DECISIONS.md (없을 수 있음)\n"
        f"- 구현 코드 추정 경로: {source_hint}\n"
        f"- 표준: {ROOT / style_path}, {ROOT / 'standards/security-baseline.md'}\n\n"
        f"리뷰 포커스: {focus_desc}\n\n"
        f"지침:\n"
        f"- 실제 저장소에 존재하는 파일만 평가. 없는 파일을 가정하지 말 것.\n"
        f"- 'mcp-server/' 하위 Python 코드도 본 프로젝트의 일부임.\n\n"
        f"출력 형식 (Markdown, 아래 제목을 그대로 사용):\n"
        f"# REVIEW: {feature}\n\n"
        f"## 1. Summary\n"
        f"전반 평가를 1~2문단으로 작성.\n\n"
        f"## 2. Findings\n"
        f"항목별로 `### [HIGH|MEDIUM|LOW] 제목` 형식 사용.\n"
        f"각 항목은 `- 위치:`, `- 근거:`, `- 권장 조치:`를 포함.\n"
        f"실제 파일과 라인만 인용하고, 추정 파일은 쓰지 말 것.\n\n"
        f"## 3. Positive\n"
        f"잘 된 점과 유지할 구현 판단을 작성.\n\n"
        f"## 4. Action Items\n"
        f"체크리스트 형식으로 작성.\n\n"
        f"특정 AI 제품명이나 실행 CLI 이름을 본문에 쓰지 말고, 위 Markdown 본문만 출력."
    ), context=f"TARGET_PROJECT: {context.path}\nArtifact directory: {feature_dir}\nOutput transport: stdout Markdown only; wrapper writes REVIEW.md." + "\n\n" + runner.context_block(feature, context.path)[0])


def _frontmatter(feature: str, focus: str, ai_backend: str) -> str:
    today = date.today().isoformat()
    return (
        "---\n"
        "agent: reviewer\n"
        f"feature: {feature}\n"
        "status: draft\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        f"focus: {focus}\n"
        f"ai_backend: {ai_backend}\n"
        "---\n\n"
    )


def _run_review(
    feature: str,
    focus: str,
    cli: str,
    dry_run: bool,
    timeout_sec: int,
    *, context: runner.ProjectContext,
) -> dict[str, Any]:
    _ensure_safe_name(feature)
    if focus not in VALID_FOCUS:
        raise ValueError(f"focus must be one of {sorted(VALID_FOCUS)}")

    feature_dir = runner.feature_directory(feature, context)
    if not feature_dir.is_dir():
        raise FileNotFoundError(f"Feature not found: {feature_dir}")

    prompt = _build_prompt(feature, focus, context)
    workdir = context.path
    cmd = runner.build_cmd(cli, prompt, workdir)

    if dry_run:
        return {
            "feature": feature,
            "focus": focus,
            "dry_run": True,
            "command": cmd,
            "prompt_preview": runner.preview(prompt),
            "prompt_sources": runner.prompt_sources("reviewer") + runner.context_block(feature, context.path)[1],
            "output_path": str(feature_dir / REVIEW_FILE),
        }

    proc = runner.run_cli(cli, cmd, workdir, timeout_sec)
    runner.feature_directory(feature, context)

    body, metadata = stdout_artifacts.prepare(proc.stdout, role="reviewer", feature=feature, exit_code=proc.returncode)
    review_path = feature_dir / REVIEW_FILE
    review_path.write_text(
        stdout_artifacts.metadata_prefix(_frontmatter(feature, focus, ai_backend=cli), metadata) + body, encoding="utf-8"
    )

    return {
        "feature": feature,
        "focus": focus,
        "exit_code": proc.returncode,
        "output_path": str(review_path),
        **metadata,
        "stderr_tail": "",
        "summary": runner.preview(body, 400),
    }


def run(
    feature: str,
    focus: str = "all",
    cli: str = "auto",
    dry_run: bool = False,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Review a feature and write REVIEW.md with the selected CLI."""
    context = runner.resolve_project(root)
    from agent_platform_mcp.tools import observation
    return runner.context_result(context, observation.observed(
        context, feature, "reviewer", runner.resolve_cli(cli), dry_run, lambda: _run_review(feature, focus, runner.resolve_cli(cli), dry_run, timeout_sec, context=context)))
