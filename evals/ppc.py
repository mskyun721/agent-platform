#!/usr/bin/env python3
"""Propose–Probe–Compose for one role instruction on one host against evaluator fixtures.

Billable: R = 4k fixture rollouts plus 3k + 1 read-only model sessions. Outputs go to
.local/ppc/<run-id>/. A non-base selection becomes an improvement *draft* only; review, matched
evaluation and apply remain the existing explicit workflow.
"""
import argparse
import hashlib
import json
import tempfile
import time
import uuid
from pathlib import Path

import auto
import run_task
from agent_platform_mcp import backends
from agent_platform_mcp.learning import ppc

OUT = run_task.ROOT / ".local/ppc"
PROMPT = ("Isolated evaluator task. TARGET_PROJECT is {workspace}; ignore active-project pointers. "
          "Do not delegate, invoke another AI, read credentials, change the platform, or push/deploy. "
          "No documentation is required for this fixture.\n\n")


def _snapshot(workspace):
    return {p.relative_to(workspace).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in workspace.rglob("*") if p.is_file() and not p.is_symlink()
            and not {"__pycache__", ".pytest_cache"} & set(p.parts)}


class Runner:
    def __init__(self, host, model, tasks, max_minutes):
        self.host, self.model, self.tasks = host, model, list(tasks)
        self.adapter = backends.get(host)
        if not backends.installed(host):
            raise ValueError(f"{host} CLI is not installed")
        for task in self.tasks:
            run_task._task(task)
        if not 0 < max_minutes <= 240:
            raise ValueError("max_minutes must be within 0..240")
        self.deadline = time.monotonic() + max_minutes * 60
        self.version = backends.version(host) if backends.installed(host) else None

    def remaining(self):
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise ppc.BudgetError("time budget exhausted")
        return left

    def session(self, prompt):
        with tempfile.TemporaryDirectory(prefix="ppc-session-") as temp:
            workspace = Path(temp).resolve()
            execution = auto.execute(self.adapter.command(prompt, workspace, model=self.model, read_only=True),
                                     workspace, self.remaining())
        if execution["reason"] in ("budget", "interrupted"):
            raise ppc.BudgetError(f"session {execution['reason']}")
        text, _, failed = self.adapter.parse(execution["stdout"])
        if execution["exit_code"] != 0 or failed:
            raise RuntimeError(f"session failed: {execution['reason'] or 'unparseable output'}")
        return text

    def rollout(self, instruction, label):
        tasks = []
        for task in self.tasks:
            with tempfile.TemporaryDirectory(prefix=f"ppc-{task}-") as temp:
                workspace = Path(temp).resolve()
                state = run_task.setup(task, workspace, ai=self.host, model=self.model, cli_version=self.version,
                                       instructions="ppc")
                policy = (run_task.ROOT / "AGENTS.md").read_text() + "\n\n" + instruction
                (workspace / "AGENTS.md").write_text(policy + "\n\nFixture scope: use this workspace only.\n")
                for name in ("CLAUDE.md", "GEMINI.md"):
                    (workspace / name).write_text("@AGENTS.md\n")
                prompt = PROMPT.format(workspace=workspace) + (run_task._task(task) / "task.md").read_text()
                before = _snapshot(workspace)
                execution = auto.execute(self.adapter.command(prompt, workspace, model=self.model, read_only=False),
                                         workspace, self.remaining())
                after = _snapshot(workspace)
                checked = run_task.check(state["run_id"])
                _, usage, _ = self.adapter.parse(execution["stdout"])
                tasks.append({"task": task, "passed": checked["passed"] and execution["exit_code"] == 0,
                              "failure_reason": execution["reason"] or (None if checked["passed"] else "evaluator"),
                              "evaluator_stage": checked.get("evaluator_stage"),
                              "changed_files": sorted(name for name in before.keys() | after.keys()
                                                      if before.get(name) != after.get(name)
                                                      and name not in ("AGENTS.md", "CLAUDE.md", "GEMINI.md")),
                              "exit_code": execution["exit_code"], "duration_sec": execution["duration_sec"],
                              "usage_completeness": usage.completeness})
                if execution["reason"] in ("budget", "interrupted"):
                    raise ppc.BudgetError(f"rollout {label} {execution['reason']}")
        return {"tasks": tasks}


def _lessons(project, role):
    if not project:
        return ""
    from agent_platform_mcp.learning import experience
    path = experience.library(experience._project(project), role) / "INDEX.md"
    return path.read_text(encoding="utf-8") if path.is_file() and not path.is_symlink() else ""


def _register(run_id, args, result):
    from agent_platform_mcp.learning import feedback, improvements
    from agent_platform_mcp.tools.stdout_artifacts import _mask
    root = str(run_task.ROOT)
    why = _mask(result["selection"]["why"] or "PPC composition selected")
    record = feedback.add(root, "manual", None, "suggestion",
                          f"PPC run {run_id} ({args.host}, k={args.k}, tasks={args.tasks}) selected a refined "
                          f"{args.role} instruction: {why}"[:2000])
    item = improvements.propose(root, record["id"], trigger=f"PPC run {run_id}", action=why[:2000],
                                target=f"standards/agents/{args.role}.md", replacement=result["text"])
    return {"feedback_id": record["id"], "candidate_id": item["id"]}


def _write(directory, name, value):
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=backends.NAMES, required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--k", type=int, default=1)
    parser.add_argument("--tasks", required=True, help="comma-separated evaluator tasks, e.g. seeded-bug,small-feature")
    parser.add_argument("--max-minutes", type=float, required=True)
    parser.add_argument("--project", help="project root or id whose docs/experience/<role>/INDEX.md supplies lessons")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--no-improvement", action="store_true", help="do not register a non-base selection")
    args = parser.parse_args(argv)
    from agent_platform_mcp import config
    if args.role not in config.VALID_AGENTS:
        parser.error(f"unknown role: {args.role}")
    run_id = str(uuid.uuid4())
    out = OUT / run_id
    out.mkdir(parents=True)
    base = (run_task.ROOT / "standards/agents" / f"{args.role}.md").read_text(encoding="utf-8")
    summary = {"run_id": run_id, "host": args.host, "role": args.role, "model": args.model, "k": args.k,
               "tasks": args.tasks.split(","), "seed": args.seed}
    try:
        runner = Runner(args.host, args.model, summary["tasks"], args.max_minutes)
        result = ppc.run(role=args.role, k=args.k, base=base, lessons=_lessons(args.project, args.role),
                         session=runner.session, rollout=runner.rollout, seed=args.seed)
    except (ppc.BudgetError, RuntimeError, ValueError) as exc:
        _write(out, "ledger.json", getattr(exc, "ledger", {}))
        for group, values in getattr(exc, "partial", {}).items():
            for label, value in values.items():
                _write(out, f"{group}/{label}.{'json' if group == 'rollouts' else 'md'}", value)
        status = "budget_exhausted" if isinstance(exc, ppc.BudgetError) else "failed"
        _write(out, "result.json", {**summary, "status": status, "error": str(exc)[:500]})
        print(json.dumps({**summary, "status": status, "output": str(out)}))
        return 1
    _write(out, "ledger.json", result["ledger"])
    for group in ("candidates", "finals"):
        for label, text in result[group].items():
            _write(out, f"{group}/{label}.md", text)
    for label, record in result["rollouts"].items():
        _write(out, f"rollouts/{label}.json", record)
    status, registered = "completed", None
    if result["stages"] and all(stage.get("fell_back") for stage in result["stages"]):
        status = "no_valid_proposals"
    elif result["changed"] and not args.no_improvement:
        try:
            registered = _register(run_id, args, result)
        except (ValueError, RuntimeError, OSError) as exc:
            status, registered = "registration_failed", {"error": str(exc)[:500]}
    final = {**summary, "status": status, "stages": result["stages"], "selection": result["selection"],
             "changed": result["changed"], "improvement": registered}
    _write(out, "result.json", final)
    print(json.dumps({**final, "output": str(out)}, ensure_ascii=False))
    return 0 if status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
