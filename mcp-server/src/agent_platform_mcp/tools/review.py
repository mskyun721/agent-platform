"""Code review wrapper — delegates to Codex CLI."""

from __future__ import annotations

import shutil
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from agent_platform_mcp.config import FEATURES_DIR, ROOT
from agent_platform_mcp.tools.feature import _ensure_safe_name  # noqa: PLC2701

VALID_FOCUS = {"all", "security", "performance", "style", "hexagonal"}
REVIEW_FILE = "REVIEW.md"
DEFAULT_TIMEOUT_SEC = 600


def _detect_source_hints() -> str:
    """Scan repository root for likely source locations and return a hint string."""
    hints: list[str] = []
    candidates = [
        ("src/main/kotlin/", "Kotlin/Spring"),
        ("src/main/java/", "Java"),
        ("src/", "generic src tree"),
        ("app/", "app module"),
        ("server/", "server module"),
        ("mcp-server/src/", "Python (mcp-server)"),
    ]
    for rel, label in candidates:
        if (ROOT / rel).is_dir():
            hints.append(f"{rel} ({label})")
    return ", ".join(hints) if hints else "(auto-detect within repository)"


def _build_prompt(feature: str, focus: str) -> str:
    feature_dir = FEATURES_DIR / feature
    focus_desc = {
        "all": "전반적 코드 품질 (보안/성능/가독성/아키텍처)",
        "security": "OWASP Top 10, 입력 검증, 시크릿 노출, 권한 체크",
        "performance": "N+1 쿼리, 블로킹 호출, 불필요한 I/O, 메모리 누수",
        "style": "언어별 컨벤션, standards/coding-style.md 준수",
        "hexagonal": "헥사곤 아키텍처 준수 (도메인이 어댑터 참조 금지 등)",
    }[focus]
    source_hint = _detect_source_hints()

    return (
        f"agent-platform 프로젝트의 '{feature}' 기능을 리뷰해줘.\n\n"
        f"입력 컨텍스트:\n"
        f"- 요구사항: {feature_dir}/PRD.md\n"
        f"- API 명세: {feature_dir}/API-SPEC.md (없을 수 있음)\n"
        f"- 아키텍처 결정: {feature_dir}/DECISIONS.md (없을 수 있음)\n"
        f"- 구현 코드 추정 경로: {source_hint}\n"
        f"- 표준: standards/coding-style.md, standards/security-baseline.md\n\n"
        f"리뷰 포커스: {focus_desc}\n\n"
        f"지침:\n"
        f"- 실제 저장소에 존재하는 파일만 평가. 없는 파일을 가정하지 말 것.\n"
        f"- 'mcp-server/' 하위 Python 코드도 본 프로젝트의 일부임.\n\n"
        f"출력 형식 (Markdown):\n"
        f"1. Summary — 전반 평가 1~2문단\n"
        f"2. Findings — 항목별로 `### [HIGH|MEDIUM|LOW] 제목` + 위치 + 권장 조치\n"
        f"3. Positive — 잘 된 점\n"
        f"4. Action Items — 체크리스트\n\n"
        f"주석이나 설명 없이 위 Markdown 본문만 출력."
    )


def _frontmatter(feature: str, focus: str) -> str:
    today = date.today().isoformat()
    return (
        "---\n"
        "agent: reviewer\n"
        f"feature: {feature}\n"
        "status: draft\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        f"focus: {focus}\n"
        "tool: codex\n"
        "---\n\n"
    )


def run_codex(
    feature: str,
    focus: str = "all",
    dry_run: bool = False,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    """Run Codex CLI to review a feature. Writes REVIEW.md with the output.

    Args:
        feature: feature name under docs/features/
        focus: one of {all, security, performance, style, hexagonal}
        dry_run: if True, returns the prompt and command without invoking Codex
        timeout_sec: hard subprocess timeout
    """
    _ensure_safe_name(feature)
    if focus not in VALID_FOCUS:
        raise ValueError(f"focus must be one of {sorted(VALID_FOCUS)}")

    feature_dir = FEATURES_DIR / feature
    if not feature_dir.is_dir():
        raise FileNotFoundError(f"Feature not found: {feature_dir}")

    prompt = _build_prompt(feature, focus)
    cmd = [
        "codex",
        "exec",
        "--cd",
        str(ROOT),
        "--skip-git-repo-check",
        "--full-auto",
        prompt,
    ]

    if dry_run:
        return {
            "feature": feature,
            "focus": focus,
            "dry_run": True,
            "command": cmd,
            "prompt_preview": prompt[:300] + ("…" if len(prompt) > 300 else ""),
            "output_path": str(feature_dir / REVIEW_FILE),
        }

    if shutil.which("codex") is None:
        raise RuntimeError("codex CLI not found on PATH")

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
        raise RuntimeError(f"codex exec timed out after {timeout_sec}s") from exc

    body = proc.stdout.strip() or "_(codex returned empty stdout)_"
    review_path = feature_dir / REVIEW_FILE
    review_path.write_text(_frontmatter(feature, focus) + body + "\n", encoding="utf-8")

    return {
        "feature": feature,
        "focus": focus,
        "exit_code": proc.returncode,
        "output_path": str(review_path),
        "stderr_tail": proc.stderr[-500:] if proc.stderr else "",
        "summary": body[:400] + ("…" if len(body) > 400 else ""),
    }
