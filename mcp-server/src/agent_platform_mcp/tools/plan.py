"""Planning wrapper — delegates PRD/TASK generation to Gemini or Codex CLI."""

from __future__ import annotations

import shutil
import subprocess
from datetime import date
from typing import Any

from agent_platform_mcp.config import ROOT, docs_dir, preferred_cli, target_project_root
from agent_platform_mcp.tools.feature import _ensure_safe_name  # noqa: PLC2701

VALID_ACTION = {"prd", "task", "all"}
PRD_FILE = "PRD.md"
TASK_FILE = "TASK.md"
DEFAULT_TIMEOUT_SEC = 600


def _build_prompt(feature: str, action: str, requirements: str) -> str:
    feature_dir = docs_dir(feature)
    action_desc = {
        "prd": "PRD.md 문서만 작성한다.",
        "task": "TASK.md 문서만 작성한다. (PRD.md가 이미 존재해야 함)",
        "all": "PRD.md 와 TASK.md 두 문서를 모두 작성한다.",
    }[action]

    return (
        f"백엔드 서버 기능 '{feature}'에 대한 기획 산출물을 작성해줘.\n\n"
        f"작업 범위: {action_desc}\n\n"
        f"사용자 요구사항:\n{requirements}\n\n"
        f"참조 파일 (존재하는 것만):\n"
        f"- PRD 템플릿: {ROOT / 'templates/PRD.md'}\n"
        f"- TASK 템플릿: {ROOT / 'templates/TASK.md'}\n"
        f"- API 계약 표준: {ROOT / 'standards/api-contract.md'}\n"
        f"- 보안 기준: {ROOT / 'standards/security-baseline.md'}\n"
        f"- 기존 PRD 예시: docs/*/*/PRD.md (패턴 참고)\n\n"
        f"산출물 저장 경로:\n"
        f"- PRD: {feature_dir}/PRD.md\n"
        f"- TASK: {feature_dir}/TASK.md\n\n"
        f"PRD 필수 섹션 (templates/PRD.md 구조 그대로 사용):\n"
        f"- Front-matter (agent, feature, status: draft, created, updated)\n"
        f"- API 요약 (메서드/경로/권한/멱등성)\n"
        f"- 도메인 모델 변경 + 마이그레이션\n"
        f"- Business Rules (BR-n 번호 부여)\n"
        f"- 에러 케이스 (code, HTTP, 메시지)\n"
        f"- Acceptance Criteria (AC-n, 검증 방법 명시)\n\n"
        f"TASK 필수 사항:\n"
        f"- Hexagonal 순서 준수: Domain → Application → Adapter\n"
        f"- 각 Phase는 독립 빌드·테스트 가능 단위\n\n"
        f"지침:\n"
        f"- 불명확한 요구사항은 Assumption 섹션에 명시 (추측 금지)\n"
        f"- 실제 존재 파일만 참조, 없는 파일 가정 금지\n"
        f"- UI/UX 여정 기술 금지 (백엔드 범위만)\n"
        f"- 모든 AC는 자동 검증 가능한 형태 (Integration/Load Test 등)\n\n"
        f"완료 후 stdout에 생성 파일 경로와 주요 Assumption 목록을 출력."
    )


def _frontmatter(feature: str, action: str, tool: str = "gemini") -> str:
    today = date.today().isoformat()
    return (
        "---\n"
        "agent: planner\n"
        f"feature: {feature}\n"
        "status: draft\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        f"action: {action}\n"
        f"tool: {tool}\n"
        "---\n\n"
    )


def run_gemini(
    feature: str,
    requirements: str,
    action: str = "all",
    dry_run: bool = False,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    """Run Gemini CLI to generate PRD and/or TASK for a feature.

    Args:
        feature: name under docs/<type>/ (e.g. "fix/login-bug" or a bare
            name for docs/features/<name>)
        requirements: raw user requirements text
        action: one of {prd, task, all}
        dry_run: returns the prompt and command without invoking Gemini
        timeout_sec: hard subprocess timeout
    """
    _ensure_safe_name(feature)
    if action not in VALID_ACTION:
        raise ValueError(f"action must be one of {sorted(VALID_ACTION)}")
    if not requirements or not requirements.strip():
        raise ValueError("requirements must be non-empty")

    feature_dir = docs_dir(feature)
    if not feature_dir.is_dir():
        raise FileNotFoundError(
            f"Feature directory not found: {feature_dir}. "
            "Run feature_scaffold first."
        )

    prompt = _build_prompt(feature, action, requirements.strip())
    workdir = target_project_root() or ROOT
    cmd = ["gemini", "--approval-mode", "plan", "-p", prompt]

    if dry_run:
        return {
            "feature": feature,
            "action": action,
            "dry_run": True,
            "command": cmd,
            "prompt_preview": prompt[:300] + ("…" if len(prompt) > 300 else ""),
        }

    if shutil.which("gemini") is None:
        raise RuntimeError("gemini CLI not found on PATH")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=str(workdir),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"gemini timed out after {timeout_sec}s") from exc

    artifacts: list[str] = []
    for fname in ([PRD_FILE, TASK_FILE] if action == "all" else [PRD_FILE if action == "prd" else TASK_FILE]):
        fpath = feature_dir / fname
        if fpath.is_file():
            content = fpath.read_text(encoding="utf-8")
            if not content.lstrip().startswith("---"):
                fpath.write_text(_frontmatter(feature, action, tool="gemini") + content, encoding="utf-8")
            artifacts.append(str(fpath))

    return {
        "feature": feature,
        "action": action,
        "exit_code": proc.returncode,
        "artifacts": artifacts,
        "stderr_tail": proc.stderr[-500:] if proc.stderr else "",
        "summary": (proc.stdout or "")[-800:],
    }


def run_codex(
    feature: str,
    requirements: str,
    action: str = "all",
    dry_run: bool = False,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    """Run Codex CLI to generate PRD and/or TASK for a feature."""
    _ensure_safe_name(feature)
    if action not in VALID_ACTION:
        raise ValueError(f"action must be one of {sorted(VALID_ACTION)}")
    if not requirements or not requirements.strip():
        raise ValueError("requirements must be non-empty")

    feature_dir = docs_dir(feature)
    if not feature_dir.is_dir():
        raise FileNotFoundError(
            f"Feature directory not found: {feature_dir}. "
            "Run feature_scaffold first."
        )

    prompt = _build_prompt(feature, action, requirements.strip())
    workdir = target_project_root() or ROOT
    cmd = [
        "codex",
        "exec",
        "--cd",
        str(workdir),
        "--skip-git-repo-check",
        "--full-auto",
        prompt,
    ]

    if dry_run:
        return {
            "feature": feature,
            "action": action,
            "dry_run": True,
            "command": cmd,
            "prompt_preview": prompt[:300] + ("..." if len(prompt) > 300 else ""),
        }

    if shutil.which("codex") is None:
        raise RuntimeError("codex CLI not found on PATH")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=str(workdir),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"codex exec timed out after {timeout_sec}s") from exc

    artifacts: list[str] = []
    for fname in ([PRD_FILE, TASK_FILE] if action == "all" else [PRD_FILE if action == "prd" else TASK_FILE]):
        fpath = feature_dir / fname
        if fpath.is_file():
            content = fpath.read_text(encoding="utf-8")
            if not content.lstrip().startswith("---"):
                fpath.write_text(_frontmatter(feature, action, tool="codex") + content, encoding="utf-8")
            artifacts.append(str(fpath))

    return {
        "feature": feature,
        "action": action,
        "exit_code": proc.returncode,
        "artifacts": artifacts,
        "stderr_tail": proc.stderr[-500:] if proc.stderr else "",
        "summary": (proc.stdout or "")[-800:],
    }
