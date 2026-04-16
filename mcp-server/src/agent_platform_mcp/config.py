"""Runtime configuration for agent-platform MCP server."""

from __future__ import annotations

import os
from pathlib import Path

# File that stores the currently active target project path.
# Written by project_init; read by feature/log tools.
_ACTIVE_PROJECT_FILE_NAME = ".active-project"


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


def target_project_root() -> Path | None:
    """Return the active target project root, or None if not set.

    Reads from ROOT/.active-project (written by project_init).
    Can be overridden with TARGET_PROJECT_ROOT env var.
    """
    env = os.environ.get("TARGET_PROJECT_ROOT")
    if env:
        p = Path(env).expanduser().resolve()
        return p if p.is_dir() else None

    active_file = ROOT / _ACTIVE_PROJECT_FILE_NAME
    if active_file.is_file():
        content = active_file.read_text(encoding="utf-8").strip()
        if content:
            p = Path(content).expanduser().resolve()
            return p if p.is_dir() else None
    return None


def set_active_project(path: Path) -> None:
    """Persist the target project path to ROOT/.active-project."""
    active_file = ROOT / _ACTIVE_PROJECT_FILE_NAME
    active_file.write_text(str(path.resolve()) + "\n", encoding="utf-8")


def features_dir(project_dir: Path | None = None) -> Path:
    """Return the docs/features directory for the active (or given) project."""
    base = project_dir or target_project_root() or ROOT
    return base / "docs" / "features"


def log_file(project_dir: Path | None = None) -> Path:
    """Return the claude_log.md path for the active (or given) project."""
    base = project_dir or target_project_root() or ROOT
    return base / "claude_log.md"


ROOT: Path = project_root()
FEATURES_DIR: Path = ROOT / "docs" / "features"   # legacy — prefer features_dir()
TEMPLATES_DIR: Path = ROOT / "templates"
LOG_FILE: Path = ROOT / "claude_log.md"            # legacy — prefer log_file()

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
