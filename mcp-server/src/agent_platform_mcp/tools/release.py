"""Release/CICD wrapper — delegates to Gemini CLI."""

from __future__ import annotations

import shutil
import subprocess
from datetime import date
from typing import Any

from agent_platform_mcp.config import FEATURES_DIR, ROOT
from agent_platform_mcp.tools.feature import _ensure_safe_name  # noqa: PLC2701

VALID_ACTION = {"pr-body", "release-note", "checklist", "all"}
RELEASE_FILE = "RELEASE-NOTE.md"
PR_BODY_FILE = "PR-BODY.md"
CHECKLIST_FILE = "DEPLOY-CHECKLIST.md"
DEFAULT_TIMEOUT_SEC = 600
DEFAULT_MODEL = "gemini-2.5-flash"


def _build_prompt(feature: str, action: str) -> str:
    feature_dir = FEATURES_DIR / feature
    action_desc = {
        "pr-body": "GitHub PR body 작성 (templates/PR-TEMPLATE.md 구조 준수)",
        "release-note": "RELEASE-NOTE.md 작성 (Semantic Versioning, 마이그레이션, 롤백 포함)",
        "checklist": "배포 체크리스트 작성 (모니터링/알람/카나리/롤백 트리거)",
        "all": "PR body + RELEASE-NOTE + 배포 체크리스트 통합 생성",
    }[action]

    return (
        f"agent-platform '{feature}' 기능의 배포 산출물을 작성해줘.\n\n"
        f"작업: {action_desc}\n\n"
        f"입력 컨텍스트 (전부 읽고 반영):\n"
        f"- 요구사항: {feature_dir}/PRD.md\n"
        f"- API 명세: {feature_dir}/API-SPEC.md\n"
        f"- 아키텍처 결정: {feature_dir}/DECISIONS.md\n"
        f"- 리뷰 결과: {feature_dir}/REVIEW.md\n"
        f"- 보안 감사: {feature_dir}/SECURITY-AUDIT.md\n"
        f"- 테스트 계획: {feature_dir}/TEST-PLAN.md\n"
        f"- 커밋 내역: `git log --oneline` 로 최근 변경 확인\n"
        f"- 템플릿: templates/PR-TEMPLATE.md, templates/RELEASE-NOTE.md\n"
        f"- 규약: standards/commit-convention.md\n\n"
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
    )


def _ensure_frontmatter(feature: str, action: str, path_stem: str) -> str:
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
        "tool: gemini\n"
        "---\n\n"
    )


def _patch_frontmatter(path, feature: str, action: str) -> None:
    if not path.is_file():
        return
    existing = path.read_text(encoding="utf-8")
    if existing.lstrip().startswith("---"):
        return
    path.write_text(
        _ensure_frontmatter(feature, action, path.stem) + existing,
        encoding="utf-8",
    )


def run_gemini(
    feature: str,
    action: str = "all",
    dry_run: bool = False,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Run Gemini CLI to produce CICD artifacts (PR body / RELEASE-NOTE / checklist).

    Args:
        feature: feature name under docs/features/
        action: one of {pr-body, release-note, checklist, all}
        model: Gemini model (default: gemini-2.5-flash for speed/quota)
    """
    _ensure_safe_name(feature)
    if action not in VALID_ACTION:
        raise ValueError(f"action must be one of {sorted(VALID_ACTION)}")

    feature_dir = FEATURES_DIR / feature
    if not feature_dir.is_dir():
        raise FileNotFoundError(f"Feature not found: {feature_dir}")

    prompt = _build_prompt(feature, action)
    # approval-mode=auto_edit lets Gemini write files it was told to write.
    cmd = ["gemini", "-m", model, "--approval-mode", "auto_edit", "-p", prompt]

    if dry_run:
        expected_outputs = {
            "pr-body": [PR_BODY_FILE],
            "release-note": [RELEASE_FILE],
            "checklist": [CHECKLIST_FILE],
            "all": [PR_BODY_FILE, RELEASE_FILE, CHECKLIST_FILE],
        }[action]
        return {
            "feature": feature,
            "action": action,
            "model": model,
            "dry_run": True,
            "command": cmd,
            "prompt_preview": prompt[:300] + ("…" if len(prompt) > 300 else ""),
            "expected_outputs": [str(feature_dir / f) for f in expected_outputs],
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

    # Ensure front-matter on artifacts Gemini may have produced.
    produced: list[str] = []
    for fname, act in [
        (PR_BODY_FILE, "pr-body"),
        (RELEASE_FILE, "release-note"),
        (CHECKLIST_FILE, "checklist"),
    ]:
        path = feature_dir / fname
        if path.is_file():
            _patch_frontmatter(path, feature, act)
            produced.append(str(path))

    return {
        "feature": feature,
        "action": action,
        "model": model,
        "exit_code": proc.returncode,
        "produced_files": produced,
        "stderr_tail": proc.stderr[-500:] if proc.stderr else "",
        "summary": (proc.stdout or "")[-800:],
    }
