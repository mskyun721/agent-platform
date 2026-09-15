"""Explicit verification profiles and advisory policy reports."""

from __future__ import annotations

import hashlib
import json
import math
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from agent_platform_mcp.config import ROOT

VERIFIER_FILES = (
    "mcp-server/src/agent_platform_mcp/config.py",
    "mcp-server/src/agent_platform_mcp/events.py",
    "mcp-server/src/agent_platform_mcp/frontmatter.py",
    "mcp-server/src/agent_platform_mcp/tools/feature.py",
    "mcp-server/src/agent_platform_mcp/tools/handoff.py",
    "mcp-server/src/agent_platform_mcp/tools/verification.py",
    "mcp-server/src/agent_platform_mcp/tools/fingerprint.py",
    "mcp-server/src/agent_platform_mcp/tools/evidence.py",
    "mcp-server/src/agent_platform_mcp/tools/store.py",
    "mcp-server/src/agent_platform_mcp/tools/projects.py",
    "mcp-server/src/agent_platform_mcp/tools/observation.py",
    "mcp-server/src/agent_platform_mcp/tools/monitored_process.py",
)
SUGGESTIONS = (("gradlew", "gradle"), ("mvnw", "maven"), ("pyproject.toml", "pytest"))


def profile_hash(profile: dict[str, Any]) -> str:
    body = {key: value for key, value in profile.items() if not key.startswith("reviewed_")}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def verifier_hash(root: Path) -> str:
    from agent_platform_mcp.tools.projects import _safe_storage
    manifest = {}
    for relative in VERIFIER_FILES:
        path = root / relative
        _safe_storage(path)
        manifest[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


def _policy(profile: dict[str, Any], project: Path) -> tuple[str, dict[str, Any]]:
    current = profile_hash(profile)
    reviewed = profile.get("reviewed_hash")
    dirty: list[str] = []
    errors: list[str] = []
    # Inspect the code actually loaded by the server as well as a self-target
    # worktree. An external product repo is never treated as the verifier.
    roots = [ROOT.resolve()]
    if project != ROOT.resolve() and all((project / rel).is_file() for rel in VERIFIER_FILES):
        roots.append(project)
    for root in roots:
        try:
            proc = subprocess.run(
                ["git", "status", "--porcelain", "--", *VERIFIER_FILES],
                cwd=root, capture_output=True, text=True, timeout=10, check=False,
            )
            if proc.returncode:
                errors.append(f"cannot inspect verifier at {root}")
            else:
                dirty.extend(f"{root}/{line[3:]}" for line in proc.stdout.splitlines() if line)
        except (OSError, subprocess.TimeoutExpired):
            errors.append(f"cannot inspect verifier at {root}")
    code_changed = bool(dirty)
    if profile.get("reviewed_verifier_hash"):
        try:
            code_changed = any(verifier_hash(root) != profile["reviewed_verifier_hash"] for root in roots)
        except (OSError, ValueError):
            errors.append("cannot fingerprint verifier source")
    status = "changed" if code_changed or (reviewed and reviewed != current) else (
        "unchanged" if reviewed == current and not errors else "unreviewed"
    )
    return status, {
        "profile_hash": current, "reviewed_hash": reviewed,
        "reviewed_rev": profile.get("reviewed_rev"), "reviewed_by": profile.get("reviewed_by"),
        "approval_provenance": "complete" if all(profile.get(key) for key in
            ("reviewed_rev", "reviewed_by", "reviewed_at", "reviewed_verifier_hash")) else "legacy_or_missing",
        "verifier_code_dirty": dirty, "inspection_errors": errors,
        "loaded_platform_root": str(ROOT), "project_dir": str(project),
        "enforcement": "advisory; commit is not approval",
    }


def _run(
    result: dict[str, Any], project: Path, profile_id: str | None,
    config: dict[str, Any], legacy: str | None, timeout_budget: float | None = None,
) -> None:
    info: dict[str, Any] = {"profile_id": profile_id}
    result["verification"] = info
    try:
        profiles = config.get("verify_profiles", {})
        if not isinstance(profiles, dict):
            raise ValueError("verify_profiles must be an object")
        if profile_id is not None:
            profile = profiles.get(profile_id)
            if not isinstance(profile, dict):
                raise ValueError(f"unknown or invalid verify profile: {profile_id}")
            argv = profile.get("argv")
            if (not isinstance(argv, list) or not argv
                    or any(not isinstance(arg, str) or not arg or "\0" in arg for arg in argv)):
                raise ValueError("profile argv must be a non-empty array of non-empty strings")
            if "command" in profile:
                raise ValueError("explicit profiles cannot contain shell commands")
            command: list[str] | str = argv
            info.update(source="explicit", mode="argv", argv=argv)
        elif legacy:
            profile = {"command": legacy}
            command = legacy
            info.update(source="legacy-shell", mode="shell-compat", command=legacy)
        else:
            result.update(verification_status="not_run", passed=False)
            result["verify_skipped"] = "no verify profile selected"
            info.update(source="none", reason=result["verify_skipped"], suggested_profiles=[
                pid for marker, pid in SUGGESTIONS if (project / marker).is_file() and pid in profiles
            ])
            return

        relative = profile.get("cwd", ".")
        if not isinstance(relative, str) or Path(relative).is_absolute():
            raise ValueError("profile cwd must be relative to the project")
        cwd = (project / relative).resolve()
        if not cwd.is_relative_to(project) or not cwd.is_dir():
            raise ValueError("profile cwd must be an existing directory inside the project")
        timeout = profile.get("timeout_sec", 900)
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or timeout <= 0):
            raise ValueError("profile timeout_sec must be a finite positive number")
        result["policy_status"], result["policy"] = _policy(profile, project)
        info.update(cwd=str(cwd), timeout_sec=timeout, scope=profile.get("scope"))
        result["verify_command"] = shlex.join(command) if isinstance(command, list) else command
    except (ValueError, TypeError) as exc:
        result.update(verification_status="error", passed=False)
        info.update(error=str(exc), exit_code=None)
        return

    started = time.monotonic()
    effective_timeout = min(timeout, timeout_budget) if timeout_budget is not None else timeout
    try:
        from agent_platform_mcp.tools import monitored_process, observation
        proc = monitored_process.run(command, shell=info["mode"] == "shell-compat", cwd=cwd,
                                     timeout=effective_timeout,
                                     pulse=observation.process_heartbeat)
    except subprocess.TimeoutExpired:
        status = "error"
        info.update(error=f"timeout after {effective_timeout}s", exit_code=None, timed_out=True)
    except (OSError, UnicodeError) as exc:
        status = "error"
        info.update(error=f"verification execution error: {exc}", exit_code=None)
    else:
        status = "passed" if proc.returncode == 0 else "failed"
        info["exit_code"] = proc.returncode
        # Output is deliberately not returned: build output may contain secrets.
    info["duration_sec"] = round(time.monotonic() - started, 3)
    info["output_tail"] = ""
    info["output_omitted"] = True
    result["verification_status"] = status
    result["verify_exit_code"] = info["exit_code"]
    result["verify_output_tail"] = ""
    if status != "passed":
        result["passed"] = False


def _attempt(result: dict[str, Any], project: Path, profile_id: str | None,
        config: dict[str, Any], legacy: str | None, *, collect_evidence: bool = False,
        ac_ids: list[str] | None = None, timeout_budget: float | None = None) -> None:
    from agent_platform_mcp.tools import observation, projects, evidence, fingerprint
    from agent_platform_mcp.config import docs_dir

    before = None
    criteria = []
    if collect_evidence:
        try:
            before = fingerprint.code_fingerprint(project)
            criteria = evidence.acceptance_criteria(docs_dir(result["feature"], project_dir=project))
        except Exception as exc:
            result["evidence_error"] = type(exc).__name__
    context = projects.ProjectContext(result.get("project_id"), project)
    started = observation.start_context(result.get("feature", "verification"), "qa", None, context)
    token = observation._current.set(started)
    try:
        _run(result, project, profile_id, config, legacy, timeout_budget)
    except BaseException as exc:
        if not isinstance(exc, KeyboardInterrupt) and not getattr(exc, "interrupted", False):
            raise
        result.update(passed=False, verification_status="error", verification={"interrupted": True, "exit_code": None})
    finally:
        observation._current.reset(token)
    details = result.get("verification", {})
    recorded = observation.point(result, projects.ProjectContext(result.get("project_id"), project), "qa", "verification",
        {"profile_id": profile_id, "status": result.get("verification_status"),
         "exit_code": details.get("exit_code"), "duration_sec": details.get("duration_sec")}, started=started)
    result["verification_run_id"] = recorded["run_id"]
    result["observability"] = recorded["observability"]
    if collect_evidence:
        try:
            if before is None or not recorded["observability"]["stored"]:
                raise RuntimeError("verification evidence unavailable")
            profile = config.get("verify_profiles", {}).get(profile_id, {})
            scope = profile.get("scope", {})
            selected = ac_ids if ac_ids is not None else scope.get("acs", []) if isinstance(scope, dict) else []
            after = fingerprint.code_fingerprint(project)
            evidence.record(result, project, before, after, criteria, selected)
        except Exception as exc:
            result["evidence_error"] = type(exc).__name__
            result["evidence_status"] = "evidence_unavailable"


def run(result: dict[str, Any], project: Path, profile_id: str | None,
        config: dict[str, Any], legacy: str | None, *, collect_evidence: bool = False,
        ac_ids: list[str] | None = None, retry: dict | None = None) -> None:
    from agent_platform_mcp.tools import recovery
    budget = retry if retry is not None else config.get("retry", {}).get("verification", {})
    if not isinstance(budget, dict) or set(budget) - {"max_attempts", "max_minutes"}:
        raise ValueError("invalid verification retry budget")
    attempts = budget.get("max_attempts", 1)
    minutes = budget.get("max_minutes", 15)
    if type(attempts) is not int or not 1 <= attempts <= 5 or type(minutes) not in (int, float) or not math.isfinite(minutes) or not 0 < minutes <= 60:
        raise ValueError("retry allows 1-5 attempts and 0-60 finite minutes")
    deadline = time.monotonic() + minutes * 60
    original_passed = result.get("passed", False)
    history = []
    for attempt in range(1, attempts + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        result["passed"] = original_passed
        for field in ("evidence_error", "evidence_status"):
            result.pop(field, None)
        _attempt(result, project, profile_id, config, legacy, collect_evidence=collect_evidence,
                 ac_ids=ac_ids, timeout_budget=remaining)
        history.append({"attempt": attempt, "run_id": result.get("verification_run_id"),
                        "status": result.get("verification_status")})
        if result.get("verification_status") in {"passed", "not_run"} or result.get("verification", {}).get("interrupted"):
            break
    exhausted = result.get("verification_status") not in {"passed", "not_run"} and not result.get("verification", {}).get("interrupted")
    result["retry"] = {"attempts": history, "max_attempts": attempts, "max_minutes": minutes, "exhausted": exhausted}
    if exhausted:
        result.update(passed=False, run_state="waiting")
        result["retry"]["reason"] = "verification retry budget exhausted"
        if history and result.get("observability", {}).get("stored"):
            try:
                recovery.transition(history[-1]["run_id"], "waiting", result["retry"]["reason"])
            except Exception as exc:
                result["retry"]["state_error"] = type(exc).__name__
