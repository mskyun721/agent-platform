"""QA test-plan/test-code wrapper — delegates to Codex CLI."""

from __future__ import annotations

import shutil
import subprocess
from datetime import date
from typing import Any

from agent_platform_mcp.config import FEATURES_DIR, ROOT
from agent_platform_mcp.tools.feature import _ensure_safe_name  # noqa: PLC2701

VALID_SCOPE = {"plan", "test-gen", "regression", "all"}
TEST_PLAN_FILE = "TEST-PLAN.md"
DEFAULT_TIMEOUT_SEC = 900


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
        "plan": "TEST-PLAN.md 문서만 작성. 테스트 코드는 생성하지 않음.",
        "test-gen": "누락된 테스트 코드 생성. AC/에러 케이스/동시성/경계값/보안 커버.",
        "regression": "기존 관련 기능 회귀 테스트 설계·실행. 변경 엔티티 사용처 전수 검토.",
        "all": "TEST-PLAN 작성 + 누락 테스트 코드 생성 + 회귀 검증 통합.",
    }[scope]
    source_hint = _detect_source_hints()

    return (
        f"agent-platform '{feature}' 기능에 대한 QA 작업을 수행해줘.\n\n"
        f"작업 범위: {scope_desc}\n\n"
        f"입력:\n"
        f"- 요구사항: {feature_dir}/PRD.md (AC 목록)\n"
        f"- API 명세: {feature_dir}/API-SPEC.md (에러 케이스)\n"
        f"- 아키텍처 결정: {feature_dir}/DECISIONS.md\n"
        f"- 리뷰 결과: {feature_dir}/REVIEW.md (있으면 특별 검증 요청 반영)\n"
        f"- 보안 감사: {feature_dir}/SECURITY-AUDIT.md (있으면)\n"
        f"- 구현 코드: {source_hint}\n"
        f"- 테스트 표준: standards/test-policy.md\n"
        f"- 템플릿: templates/TEST-PLAN.md\n\n"
        f"산출물:\n"
        f"1. **TEST-PLAN.md** 를 `{feature_dir}/TEST-PLAN.md` 에 작성\n"
        f"   - 템플릿 구조 준수 (Front-matter 포함)\n"
        f"   - AC × 테스트 레벨 (Unit/Integration/E2E/Load) 매트릭스\n"
        f"   - 각 시나리오 Given-When-Then\n"
        f"   - 동시성/경계값/보안 시나리오 필수 포함\n"
        f"2. (scope=test-gen|all) 누락된 테스트 코드를 실제 저장소에 추가\n"
        f"   - Kotlin 프로젝트: `src/test/kotlin/` 하위\n"
        f"   - Python 프로젝트: `tests/` 또는 대응 디렉터리\n"
        f"   - 테스트 프레임워크는 기존 테스트 관례 따름\n"
        f"3. (scope=all) 전체 테스트 실행 후 결과 요약을 stdout 에 출력\n\n"
        f"지침:\n"
        f"- Happy path 만 검증 금지 — 에러/경계/동시성/보안 시나리오 필수\n"
        f"- P0/P1 결함 발견 시 `{feature_dir}/bugs/BUG-<id>.md` 생성\n"
        f"- 실제 존재 파일만 기준으로 판단, 없는 파일 가정 금지\n\n"
        f"출력 (stdout): 수행 결과 요약과 남은 이슈 리스트를 Markdown 으로 출력."
    )


def _plan_frontmatter_prefix(feature: str, scope: str) -> str:
    today = date.today().isoformat()
    return (
        "---\n"
        "agent: qa\n"
        f"feature: {feature}\n"
        "status: draft\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        f"scope: {scope}\n"
        "tool: codex\n"
        "---\n\n"
    )


def run_codex(
    feature: str,
    scope: str = "plan",
    dry_run: bool = False,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    """Run Codex CLI to perform QA work.

    Args:
        feature: feature name under docs/features/
        scope: one of {plan, test-gen, regression, all}
        dry_run: returns the prompt and command without invoking Codex
    """
    _ensure_safe_name(feature)
    if scope not in VALID_SCOPE:
        raise ValueError(f"scope must be one of {sorted(VALID_SCOPE)}")

    feature_dir = FEATURES_DIR / feature
    if not feature_dir.is_dir():
        raise FileNotFoundError(f"Feature not found: {feature_dir}")

    prompt = _build_prompt(feature, scope)
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
            "scope": scope,
            "dry_run": True,
            "command": cmd,
            "prompt_preview": prompt[:300] + ("…" if len(prompt) > 300 else ""),
            "output_path": str(feature_dir / TEST_PLAN_FILE),
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

    # Ensure TEST-PLAN front-matter is present (Codex may or may not add it).
    test_plan = feature_dir / TEST_PLAN_FILE
    if test_plan.is_file():
        existing = test_plan.read_text(encoding="utf-8")
        if not existing.lstrip().startswith("---"):
            test_plan.write_text(
                _plan_frontmatter_prefix(feature, scope) + existing,
                encoding="utf-8",
            )

    return {
        "feature": feature,
        "scope": scope,
        "exit_code": proc.returncode,
        "test_plan_path": str(test_plan),
        "test_plan_exists": test_plan.is_file(),
        "stderr_tail": proc.stderr[-500:] if proc.stderr else "",
        "summary": (proc.stdout or "")[-800:],
    }
