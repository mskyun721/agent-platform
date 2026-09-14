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
    "mcp-server/src/agent_platform_mcp/tools/feature.py",
    "mcp-server/src/agent_platform_mcp/tools/handoff.py",
    "mcp-server/src/agent_platform_mcp/tools/verification.py",
)
SUGGESTIONS = (("gradlew", "gradle"), ("mvnw", "maven"), ("pyproject.toml", "pytest"))


def profile_hash(profile: dict[str, Any]) -> str:
    body = {key: value for key, value in profile.items() if key != "reviewed_hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


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
    status = "changed" if dirty or (reviewed and reviewed != current) else (
        "unchanged" if reviewed == current and not errors else "unreviewed"
    )
    return status, {
        "profile_hash": current, "reviewed_hash": reviewed,
        "verifier_code_dirty": dirty, "inspection_errors": errors,
        "loaded_platform_root": str(ROOT), "project_dir": str(project),
        "enforcement": "advisory; commit is not approval",
    }


def _run(
    result: dict[str, Any], project: Path, profile_id: str | None,
    config: dict[str, Any], legacy: str | None,
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
    try:
        proc = subprocess.run(
            command, shell=info["mode"] == "shell-compat", cwd=cwd,
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        status = "error"
        info.update(error=f"timeout after {timeout}s", exit_code=None)
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


def run(result: dict[str, Any], project: Path, profile_id: str | None,
        config: dict[str, Any], legacy: str | None, *, collect_evidence: bool = False,
        ac_ids: list[str] | None = None) -> None:
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
    _run(result, project, profile_id, config, legacy)
    details = result.get("verification", {})
    recorded = observation.point(result, projects.ProjectContext(result.get("project_id"), project), "qa", "verification",
        {"profile_id": profile_id, "status": result.get("verification_status"),
         "exit_code": details.get("exit_code"), "duration_sec": details.get("duration_sec")})
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
