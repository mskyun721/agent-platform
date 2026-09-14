#!/usr/bin/env python3
"""Local baseline preparation and evaluator-owned checks; no AI is auto-launched."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EVALS = Path(__file__).resolve().parent
ROOT = EVALS.parent
FIXTURE = EVALS / "fixtures/sample-service"
TASKS = EVALS / "tasks"
RESULTS = EVALS / "results"


def _task(task: str) -> Path:
    if task not in {"small-feature", "seeded-bug", "broken-test", "api-add", "skill-remove"}:
        raise ValueError(f"unknown task: {task}")
    return TASKS / task


def _hash(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected regular evaluator file: {path.name}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inputs(task: str) -> dict[str, Path]:
    files = {p.relative_to(FIXTURE).as_posix(): p for p in FIXTURE.rglob("*.py") if "__pycache__" not in p.parts}
    overlay = _task(task) / "overlay"
    if overlay.is_dir():
        files.update({p.relative_to(overlay).as_posix(): p for p in overlay.rglob("*.py")})
    return files


def _spec_hash(task: str) -> str:
    files = _inputs(task)
    files.update({"instructions": _task(task) / "task.md", "criteria": _task(task) / "expect.json", "judge": EVALS / "judge.py",
                  "skill_judge": EVALS / "skill_judge.py", "http_judge": EVALS / "http_judge.py"})
    for name in ("openapi.yaml", "flow.mmd"):
        if (_task(task) / name).exists():
            files["contract:" + name] = _task(task) / name
    return hashlib.sha256(json.dumps({k: _hash(v) for k, v in files.items()}, sort_keys=True).encode()).hexdigest()


def _revision() -> str | None:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_file(run_id: str) -> Path:
    # Validate before constructing a path; IDs are independent of task names.
    if str(uuid.UUID(run_id)) != run_id:
        raise ValueError("invalid run id")
    return RESULTS / f"{run_id}.json"


def setup(task: str, workspace: Path, *, ai: str | None = None, model: str | None = None,
          cli_version: str | None = None, instructions: str = "task-only") -> dict[str, Any]:
    _task(task)
    if workspace.is_symlink():
        raise ValueError("workspace cannot be a symlink")
    workspace = workspace.resolve()
    if workspace.is_relative_to(ROOT) or RESULTS.resolve().is_relative_to(workspace):
        raise ValueError("evaluation workspace must be outside the platform and evaluator state")
    if workspace.exists() and any(workspace.iterdir()):
        raise FileExistsError(f"workspace not empty: {workspace}")
    workspace.mkdir(parents=True, exist_ok=True)
    for rel, source in _inputs(task).items():
        dest = workspace / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    run_id = str(uuid.uuid4())
    metadata = {"run_id": run_id, "task": task, "workspace": str(workspace),
                "started_at": _now(), "started_timestamp": time.time(), "task_hash": _spec_hash(task),
                "platform_revision": _revision(), "platform_dirty": _platform_dirty(),
                "platform_fingerprint": _platform_fingerprint(),
                "ai": ai, "model": model, "cli_version": cli_version,
                "instruction_mode": instructions, "python": sys.version,
                "status": "prepared", "usage": None, "usage_source": "unavailable"}
    RESULTS.mkdir(parents=True, exist_ok=True)
    _state_file(run_id).write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


def _platform_dirty() -> bool:
    proc = subprocess.run(["git", "diff", "--quiet", "HEAD"], cwd=ROOT, check=False)
    return proc.returncode != 0


def _platform_fingerprint() -> str:
    files = list((ROOT / "mcp-server/src/agent_platform_mcp").rglob("*.py"))
    files += [ROOT / "AGENTS.md", EVALS / "run_task.py", EVALS / "judge.py"]
    manifest = {p.relative_to(ROOT).as_posix(): _hash(p) for p in files}
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


def check(run_id: str, *, human_interventions: int = 0, note: str = "") -> dict[str, Any]:
    state_file = _state_file(run_id)
    metadata = json.loads(state_file.read_text())
    task = metadata["task"]
    workspace = Path(metadata["workspace"])
    if metadata["task_hash"] != _spec_hash(task):
        raise ValueError("evaluator inputs changed since setup; create a new baseline run")
    if human_interventions < 0:
        raise ValueError("human_interventions cannot be negative")
    expect = json.loads((_task(task) / "expect.json").read_text())
    failures: list[str] = []
    for rel in _inputs(task):
        path = workspace / rel
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != p.parent):
            failures.append(f"symlink not allowed: {rel}")
        if not path.is_file():
            failures.append(f"required file missing: {rel}")
    for rel in expect["unchanged"]:
        path = workspace / rel
        if not path.is_file() or path.is_symlink() or _hash(path) != _hash(_inputs(task)[rel]):
            failures.append(f"{rel} must be unchanged")
    started = time.monotonic()
    exit_code = None
    if not failures:
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(EVALS / "judge.py"), str(workspace), str(_task(task) / "expect.json")],
                cwd=EVALS, capture_output=True, text=True, timeout=expect["timeout_sec"], check=False,
            )
            exit_code = proc.returncode
            if exit_code:
                failures.append(f"evaluator behavior/test check exit {exit_code}")
        except (OSError, subprocess.TimeoutExpired) as exc:
            failures.append(f"evaluator execution error: {type(exc).__name__}")
    result = {**metadata, "status": "checked", "passed": not failures, "failures": failures,
              "checked_at": _now(), "verification_exit_code": exit_code,
              "check_duration_sec": round(time.monotonic() - started, 3),
              "session_wall_sec": round(time.time() - metadata["started_timestamp"], 3),
              "human_interventions": human_interventions, "note": note}
    state_file.write_text(json.dumps(result, indent=2) + "\n")
    return result


def record_skip(task: str, ai: str, reason: str) -> dict[str, Any]:
    _task(task)
    if not reason.strip():
        raise ValueError("skip reason required")
    result = {"run_id": str(uuid.uuid4()), "task": task, "ai": ai, "status": "not_run",
              "reason": reason, "recorded_at": _now(), "platform_revision": _revision(),
              "platform_fingerprint": _platform_fingerprint(), "platform_dirty": _platform_dirty(),
              "task_hash": _spec_hash(task), "usage": None}
    RESULTS.mkdir(parents=True, exist_ok=True)
    _state_file(result["run_id"]).write_text(json.dumps(result, indent=2) + "\n")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    auto = commands.add_parser("auto")
    auto.add_argument("--task", required=True)
    auto.add_argument("--ai", choices=["claude", "codex"], required=True)
    auto.add_argument("--repeat", type=int, default=3)
    auto.add_argument("--max-minutes", type=float, default=10)
    auto.add_argument("--instructions", choices=["platform", "task-only"], default="platform")
    auto.add_argument("--model")
    start = commands.add_parser("setup")
    start.add_argument("--task", required=True)
    start.add_argument("--workspace", type=Path, required=True)
    start.add_argument("--ai", choices=["claude", "codex"])
    start.add_argument("--model")
    start.add_argument("--cli-version")
    start.add_argument("--instructions", default="task-only")
    verify = commands.add_parser("check")
    verify.add_argument("--run-id", required=True)
    verify.add_argument("--human-interventions", type=int, default=0)
    verify.add_argument("--note", default="")
    skip = commands.add_parser("record-skip")
    skip.add_argument("--task", required=True)
    skip.add_argument("--ai", choices=["claude", "codex"], required=True)
    skip.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "auto":
            from auto import run
            result = run(args.task, args.ai, args.repeat, args.max_minutes, args.instructions, args.model)
        elif args.command == "setup":
            result = setup(args.task, args.workspace, ai=args.ai, model=args.model,
                           cli_version=args.cli_version, instructions=args.instructions)
        elif args.command == "check":
            result = check(args.run_id, human_interventions=args.human_interventions, note=args.note)
        else:
            result = record_skip(args.task, args.ai, args.reason)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"eval: {exc}\n")
    print(json.dumps(result, indent=2))
    return 0 if result.get("passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
