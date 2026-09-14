#!/usr/bin/env python3
"""Explicit, bounded native skill discovery smoke; never run by normal pytest."""

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server/src"))
from agent_platform_mcp.tools import projects, skill_packages as packages, skills


def invoke(backend: str, workspace: Path, token: str, timeout: int) -> dict:
    prompt = (
        "This is a native skill discovery test. If platform-native-probe is in your native available "
        "skills list, invoke it and follow it. Otherwise reply exactly SKILL_UNAVAILABLE. "
        "Do not discover skill files by searching directories. Do not invoke another AI, agent, MCP, "
        "or external tool. Do not read credentials or modify any file."
    )
    argv = (["codex", "exec", "--sandbox", "read-only", "--skip-git-repo-check", prompt]
            if backend == "codex" else ["claude", "-p", prompt, "--strict-mcp-config", "--no-session-persistence",
                                       "--tools", "Skill,Read", "--allowedTools", "Skill", "Read"])
    proc = subprocess.Popen(argv, cwd=workspace, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return {"exit_code": proc.returncode, "token_observed": token in stdout,
                "unavailable_observed": "SKILL_UNAVAILABLE" in stdout,
                "permission_error": any(value in (stdout + stderr).lower() for value in
                                        ("operation not permitted", "permission denied")),
                "authentication_error": any(value in (stdout + stderr).lower() for value in
                                           ("not logged in", "authentication", "invalid api key"))}
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        return {"exit_code": None, "timeout": True, "token_observed": False, "unavailable_observed": False}


def smoke(backend: str, timeout: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="platform-skill-smoke-") as temp:
        root = Path(temp).resolve()
        source, target = root / "source", root / "project"
        source.mkdir()
        target.mkdir()
        token = "NATIVE_PROBE_" + uuid.uuid4().hex
        (source / "SKILL.md").write_text(
            "---\nname: platform-native-probe\ndescription: Respond to the platform native discovery test.\n---\n"
            f"Reply exactly {token}. Do not invoke tools or modify files.\n")
        (source / "skill.json").write_text(json.dumps({"id": "platform-native-probe", "version": "1.0.0",
                                                     "supports": [backend]}))
        with patch.object(projects, "REGISTRY_FILE", root / ".agent-projects.json"), \
             patch.object(packages, "PACKAGES", root / "packages"), \
             patch.object(packages, "REGISTRY", root / "registry.json"), \
             patch.dict(os.environ, {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": str(root)}):
            projects.register(str(target), "smoke-project")
            packages.add(str(source))
            skills.enable("platform-native-probe", "smoke-project")
            enabled = invoke(backend, target, token, timeout)
            if enabled["exit_code"] != 0 or not enabled["token_observed"]:
                return {"backend": backend, "passed": False, "enabled": enabled, "disabled": None,
                        "reason": "native enabled discovery not verified"}
            disabled_state = skills.disable("platform-native-probe", "smoke-project")
            disabled = invoke(backend, target, token, timeout)
            packages.remove("platform-native-probe")
            passed = (disabled_state["complete"] and disabled["exit_code"] == 0 and
                      disabled["unavailable_observed"] and not disabled["token_observed"])
            return {"backend": backend, "passed": passed, "enabled": enabled, "disabled": disabled,
                    "removed": not (packages.PACKAGES / "platform-native-probe").exists()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["claude", "codex"], required=True)
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()
    if not 10 <= args.timeout <= 180:
        parser.error("timeout must be between 10 and 180 seconds per invocation")
    result = smoke(args.backend, args.timeout)
    result.update(raw_output_retained=False, model=None, usage=None)
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
