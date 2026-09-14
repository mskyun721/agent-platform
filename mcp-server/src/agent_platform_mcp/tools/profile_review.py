"""Explicit operator-facing profile review records; no MCP auto-approval path."""

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from agent_platform_mcp import config
from agent_platform_mcp.tools import projects, verification


def approve(profile_id: str, reviewer: str) -> dict:
    if not reviewer.strip() or len(reviewer) > 128:
        raise ValueError("reviewer identity required")
    path = config.ROOT / ".agent-config.json"
    projects._safe_storage(path)
    with projects._locked():
        data = json.loads(path.read_text())
        profile = data.get("verify_profiles", {}).get(profile_id)
        if not isinstance(profile, dict):
            raise ValueError("unknown verification profile")
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=config.ROOT,
                                  capture_output=True, text=True, timeout=10, check=False)
        if revision.returncode:
            raise ValueError("review requires a known platform revision")
        metadata = {"reviewed_hash": verification.profile_hash(profile), "reviewed_rev": revision.stdout.strip(),
                    "reviewed_by": reviewer, "reviewed_at": datetime.now(timezone.utc).isoformat(),
                    "reviewed_verifier_hash": verification.verifier_hash(config.ROOT)}
        profile.update(metadata)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as output:
                temporary = Path(output.name)
                json.dump(data, output, indent=2, ensure_ascii=False)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
    return {"profile_id": profile_id, **metadata, "limitation": "local record; not a technical human-only boundary"}
