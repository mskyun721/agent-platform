"""Planning wrapper — delegates PRD/TASK generation to Gemini or Codex CLI."""

from __future__ import annotations

from datetime import date
from typing import Any

from agent_platform_mcp.config import ROOT, docs_dir
from agent_platform_mcp.tools import runner
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


def _frontmatter(feature: str, action: str, tool: str) -> str:
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


def _expected_files(action: str) -> list[str]:
    if action == "all":
        return [PRD_FILE, TASK_FILE]
    return [PRD_FILE if action == "prd" else TASK_FILE]


def _run_plan(
    feature: str,
    requirements: str,
    action: str,
    cli: str,
    dry_run: bool,
    timeout_sec: int,
) -> dict[str, Any]:
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
    workdir = runner.workspace_root()
    cmd = runner.build_cmd(cli, prompt, workdir)

    if dry_run:
        return {
            "feature": feature,
            "action": action,
            "dry_run": True,
            "command": cmd,
            "prompt_preview": runner.preview(prompt),
        }

    proc = runner.run_cli(cli, cmd, workdir, timeout_sec)

    artifacts: list[str] = []
    for fname in _expected_files(action):
        fpath = feature_dir / fname
        if fpath.is_file():
            content = fpath.read_text(encoding="utf-8")
            if not content.lstrip().startswith("---"):
                fpath.write_text(
                    _frontmatter(feature, action, tool=cli) + content,
                    encoding="utf-8",
                )
            artifacts.append(str(fpath))

    return {
        "feature": feature,
        "action": action,
        "exit_code": proc.returncode,
        "artifacts": artifacts,
        "stderr_tail": runner.stderr_tail(proc),
        "summary": (proc.stdout or "")[-800:],
    }


def run(
    feature: str,
    requirements: str,
    action: str = "all",
    cli: str = "auto",
    dry_run: bool = False,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    """Generate PRD/TASK with the selected CLI. cli='auto' uses .agent-config.json."""
    return _run_plan(feature, requirements, action, runner.resolve_cli(cli), dry_run, timeout_sec)
