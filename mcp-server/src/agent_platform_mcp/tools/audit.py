"""Security/audit wrapper — delegates to the Codex CLI."""

from __future__ import annotations

from pathlib import Path
from datetime import date
from typing import Any

from agent_platform_mcp.config import ROOT, docs_dir
from agent_platform_mcp.tools import runner, stdout_artifacts
from agent_platform_mcp.tools.feature import _ensure_safe_name  # noqa: PLC2701

VALID_SCOPE = {"owasp", "secrets", "deps", "all"}
AUDIT_FILE = "SECURITY-AUDIT.md"
DEFAULT_TIMEOUT_SEC = 600


def _build_prompt(feature: str, scope: str, context: runner.ProjectContext) -> str:
    feature_dir = runner.feature_directory(feature, context)
    scope_desc = {
        "owasp": "OWASP Top 10 (인젝션, 인증/세션, 권한, XSS, CSRF 등)",
        "secrets": "하드코딩된 시크릿/키/토큰/자격증명 탐지",
        "deps": "의존성 취약점 (CVE, outdated versions)",
        "all": "OWASP + 시크릿 + 의존성 통합 감사",
    }[scope]
    source_hint = runner.detect_source_hints(context.path)

    return runner.role_prompt("security", task=(
        f"agent-platform '{feature}' 기능에 대해 보안 감사를 수행해줘.\n\n"
        f"검사 범위: {scope_desc}\n\n"
        f"입력:\n"
        f"- 요구사항: {feature_dir}/PRD.md\n"
        f"- API 명세: {feature_dir}/API-SPEC.md (없을 수 있음)\n"
        f"- 구현 코드 추정 경로: {source_hint}\n"
        f"- 보안 기준: {ROOT / 'standards/security-baseline.md'}\n\n"
        f"지침:\n"
        f"- 실제 존재 파일만 평가. 없는 파일은 평가 대상에서 제외.\n"
        f"- Python (mcp-server) 코드도 감사 범위에 포함.\n\n"
        f"출력 (Markdown, 제목을 그대로 사용):\n"
        f"# SECURITY AUDIT: {feature}\n"
        f"## 1. Risk Level\nOverall: Critical/High/Medium/Low/None\n"
        f"## 2. Findings\n`### [Severity] 제목` + 근거(파일:라인) + 재현/영향/권장 조치\n"
        f"## 3. Checklist\n이번 감사에서 통과한 항목\n"
        f"## 4. Recommendations\n우선순위 조치 리스트\n\n"
        f"위 Markdown 본문만 출력, 설명·인사말 제외."
    ), context=f"TARGET_PROJECT: {context.path}\nArtifact directory: {feature_dir}\nOutput transport: stdout Markdown only; wrapper writes SECURITY-AUDIT.md." + "\n\n" + runner.context_block(feature, context.path)[0])


def _frontmatter(feature: str, scope: str, tool: str) -> str:
    today = date.today().isoformat()
    return (
        "---\n"
        "agent: security\n"
        f"feature: {feature}\n"
        "status: draft\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        f"scope: {scope}\n"
        f"tool: {tool}\n"
        "---\n\n"
    )


def _run_audit(
    feature: str,
    scope: str,
    cli: str,
    dry_run: bool,
    timeout_sec: int,
    *, context: runner.ProjectContext,
) -> dict[str, Any]:
    _ensure_safe_name(feature)
    if scope not in VALID_SCOPE:
        raise ValueError(f"scope must be one of {sorted(VALID_SCOPE)}")

    feature_dir = runner.feature_directory(feature, context)
    if not feature_dir.is_dir():
        raise FileNotFoundError(f"Feature not found: {feature_dir}")

    prompt = _build_prompt(feature, scope, context)
    workdir = context.path
    cmd = runner.build_cmd(cli, prompt, workdir)

    if dry_run:
        return {
            "feature": feature,
            "scope": scope,
            "dry_run": True,
            "command": cmd,
            "prompt_preview": runner.preview(prompt),
            "prompt_sources": runner.prompt_sources("security") + runner.context_block(feature, context.path)[1],
            "output_path": str(feature_dir / AUDIT_FILE),
        }

    proc = runner.run_cli(cli, cmd, workdir, timeout_sec)
    runner.feature_directory(feature, context)

    body, metadata = stdout_artifacts.prepare(proc.stdout, role="security", feature=feature, exit_code=proc.returncode)
    audit_path = feature_dir / AUDIT_FILE
    audit_path.write_text(
        stdout_artifacts.metadata_prefix(_frontmatter(feature, scope, tool=cli), metadata) + body, encoding="utf-8"
    )

    return {
        "feature": feature,
        "scope": scope,
        "exit_code": proc.returncode,
        "output_path": str(audit_path),
        **metadata,
        "stderr_tail": "",
        "summary": runner.preview(body, 400),
    }


def run(
    feature: str,
    scope: str = "all",
    cli: str = "auto",
    dry_run: bool = False,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Security-audit a feature and write SECURITY-AUDIT.md with the selected CLI."""
    context = runner.resolve_project(root)
    return runner.context_result(context, _run_audit(feature, scope, runner.resolve_cli(cli), dry_run, timeout_sec, context=context))
