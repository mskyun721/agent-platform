"""Bounded, explicitly requested fixture runs. No external service workspaces."""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

import run_task

sys.path.insert(0, str(run_task.ROOT / "mcp-server/src"))
from agent_platform_mcp.tools import monitored_process, native_output, observation, projects, store


def execute(argv: list[str], workspace: Path, timeout: float) -> dict:
    started = time.monotonic()
    try:
        proc = monitored_process.run(argv, cwd=workspace, timeout=timeout, pulse=observation.process_heartbeat)
        return {"exit_code": proc.returncode, "reason": None if proc.returncode == 0 else "cli_failed",
                "stdout": proc.stdout, "duration_sec": round(time.monotonic() - started, 3)}
    except subprocess.TimeoutExpired:
        reason = "budget"
    except (monitored_process.ProcessInterrupted, KeyboardInterrupt):
        reason = "interrupted"
    except OSError:
        return {"exit_code": None, "reason": "cli_unavailable", "stdout": "", "duration_sec": 0}
    return {"exit_code": None, "reason": reason, "stdout": "", "duration_sec": round(time.monotonic() - started, 3)}


def usage(backend: str, stdout: str) -> dict | None:
    if backend == "codex":
        return asdict(native_output.codex(stdout)[1])
    try:
        result = json.loads(stdout)
        native = result["usage"]
        from agent_platform_mcp.events import Usage, validate_usage
        values = [native.get(key) for key in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")]
        projected = Usage(*values, "claude-json", "full" if all(v is not None for v in values) else "partial")
        return asdict(projected) if not validate_usage(projected) else None
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def run(task: str, backend: str, repeat: int, max_minutes: float, instructions: str = "platform",
        model: str | None = None) -> dict:
    run_task._task(task)
    if backend not in {"claude", "codex"} or type(repeat) is not int or not 1 <= repeat <= 10:
        raise ValueError("backend must be claude/codex and repeat 1-10")
    if not 0 < max_minutes <= 60 or instructions not in {"platform", "task-only"}:
        raise ValueError("budget must be 0-60 minutes and instructions platform/task-only")
    try:
        version_result = subprocess.run([backend, "--version"], capture_output=True, text=True, timeout=10, check=False)
        import re
        matched = re.search(r"\b\d+\.\d+\.\d+\b", version_result.stdout)
        version = matched[0] if matched else None
    except (OSError, subprocess.TimeoutExpired):
        version = None
    deadline = time.monotonic() + max_minutes * 60
    records = []
    task_text = (run_task._task(task) / "task.md").read_text()
    for _ in range(repeat):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        with tempfile.TemporaryDirectory(prefix=f"platform-eval-{task}-") as temp:
            workspace = Path(temp).resolve()
            state = run_task.setup(task, workspace, ai=backend, model=model, cli_version=version, instructions=instructions)
            prompt = (f"Isolated evaluator task. TARGET_PROJECT is {workspace}; ignore active-project pointers. "
                      "Do not delegate, invoke another AI, read credentials, change the platform, or push/deploy. "
                      f"Use {sys.executable} -m pytest -q for tests. No documentation is required for this fixture.\n\n" + task_text)
            if instructions == "platform":
                policy = (run_task.ROOT / "AGENTS.md").read_text() + "\n" + (run_task.ROOT / "standards/agents/backend.md").read_text()
                # The explicit task scope remains the fixture, even when the imported policy mentions active-project.
                (workspace / "AGENTS.md").write_text(policy + "\n\nFixture scope: use this workspace only. Do not start platform observation from this fixture.\n")
                (workspace / "CLAUDE.md").write_text("@AGENTS.md\n")
            argv = (["codex", "exec", "--sandbox", "workspace-write", "--skip-git-repo-check", "--json"]
                    if backend == "codex" else ["claude", "-p", prompt, "--output-format", "json", "--strict-mcp-config",
                                               "--no-session-persistence", "--tools", "Read,Edit,Write,Bash",
                                               "--allowedTools", "Read", "Edit", "Write", f"Bash({sys.executable} -m pytest -q)"])
            if model:
                argv += ["--model", model]
            observed = observation.start_context(task, "backend", backend, projects.ProjectContext(None, workspace), model, "wrapper")
            token = observation._current.set(observed)
            try:
                execution = execute([*argv, prompt] if backend == "codex" else argv, workspace, remaining)
            finally:
                observation._current.reset(token)
            checked = run_task.check(state["run_id"], human_interventions=0)
            checked.update(passed=checked["passed"] and execution["exit_code"] == 0,
                           ai_exit_code=execution["exit_code"], ai_duration_sec=execution["duration_sec"],
                           failure_reason=execution["reason"] or (None if checked["passed"] else "evaluator"),
                           outcome="interrupted" if execution["reason"] in {"budget", "interrupted"} else "completed" if checked["passed"] and execution["exit_code"] == 0 else "failed",
                           usage=usage(backend, execution["stdout"]), judge_version=4, adapter_version=1,
                           skill_versions=None, skill_versions_source="unavailable", raw_output_retained=False,
                           workspace_removed=True)
            checked["observation_run_id"] = observed["run_id"]
            checked["observability"] = observed["observability"]
            if observed["observability"]["stored"]:
                try:
                    if checked["usage"]:
                        from agent_platform_mcp.events import Usage
                        with store.open() as db:
                            db.record_usage(observed["run_id"], Usage(**checked["usage"]))
                    ended = observation.run_end(observed["run_id"], checked["outcome"], duration_sec=execution["duration_sec"])
                    checked["observability"] = ended["observability"]
                except Exception as exc:
                    checked["observability"] = {"stored": False, "error": type(exc).__name__}
            run_task._state_file(state["run_id"]).write_text(json.dumps(checked, indent=2) + "\n")
            records.append({key: checked[key] for key in ("run_id", "task", "ai", "passed", "failure_reason", "ai_duration_sec")})
            print(json.dumps(records[-1]), flush=True)
            if execution["reason"] == "interrupted":
                break
    return {"runs": records, "requested": repeat, "completed": len(records),
            "sample_insufficient": len(records) < 3, "passed": len(records) == repeat and all(row["passed"] for row in records)}
