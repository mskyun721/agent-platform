"""Runtime configuration for agent-platform MCP server."""

from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    """Resolve the agent-platform project root.

    Priority:
      1. `AGENT_PLATFORM_ROOT` env var (explicit override)
      2. Walk up from this file until a directory containing `CLAUDE.md`
         and a `standards/` folder is found.
    """
    env = os.environ.get("AGENT_PLATFORM_ROOT")
    if env:
        root = Path(env).expanduser().resolve()
        if not root.exists():
            raise RuntimeError(f"AGENT_PLATFORM_ROOT does not exist: {root}")
        return root

    here = Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "CLAUDE.md").is_file() and (candidate / "standards").is_dir():
            return candidate
    raise RuntimeError(
        "Unable to locate agent-platform root. Set AGENT_PLATFORM_ROOT env var."
    )


ROOT: Path = project_root()
FEATURES_DIR: Path = ROOT / "docs" / "features"
TEMPLATES_DIR: Path = ROOT / "templates"
LOG_FILE: Path = ROOT / "claude_log.md"

VALID_AGENTS = {"planner", "backend", "qa", "cicd", "orchestrator", "reviewer", "security"}
VALID_STATUSES = {"draft", "review", "approved", "rejected"}

# Artifacts each agent is responsible for producing.
AGENT_OUTPUTS: dict[str, list[str]] = {
    "planner": ["PRD.md", "TASK.md"],
    "backend": ["API-SPEC.md", "DECISIONS.md"],
    "reviewer": ["REVIEW.md"],
    "security": ["SECURITY-AUDIT.md"],
    "qa": ["TEST-PLAN.md"],
    "cicd": ["RELEASE-NOTE.md", "PR-BODY.md", "DEPLOY-CHECKLIST.md"],
}

# Prerequisite artifacts that must be `approved` before a given agent can start.
AGENT_PREREQUISITES: dict[str, list[str]] = {
    "planner": [],
    "backend": ["PRD.md", "TASK.md"],
    "reviewer": ["PRD.md", "API-SPEC.md", "DECISIONS.md"],
    "security": ["PRD.md", "API-SPEC.md", "DECISIONS.md"],
    "qa": ["PRD.md", "API-SPEC.md", "DECISIONS.md", "REVIEW.md", "SECURITY-AUDIT.md"],
    "cicd": ["PRD.md", "API-SPEC.md", "TEST-PLAN.md"],
}
