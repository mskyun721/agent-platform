"""Runtime configuration for agent-platform MCP server."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

# File that stores the currently active target project path.
# Written by project_init; read by feature/log tools.
_ACTIVE_PROJECT_FILE_NAME = ".active-project"
_AGENT_PLATFORM_ENV_FILE_NAME = ".agent-platform.env"

# MCP tools (project_init, feature_scaffold, log_append, ...) may only read/write
# inside explicitly configured roots. This prevents a target_dir/.active-project
# value from pointing the server at arbitrary filesystem locations.
ALLOWED_PROJECT_ROOTS: tuple[Path, ...] = ()


def allowed_project_roots() -> tuple[Path, ...]:
    """Return allowed target-project roots.

    AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS may contain paths separated by the OS
    path separator (':' on macOS/Linux) or commas. This keeps the production
    safety boundary while letting tests and CI inject temporary roots.
    """
    raw = os.environ.get("AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS", "").strip()
    if not raw:
        raise RuntimeError(
            "AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS is not set. "
            f"Configure it in ROOT/{_AGENT_PLATFORM_ENV_FILE_NAME} or the process environment."
        )

    parts: list[str] = []
    for chunk in raw.split(os.pathsep):
        parts.extend(p.strip() for p in chunk.split(","))
    roots = tuple(Path(p).expanduser().resolve() for p in parts if p)
    if not roots:
        raise RuntimeError("AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS does not contain any usable paths.")
    return roots


def _ensure_within_allowed_roots(path: Path) -> Path:
    """Raise if `path` is not located under one of ALLOWED_PROJECT_ROOTS."""
    resolved = path.expanduser().resolve()
    roots = allowed_project_roots()
    if not any(resolved == root or resolved.is_relative_to(root) for root in roots):
        allowed = ", ".join(str(r) for r in roots)
        raise RuntimeError(
            f"Target project path '{resolved}' is outside the allowed MCP roots ({allowed})."
        )
    return resolved


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
        if not p.is_dir():
            return None
        return _ensure_within_allowed_roots(p)

    active_file = ROOT / _ACTIVE_PROJECT_FILE_NAME
    if active_file.is_file():
        content = active_file.read_text(encoding="utf-8").strip()
        if content:
            p = Path(content).expanduser().resolve()
            if not p.is_dir():
                return None
            return _ensure_within_allowed_roots(p)
    return None


def set_active_project(path: Path) -> None:
    """Persist the target project path to ROOT/.active-project.

    Raises if `path` is outside ALLOWED_PROJECT_ROOTS, so MCP tools cannot be
    redirected to write outside the intended workspace.
    """
    resolved = _ensure_within_allowed_roots(path)
    active_file = ROOT / _ACTIVE_PROJECT_FILE_NAME
    active_file.write_text(str(resolved) + "\n", encoding="utf-8")


def docs_root(project_dir: Path | None = None) -> Path:
    """Return the project root that docs/<type>/<name> paths are relative to."""
    return project_dir or target_project_root() or ROOT


def docs_dir(name: str, project_dir: Path | None = None) -> Path:
    """Return the docs/<type>/<name> directory for a feature/fix/refactor item.

    `name` may include a leading `<type>/` segment (e.g. "fix/login-bug" ->
    docs/fix/login-bug). A bare name with no '/' defaults to
    docs/features/<name> for backward compatibility.
    """
    base = docs_root(project_dir)
    if "/" in name:
        return base / "docs" / name
    return base / "docs" / "features" / name


def log_file(project_dir: Path | None = None) -> Path:
    """Return the claude_log.md path for the active (or given) project."""
    base = project_dir or target_project_root() or ROOT
    return base / "claude_log.md"


ROOT: Path = project_root()
# Load local agent-platform environment files; existing env vars take precedence.
load_dotenv(ROOT / _AGENT_PLATFORM_ENV_FILE_NAME, override=False)
load_dotenv(ROOT / ".env.local", override=False)

TEMPLATES_DIR: Path = ROOT / "templates"
LOG_FILE: Path = ROOT / "claude_log.md"            # legacy — prefer log_file()

_AGENT_CONFIG_FILE_NAME = ".agent-config.json"
_DEFAULT_CLI = "gemini"
_VALID_CLI = {"gemini", "codex"}
_DEFAULT_AGENT_CLI: dict[str, str | list[str]] = {
    "backend": "claude",
    "reviewer": ["codex", "gemini"],
    "planner": "codex",
    "security": "codex",
    "qa": "codex",
    "cicd": "codex",
}


def agent_config() -> dict:
    """Read .agent-config.json from agent-platform root.

    Returns defaults when file is missing or malformed.
    """
    cfg_path = ROOT / _AGENT_CONFIG_FILE_NAME
    defaults: dict = {
        "preferred_cli": _DEFAULT_CLI,
        "agent_cli_defaults": _DEFAULT_AGENT_CLI,
        "model_overrides": {},
    }
    if not cfg_path.is_file():
        return defaults
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        return {**defaults, **data}
    except (json.JSONDecodeError, OSError):
        return defaults


def preferred_cli() -> str:
    """Return the preferred CLI tool ('gemini' or 'codex')."""
    cli = agent_config().get("preferred_cli", _DEFAULT_CLI)
    return cli if cli in _VALID_CLI else _DEFAULT_CLI


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
    "cicd": [
        "PRD.md",
        "API-SPEC.md",
        "DECISIONS.md",
        "REVIEW.md",
        "SECURITY-AUDIT.md",
        "TEST-PLAN.md",
    ],
}


class ConfigError(Exception):
    """Raised when required environment variables are missing."""


def apidog_config() -> dict[str, str]:
    """Return API Dog connection config from environment variables.

    Returns a dict with key: token.
    Raises ConfigError if APIDOG_API_TOKEN is missing.
    """
    token = os.environ.get("APIDOG_API_TOKEN", "").strip()
    if not token:
        raise ConfigError("Missing env var: APIDOG_API_TOKEN")
    return {"token": token}


def confluence_config() -> dict[str, str]:
    """Return Confluence connection config from environment variables.

    Returns a dict with keys: url, email, token.
    Raises ConfigError listing all missing variable names.
    """
    url = os.environ.get("CONFLUENCE_URL", "").strip()
    email = os.environ.get("CONFLUENCE_EMAIL", "").strip()
    token = os.environ.get("CONFLUENCE_API_TOKEN", "").strip()
    missing = [
        name
        for name, val in [
            ("CONFLUENCE_URL", url),
            ("CONFLUENCE_EMAIL", email),
            ("CONFLUENCE_API_TOKEN", token),
        ]
        if not val
    ]
    if missing:
        raise ConfigError(f"Missing env vars: {', '.join(missing)}")
    return {"url": url, "email": email, "token": token}
