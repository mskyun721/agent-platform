"""Security/audit wrapper — delegates to Gemini CLI."""

from __future__ import annotations

import shutil
import subprocess
from datetime import date
from typing import Any

from agent_platform_mcp.config import FEATURES_DIR, ROOT
from agent_platform_mcp.tools.feature import _ensure_safe_name  # noqa: PLC2701

VALID_SCOPE = {"owasp", "secrets", "deps", "all"}
AUDIT_FILE = "SECURITY-AUDIT.md"
DEFAULT_TIMEOUT_SEC = 600


def _detect_source_hints() -> str:
    hints: list[str] = []
    for rel, label in [
        ("src/main/kotlin/", "Kotlin/Spring"),
        ("src/main/java/", "Java"),
        ("src/", "generic src"),
        ("app/", "app"),
        ("server/", "server"),
        ("mcp-server/src/", "Python (mcp-server)"),
    ]:
        if (ROOT / rel).is_dir():
            hints.append(f"{rel} ({label})")
    return ", ".join(hints) if hints else "(auto-detect)"


def _build_prompt(feature: str, scope: str) -> str:
    feature_dir = FEATURES_DIR / feature
    scope_desc = {
        "owasp": "OWASP Top 10 (인젝션, 인증/세션, 권한, XSS, CSRF 등)",
        "secrets": "하드코딩된 시크릿/키/토큰/자격증명 탐지",
        "deps": "의존성 취약점 (CVE, outdated versions)",
        "all": "OWASP + 시크릿 + 의존성 통합 감사",
    }[scope]
    source_hint = _detect_source_hints()

    return (
        f"agent-platform '{feature}' 기능에 대해 보안 감사를 수행해줘.\n\n"
        f"검사 범위: {scope_desc}\n\n"
        f"입력:\n"
        f"- 요구사항: {feature_dir}/PRD.md\n"
        f"- API 명세: {feature_dir}/API-SPEC.md (없을 수 있음)\n"
        f"- 구현 코드 추정 경로: {source_hint}\n"
        f"- 보안 기준: standards/security-baseline.md\n\n"
        f"지침:\n"
        f"- 실제 존재 파일만 평가. 없는 파일은 평가 대상에서 제외.\n"
        f"- Python (mcp-server) 코드도 감사 범위에 포함.\n\n"
        f"출력 (Markdown):\n"
        f"1. Risk Level — Overall: Critical/High/Medium/Low/None\n"
        f"2. Findings — `### [Severity] 제목` + 근거(파일:라인) + 재현/영향/권장 조치\n"
        f"3. Checklist — 이번 감사에서 통과한 항목\n"
        f"4. Recommendations — 우선순위 조치 리스트\n\n"
        f"위 Markdown 본문만 출력, 설명·인사말 제외."
    )


def _frontmatter(feature: str, scope: str) -> str:
    today = date.today().isoformat()
    return (
        "---\n"
        "agent: security\n"
        f"feature: {feature}\n"
        "status: draft\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        f"scope: {scope}\n"
        "tool: gemini\n"
        "---\n\n"
    )


def run_gemini(
    feature: str,
    scope: str = "all",
    dry_run: bool = False,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    """Run Gemini CLI to audit a feature. Writes SECURITY-AUDIT.md."""
    _ensure_safe_name(feature)
    if scope not in VALID_SCOPE:
        raise ValueError(f"scope must be one of {sorted(VALID_SCOPE)}")

    feature_dir = FEATURES_DIR / feature
    if not feature_dir.is_dir():
        raise FileNotFoundError(f"Feature not found: {feature_dir}")

    prompt = _build_prompt(feature, scope)
    cmd = ["gemini", "--approval-mode", "plan", "-p", prompt]

    if dry_run:
        return {
            "feature": feature,
            "scope": scope,
            "dry_run": True,
            "command": cmd,
            "prompt_preview": prompt[:300] + ("…" if len(prompt) > 300 else ""),
            "output_path": str(feature_dir / AUDIT_FILE),
        }

    if shutil.which("gemini") is None:
        raise RuntimeError("gemini CLI not found on PATH")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=str(ROOT),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"gemini timed out after {timeout_sec}s") from exc

    body = proc.stdout.strip() or "_(gemini returned empty stdout)_"
    audit_path = feature_dir / AUDIT_FILE
    audit_path.write_text(_frontmatter(feature, scope) + body + "\n", encoding="utf-8")

    return {
        "feature": feature,
        "scope": scope,
        "exit_code": proc.returncode,
        "output_path": str(audit_path),
        "stderr_tail": proc.stderr[-500:] if proc.stderr else "",
        "summary": body[:400] + ("…" if len(body) > 400 else ""),
    }
