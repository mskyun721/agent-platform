"""Code review wrapper — delegates to Gemini CLI (default) or Codex CLI."""

from __future__ import annotations

import shutil
import subprocess
import time
from datetime import date
from pathlib import Path
from typing import Any

from agent_platform_mcp.config import ROOT, features_dir, preferred_cli
from agent_platform_mcp.observability import end_cli_span, get_client, start_cli_span
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


def _build_prompt_fallback(feature: str, focus: str) -> str:
    feature_dir = features_dir() / feature
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


def _build_prompt(feature: str, focus: str) -> str:
    lf = get_client()
    if lf:
        try:
            feature_dir = features_dir() / feature
            focus_desc = {
                "all": "전반적 코드 품질 (보안/성능/가독성/아키텍처)",
                "security": "OWASP Top 10, 입력 검증, 시크릿 노출, 권한 체크",
                "performance": "N+1 쿼리, 블로킹 호출, 불필요한 I/O, 메모리 누수",
                "style": "언어별 컨벤션, standards/coding-style.md 준수",
                "hexagonal": "헥사곤 아키텍처 준수 (도메인이 어댑터 참조 금지 등)",
            }[focus]
            prompt_obj = lf.get_prompt("gemini-review")
            return prompt_obj.compile(
                feature=feature,
                feature_dir=str(feature_dir),
                focus=focus,
                focus_desc=focus_desc,
                source_hint=_detect_source_hints(),
            )
        except Exception:
            pass
    return _build_prompt_fallback(feature, focus)


def _frontmatter(feature: str, focus: str, tool: str = "gemini") -> str:
    today = date.today().isoformat()
    return (
        "---\n"
        "agent: reviewer\n"
        f"feature: {feature}\n"
        "status: draft\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        f"focus: {focus}\n"
        f"tool: {tool}\n"
        "---\n\n"
    )


def run_gemini(
    feature: str,
    focus: str = "all",
    dry_run: bool = False,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    """Run Gemini CLI to review a feature. Writes REVIEW.md with the output."""
    _ensure_safe_name(feature)
    if focus not in VALID_FOCUS:
        raise ValueError(f"focus must be one of {sorted(VALID_FOCUS)}")

    feature_dir = features_dir() / feature
    if not feature_dir.is_dir():
        raise FileNotFoundError(f"Feature not found: {feature_dir}")

    prompt = _build_prompt(feature, focus)
    cmd = ["gemini", "--approval-mode", "plan", "-p", prompt]

    if dry_run:
        return {
            "feature": feature,
            "focus": focus,
            "dry_run": True,
            "command": cmd,
            "prompt_preview": prompt[:300] + ("…" if len(prompt) > 300 else ""),
            "output_path": str(feature_dir / REVIEW_FILE),
        }

    if shutil.which("gemini") is None:
        raise RuntimeError("gemini CLI not found on PATH")

    span = start_cli_span(
        trace_name="gemini-review",
        span_name="gemini-exec",
        metadata={"feature": feature, "focus": focus, "cli": "gemini"},
        prompt=prompt,
    )

    start = time.time()
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
        end_cli_span(
            span,
            stdout="",
            stderr=f"timeout after {timeout_sec}s",
            exit_code=None,
            elapsed_sec=float(timeout_sec),
            timed_out=True,
        )
        raise RuntimeError(f"gemini timed out after {timeout_sec}s") from exc

    elapsed = round(time.time() - start, 2)
    end_cli_span(
        span,
        stdout=proc.stdout,
        stderr=proc.stderr,
        exit_code=proc.returncode,
        elapsed_sec=elapsed,
    )

    body = proc.stdout.strip() or "_(gemini returned empty stdout)_"
    review_path = feature_dir / REVIEW_FILE
    review_path.write_text(_frontmatter(feature, focus, tool="gemini") + body + "\n", encoding="utf-8")

    return {
        "feature": feature,
        "focus": focus,
        "exit_code": proc.returncode,
        "output_path": str(review_path),
        "stderr_tail": proc.stderr[-500:] if proc.stderr else "",
        "summary": body[:400] + ("…" if len(body) > 400 else ""),
    }


def run(
    feature: str,
    focus: str = "all",
    dry_run: bool = False,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    cli: str | None = None,
) -> dict[str, Any]:
    """Run review using preferred CLI (reads .agent-config.json). Can override with cli arg."""
    chosen = cli if cli in {"gemini", "codex"} else preferred_cli()
    if chosen == "gemini":
        return run_gemini(feature, focus=focus, dry_run=dry_run, timeout_sec=timeout_sec)
    return run_codex(feature, focus=focus, dry_run=dry_run, timeout_sec=timeout_sec)


def run_codex(
    feature: str,
    focus: str = "all",
    dry_run: bool = False,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    """Run Codex CLI to review a feature. Writes REVIEW.md with the output."""
    _ensure_safe_name(feature)
    if focus not in VALID_FOCUS:
        raise ValueError(f"focus must be one of {sorted(VALID_FOCUS)}")

    feature_dir = features_dir() / feature
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

    span = start_cli_span(
        trace_name="codex-review",
        span_name="codex-exec",
        metadata={"feature": feature, "focus": focus, "cli": "codex"},
        prompt=prompt,
    )

    start = time.time()
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
        end_cli_span(
            span,
            stdout="",
            stderr=f"timeout after {timeout_sec}s",
            exit_code=None,
            elapsed_sec=float(timeout_sec),
            timed_out=True,
        )
        raise RuntimeError(f"codex exec timed out after {timeout_sec}s") from exc

    elapsed = round(time.time() - start, 2)
    end_cli_span(
        span,
        stdout=proc.stdout,
        stderr=proc.stderr,
        exit_code=proc.returncode,
        elapsed_sec=elapsed,
    )

    body = proc.stdout.strip() or "_(codex returned empty stdout)_"
    review_path = feature_dir / REVIEW_FILE
    review_path.write_text(_frontmatter(feature, focus, tool="codex") + body + "\n", encoding="utf-8")

    return {
        "feature": feature,
        "focus": focus,
        "exit_code": proc.returncode,
        "output_path": str(review_path),
        "stderr_tail": proc.stderr[-500:] if proc.stderr else "",
        "summary": body[:400] + ("…" if len(body) > 400 else ""),
    }
