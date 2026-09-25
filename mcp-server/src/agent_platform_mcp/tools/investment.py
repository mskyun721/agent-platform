"""Investment research reports; no trading or product-code execution contract."""

from datetime import date
from pathlib import Path
from typing import Any

from agent_platform_mcp.config import ROOT
from agent_platform_mcp.tools import observation, runner, stdout_artifacts

REPORT_FILE = "INVESTMENT-REPORT.md"
REPORT_FILES = {"investment": REPORT_FILE, "quant": "QUANT-REPORT.md",
                "investment-risk": "INVESTMENT-RISK.md"}


def _run(role: str, feature: str, requirements: str, as_of: str, cli: str, dry_run: bool,
         timeout_sec: int, context: runner.ProjectContext, model: str | None = None) -> dict[str, Any]:
    report_file = REPORT_FILES[role]
    directory = runner.feature_directory(feature, context)
    local_context, sources = runner.context_block(feature, context.path)
    prompt = runner.role_prompt(role, task=(
        f"투자 리서치 '{feature}'를 수행한다. 기준일 as_of: {as_of}.\n"
        f"사용자 요구사항:\n{requirements}\n\n"
        f"보고서 템플릿: {ROOT / 'templates' / report_file}\n"
        f"검토 기준: {ROOT / 'standards/reference/investment-development.md'}\n"
        f"# {stdout_artifacts.TITLES[role]}: {feature}\n"
        + "\n".join(stdout_artifacts.SECTIONS[role])
        + "\n위 제목과 섹션을 유지한 Markdown 본문만 stdout으로 출력한다.\n"
        "파일·제품 코드·계좌를 변경하지 않는다. 자료가 부족하면 INSUFFICIENT로 보고한다.\n"
        "기준일의 시장·시간대·장 마감 시각이 불명확하면 명시하고 확정 판단을 보류한다."
    ), context=(f"TARGET_PROJECT: {context.path}\nArtifact directory: {directory}\n"
                f"Output transport: stdout Markdown only; wrapper writes {report_file}.\n\n{local_context}"))
    command = runner.build_cmd(cli, prompt, context.path, model=model, read_only=True)
    # Research only: the parent persists the validated report, not the child CLI.
    if dry_run:
        return {"feature": feature, "as_of": as_of, "dry_run": True, "command": command,
                "prompt_preview": runner.preview(prompt),
                "prompt_sources": runner.prompt_sources(role) + sources,
                "output_path": str(directory / report_file)}
    proc = runner.run_cli(cli, command, context.path, timeout_sec)
    runner.feature_directory(feature, context)
    body, metadata = stdout_artifacts.prepare(proc.stdout, role=role, feature=feature,
                                               exit_code=proc.returncode)
    today = date.today().isoformat()
    prefix = (f"---\nagent: {role}\nfeature: {feature}\nstatus: draft\n"
              f"created: {today}\nupdated: {today}\nas_of: {as_of}\nai_backend: {cli}\n---\n\n")
    output = directory / report_file
    output.write_text(stdout_artifacts.metadata_prefix(prefix, metadata) + body, encoding="utf-8")
    return {"feature": feature, "as_of": as_of, "exit_code": proc.returncode,
            "output_path": str(output), **metadata, "stderr_tail": "",
            "summary": runner.preview(body, 400)}


def run_report(role: str, feature: str, requirements: str, as_of: str, cli: str = "auto", dry_run: bool = False,
        timeout_sec: int = 600, root: str | Path | None = None, model: str | None = None) -> dict[str, Any]:
    """Write a draft investment report for an explicit YYYY-MM-DD research cutoff."""
    if role not in REPORT_FILES:
        raise ValueError("unknown research role")
    if not requirements or not requirements.strip():
        raise ValueError("requirements must be non-empty")
    if not isinstance(as_of, str) or date.fromisoformat(as_of).isoformat() != as_of:
        raise ValueError("as_of must be YYYY-MM-DD")
    if timeout_sec <= 0:
        raise ValueError("timeout_sec must be positive")
    context = runner.resolve_project(root)
    return runner.execute(context, feature, role, cli, model, dry_run,
        lambda chosen, selected: _run(role, feature, requirements.strip(), as_of, chosen, dry_run, timeout_sec, context, selected))


def run(feature: str, requirements: str, as_of: str, cli: str = "auto", dry_run: bool = False,
        timeout_sec: int = 600, root: str | Path | None = None, model: str | None = None) -> dict[str, Any]:
    """Draft investment research using the common report runner."""
    return run_report("investment", feature, requirements, as_of, cli, dry_run, timeout_sec, root, model)
