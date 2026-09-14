#!/usr/bin/env python3
"""Read CLI version/help only; never starts an AI task or infers runtime capabilities."""

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone


def probe(binary: str) -> dict:
    if binary not in {"claude", "codex"}:
        raise ValueError("unsupported CLI probe")
    result = {"backend": binary, "status": "unavailable", "version": None, "flags": {}}
    if shutil.which(binary) is None:
        return result
    try:
        version = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10, check=False)
        if version.returncode:
            return {**result, "status": "error", "reason": "version command failed"}
        match = re.search(r"\b\d+\.\d+\.\d+(?:[-+][\w.-]+)?", version.stdout)
        result.update(status="available", version=match.group(0) if match else None)
        command = [binary, "exec", "--help"] if binary == "codex" else [binary, "--help"]
        help_result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
        if help_result.returncode:
            return {**result, "status": "partial", "reason": "help command failed"}
        flags = ("--sandbox", "--json", "--output-schema", "--full-auto") if binary == "codex" else (
            "--permission-mode", "--output-format", "--resume", "--agent")
        result["flags"] = {flag: "supported" if re.search(re.escape(flag) + r"(?=[\s,=]|$)", help_result.stdout)
                           else "unverified" for flag in flags}
        return result
    except (OSError, subprocess.TimeoutExpired):
        return {**result, "status": "error", "reason": "probe unavailable or timed out"}


def snapshot() -> dict:
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "evidence": "version/help only",
            "backends": [probe(name) for name in ("claude", "codex")]}


if __name__ == "__main__":
    print(json.dumps(snapshot(), indent=2))
