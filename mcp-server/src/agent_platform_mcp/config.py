"""Runtime configuration for agent-platform MCP server."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Legacy file that listed target projects (first line = default). Read until
# `project-migrate` moves it into the registry (.agent-projects.json) and renames it.
_ACTIVE_PROJECT_FILE_NAME = ".active-project"
_AGENT_PLATFORM_ENV_FILE_NAME = ".env"
# Pre-unification names. Still loaded so an existing checkout keeps working, with a
# one-line notice to merge them into .env.
_LEGACY_ENV_FILE_NAMES = (".agent-platform.env", ".env.local")
# Deprecated: workspaces now live in .agent-projects.json. The env value is only a
# fallback while the registry has no workspaces and was never migrated (CI, tests,
# unmigrated checkouts); `env_fallback: false` in the registry turns it off for good.
ALLOW_ENV = "AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS"

# MCP tools (project_init, feature_scaffold, ...) may only read/write inside the
# platform root, a workspace, or a registered project. Only the user, from the CLI,
# can add workspaces or register paths outside them; agents must ask the user.
ALLOWED_PROJECT_ROOTS: tuple[Path, ...] = ()
_WARNED: set[str] = set()


def _warn_once(key: str, message: str) -> None:
    if key not in _WARNED:
        _WARNED.add(key)
        print(f"agent-platform: {message}", file=sys.stderr)


def _registry() -> dict:
    from agent_platform_mcp.tools import projects

    return projects._read()


def env_project_roots() -> tuple[Path, ...]:
    """Roots from the deprecated AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS (':' or ',' separated)."""
    parts: list[str] = []
    for chunk in os.environ.get(ALLOW_ENV, "").strip().split(os.pathsep):
        parts.extend(p.strip() for p in chunk.split(","))
    return tuple(Path(p).expanduser().resolve() for p in parts if p)


def _workspace_state() -> tuple[tuple[Path, ...], bool]:
    """(workspaces, env_fallback). Registry workspaces win; the env is used only when there are
    none and the registry was never migrated (`env_fallback` still true)."""
    data = _registry()
    stored = tuple(Path(p) for p in data["workspaces"])  # stored resolved; never re-followed
    env = env_project_roots()
    if stored or not data["env_fallback"]:
        if env:
            _warn_once("env", f"{ALLOW_ENV} is deprecated and ignored (workspaces are in .agent-projects.json); "
                              "remove it from .env")
        return stored, False
    if env:
        _warn_once("env-fallback", f"using the deprecated {ALLOW_ENV} as the workspaces; ask the user to run "
                                   "`agent-platform-agent project-migrate`")
    return env, bool(env)


def workspaces() -> tuple[Path, ...]:
    return _workspace_state()[0]


def env_fallback_active() -> bool:
    return _workspace_state()[1]


def allowed_project_roots() -> tuple[Path, ...]:
    """Workspaces: where projects may be cloned/created and registered over MCP."""
    roots = workspaces()
    if not roots:
        raise RuntimeError("No workspace is configured. Ask the user to run "
                           "`agent-platform-agent project-workspace add <dir>` (agents must not change workspaces).")
    return roots


def _within(path: Path, bases) -> bool:
    return any(path == base or path.is_relative_to(base) for base in bases)


def _identity(path: Path) -> tuple[int, int] | None:
    try:
        status = path.stat()
    except OSError:
        return None
    return status.st_dev, status.st_ino


def platform_relation(path: Path) -> str | None:
    """'root' when `path` is this checkout, 'inside' when it is under it, else None.

    Compared by device/inode, so a case variant on a case-insensitive filesystem (or
    a not yet created child) is still recognised.
    """
    root = _identity(ROOT)
    if root is None:
        return None
    for node in (path, *path.parents):
        if _identity(node) == root:
            return "root" if node == path else "inside"
    return None


def contains_platform(path: Path) -> bool:
    """True when this checkout is under `path` (`path` is one of its ancestors)."""
    target = _identity(path)
    return target is not None and any(_identity(node) == target for node in ROOT.resolve().parents)


def _reject_platform_subtree(resolved: Path) -> None:
    if platform_relation(resolved) == "inside":
        raise RuntimeError(f"Target project path '{resolved}' is inside the agent-platform checkout; "
                           "only the platform root itself may be selected.")


def ensure_within_workspaces(path: Path) -> Path:
    """Raise unless `path` (symlinks resolved) is inside a workspace. Registered paths do not count.
    The platform checkout and its subtree never count, whatever the workspaces contain."""
    resolved = path.expanduser().resolve()
    _reject_platform_subtree(resolved)
    if platform_relation(resolved) == "root":
        raise RuntimeError("The agent-platform checkout is not a workspace project; select it with --root.")
    roots = workspaces()
    if not _within(resolved, roots):
        allowed = ", ".join(str(r) for r in roots) or "none configured"
        raise RuntimeError(f"Target project path '{resolved}' is outside the workspaces ({allowed}).")
    return resolved


def _ensure_within_allowed_roots(path: Path) -> Path:
    """Raise unless `path` is inside a workspace or a registered project.

    With the deprecated env fallback active, registered paths grant nothing (the
    pre-registry rule: only the configured roots count).
    """
    resolved = path.expanduser().resolve()
    _reject_platform_subtree(resolved)  # unconditional, even under a workspace that contains it
    roots, fallback = _workspace_state()
    # A registered platform root still grants only itself (checked by callers), never its subtree.
    registered = [] if fallback else [Path(r["path"]) for r in _registry()["projects"].values()]
    bases = [*roots, *(base for base in registered if base != ROOT.resolve())]
    if not _within(resolved, bases):
        allowed = ", ".join(str(r) for r in roots) or "none configured"
        raise RuntimeError(
            f"Target project path '{resolved}' is outside the allowed MCP roots ({allowed}) "
            "and is not a registered project."
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


def legacy_active_file() -> Path | None:
    """ROOT/.active-project while it has not been migrated; warns once."""
    active_file = ROOT / _ACTIVE_PROJECT_FILE_NAME
    if not active_file.is_file():
        return None
    _warn_once("legacy", f"{_ACTIVE_PROJECT_FILE_NAME} is deprecated; ask the user to run "
                         "`agent-platform-agent project-migrate` to move it into .agent-projects.json")
    return active_file


def _legacy_entries(active_file: Path) -> list[Path]:
    entries: list[Path] = []
    for line in active_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        path = Path(line).expanduser().resolve()
        if path not in entries:
            entries.append(path)
    return entries


def active_projects() -> list[Path]:
    """Every target, default first.

    Registry: registered projects (except the platform itself) with `default` first.
    Legacy (unmigrated .active-project): its lines in file order. Entries are not
    validated here — the allowlist is enforced when one is actually used.
    """
    legacy = legacy_active_file()
    if legacy is not None:
        return _legacy_entries(legacy)
    data = _registry()
    default = data["default"]
    ordered = ([default] if default else []) + [key for key in data["projects"] if key != default]
    paths = [Path(data["projects"][key]["path"]) for key in ordered]
    return [path for path in paths if path != ROOT.resolve()]


def _default_project() -> Path | None:
    legacy = legacy_active_file()
    if legacy is not None:
        entries = _legacy_entries(legacy)
        return entries[0] if entries else None
    data = _registry()
    if not data["default"]:
        return None
    if data["default_path"] and not Path(data["default_path"]).is_dir():
        _warn_once("default-path", f"the default worktree {data['default_path']} no longer exists; ask the user to "
                                   "run `agent-platform-agent project-use <id>`")
    return Path(data["default_path"] or data["projects"][data["default"]]["path"])  # a worktree stays itself


def active_project_by_name(name: str) -> Path | None:
    """Return the target or registered project whose folder name is `name`; raise when ambiguous."""
    candidates = list(active_projects())
    for record in _registry()["projects"].values():
        path = Path(record["path"])
        if path not in candidates:
            candidates.append(path)
    matches = [path for path in candidates if path.name == name]
    if len(matches) > 1:
        raise ProjectAmbiguous(f"'{name}' matches several targets; pass the project_id or full path instead "
                           f"(for a directory relative to the current one, use ./{name}).")
    return matches[0] if matches else None


def target_project_root() -> Path | None:
    """Return the default target project root, or None if not set.

    The registry `default` (legacy: first line of an unmigrated .active-project).
    Can be overridden with TARGET_PROJECT_ROOT env var.
    """
    env = os.environ.get("TARGET_PROJECT_ROOT")
    if env:
        p = Path(env).expanduser().resolve()
        if not p.is_dir():
            return None
        return _ensure_within_allowed_roots(p)

    default = _default_project()
    if default is None or not default.is_dir():
        return None
    return _ensure_within_allowed_roots(default)


def set_active_project(path: Path) -> None:
    """Make `path` the default target.

    Legacy checkout: first line of .active-project, others kept below it. Registry:
    `default` = the project registered at `path` (it must be registered). Raises if
    `path` is outside the allowed roots.
    """
    resolved = _ensure_within_allowed_roots(path)
    legacy = legacy_active_file()
    if legacy is None:
        from agent_platform_mcp.tools import projects

        projects.set_default_path(resolved)
        return
    others = [entry for entry in _legacy_entries(legacy) if entry != resolved]
    legacy.write_text("".join(f"{entry}\n" for entry in (resolved, *others)), encoding="utf-8")


def add_active_project(path: Path) -> None:
    """Legacy only: list `path` in .active-project without changing the default."""
    resolved = _ensure_within_allowed_roots(path)
    legacy = legacy_active_file()
    if legacy is None:
        return
    entries = _legacy_entries(legacy)
    if resolved not in entries:
        legacy.write_text("".join(f"{entry}\n" for entry in (*entries, resolved)), encoding="utf-8")


class ProjectNotFound(RuntimeError):
    """No project could be selected (no default target). A RuntimeError, so old handlers still match.

    Scope (Review L-8): raised only by `docs_root` when there is no default target. A root path
    that does not exist is still `FileNotFoundError` (`_resolve_project_path`), and an unregistered
    ref passed to `projects.use` is `ValueError`; callers that judge errors by type handle those too.
    """


class ProjectAmbiguous(RuntimeError):
    """A bare folder name matches several targets. A RuntimeError, so old handlers still match."""


def docs_root(project_dir: Path | None = None) -> Path:
    """Return the project root that docs/<type>/<name> paths are relative to.

    Raises when no target project is active: docs artifacts must never be
    written into the agent-platform repository itself (see CLAUDE.md policy).
    """
    base = project_dir or target_project_root()
    if base is None:
        raise ProjectNotFound(
            "No active target project. Run project_init, ask the user to run "
            "`agent-platform-agent project-add <path> --default`, or set TARGET_PROJECT_ROOT. "
            "Docs artifacts must not be written "
            "under the agent-platform repository."
        )
    return base


def _resolve_project_path(root: str | Path | None = None) -> Path:
    """Resolve one request without changing process or active-project state.

    Explicit self-target permits only this checkout, not its whole subtree.
    All external projects continue to require the configured allowlist.
    """
    if root is None:
        return docs_root().resolve()
    # A bare folder name selects a target/registered project before any relative path.
    listed = active_project_by_name(str(root)) if os.sep not in str(root) else None
    path = listed if listed is not None else Path(root).expanduser().resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"Project root is not a directory: {path}")
    if path == ROOT.resolve() or platform_relation(path) == "root":
        return ROOT.resolve()  # a case variant of the checkout is still the checkout
    return _ensure_within_allowed_roots(path)


def resolve_project(root: str | Path | None = None):
    from agent_platform_mcp.tools.projects import resolve

    return resolve(root)


def resolve_project_dir(root: str | Path | None = None) -> Path:
    """Resolve a registered ID or path without rebinding the active project."""
    return resolve_project(root).path


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


ROOT: Path = project_root()
# ROOT/.env is the single local environment file; existing env vars take precedence.
load_dotenv(ROOT / _AGENT_PLATFORM_ENV_FILE_NAME, override=False)
for _legacy in _LEGACY_ENV_FILE_NAMES:
    if (ROOT / _legacy).is_file():
        load_dotenv(ROOT / _legacy, override=False)
        print(f"agent-platform: {_legacy} is deprecated; move its values into "
              f"{_AGENT_PLATFORM_ENV_FILE_NAME}", file=sys.stderr)

TEMPLATES_DIR: Path = ROOT / "templates"

_AGENT_CONFIG_FILE_NAME = ".agent-config.json"
_DEFAULT_CLI = "codex"
from agent_platform_mcp.backends import NAMES as _BACKEND_NAMES  # noqa: E402
_VALID_CLI = set(_BACKEND_NAMES)


def agent_config() -> dict:
    """Read .agent-config.json from agent-platform root.

    Returns defaults when file is missing or malformed.
    """
    cfg_path = ROOT / _AGENT_CONFIG_FILE_NAME
    defaults: dict = {
        "preferred_cli": _DEFAULT_CLI,
        "cli_models": {},
    }
    if not cfg_path.is_file():
        return defaults
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        return {**defaults, **data}
    except (json.JSONDecodeError, OSError):
        return defaults


def cli_model(cli: str) -> str | None:
    """Return the pinned model for an external CLI backend, if configured."""
    models = agent_config().get("cli_models", {})
    model = models.get(cli)
    return model if isinstance(model, str) and model else None


def risk_rules() -> dict:
    """Path patterns (fnmatch, relative to the project) that mark a change as
    risky. A hit against a `risk: low` declaration fails the gate; a hit with
    no declaration only reports. Missing config means no patterns."""
    rules = agent_config().get("risk_rules", {})
    if not isinstance(rules, dict):
        raise ValueError("risk_rules must be an object")
    paths = rules.get("paths", [])
    if not isinstance(paths, list) or any(not isinstance(p, str) or not p for p in paths):
        raise ValueError("risk_rules.paths must be an array of non-empty patterns")
    return {"paths": paths}


def preferred_cli() -> str:
    """Return the legacy preferred backend; role execution uses strict routing."""
    cli = agent_config().get("preferred_cli", _DEFAULT_CLI)
    return cli if cli in _VALID_CLI else _DEFAULT_CLI


VALID_AGENTS = {"planner", "backend", "qa", "cicd", "orchestrator", "reviewer", "security", "dba", "investment", "quant", "investment-risk"}
VALID_STATUSES = {"draft", "review", "approved", "rejected"}

# Artifacts each agent is responsible for producing.
AGENT_OUTPUTS: dict[str, list[str]] = {
    "investment": ["INVESTMENT-REPORT.md"],
    "quant": ["QUANT-REPORT.md"],
    "investment-risk": ["INVESTMENT-RISK.md"],
    "planner": ["PRD.md", "TASK.md"],
    "backend": ["API-SPEC.md", "DECISIONS.md"],
    "reviewer": ["REVIEW.md"],
    "security": ["SECURITY-AUDIT.md"],
    "dba": ["DB-REVIEW.md"],
    "qa": ["TEST-PLAN.md"],
    "cicd": ["RELEASE-NOTE.md", "PR-BODY.md", "DEPLOY-CHECKLIST.md"],
}

# Prerequisite artifacts that must be `approved` before a given agent can start.
AGENT_PREREQUISITES: dict[str, list[str]] = {
    "planner": [], "investment": [], "quant": [], "investment-risk": [],
    "backend": ["PRD.md", "TASK.md"],
    "reviewer": ["PRD.md", "API-SPEC.md", "DECISIONS.md"],
    "security": ["PRD.md", "API-SPEC.md", "DECISIONS.md"],
    # DB-REVIEW.md: dba schema/query review with the 1s read SLO; "해당 없음" is still an approved file.
    "dba": ["PRD.md", "API-SPEC.md", "DECISIONS.md"],
    "qa": ["PRD.md", "API-SPEC.md", "DECISIONS.md", "REVIEW.md", "SECURITY-AUDIT.md", "DB-REVIEW.md"],
    "cicd": [
        "PRD.md",
        "API-SPEC.md",
        "DECISIONS.md",
        "REVIEW.md",
        "SECURITY-AUDIT.md",
        "DB-REVIEW.md",
        "TEST-PLAN.md",
    ],
}


# Lightweight track for small fixes: docs/fix/* and docs/hotfix/* items only
# need PRD + REVIEW instead of the full 7-document chain.
LIGHT_TRACK_PREFIXES: tuple[str, ...] = ("fix/", "hotfix/")
AGENT_PREREQUISITES_LIGHT: dict[str, list[str]] = {
    "planner": [], "investment": [], "quant": [], "investment-risk": [],
    "backend": ["PRD.md"],
    "reviewer": ["PRD.md"],
    "security": ["PRD.md"],
    "dba": ["PRD.md"],
    "qa": ["PRD.md", "REVIEW.md", "DB-REVIEW.md"],
    "cicd": ["PRD.md", "REVIEW.md", "DB-REVIEW.md"],
}


# Project-level structure document (target root). Required before any role touches code.
STRUCTURE_DOC = "ARCHITECTURE.md"
STRUCTURE_REQUIRED_AGENTS = {"backend", "reviewer", "security", "dba", "qa"}

VALID_CONTRACTS = {"work-v1"}
VALID_RISK = {"low", "high"}
AGENT_PREREQUISITES_BY_TRACK = {
    "full": AGENT_PREREQUISITES,
    "light": AGENT_PREREQUISITES_LIGHT,
    "work": {
        "planner": [], "investment": [], "quant": [], "investment-risk": [], "backend": ["WORK.md"], "reviewer": ["WORK.md"],
        "security": ["WORK.md"], "dba": ["WORK.md"], "qa": ["WORK.md", "REVIEW.md", "DB-REVIEW.md"],
        "cicd": ["WORK.md", "REVIEW.md", "DB-REVIEW.md"],
    },
}


def agent_prerequisites(track: str, agent: str, risk: object = None) -> list[str]:
    """Approved artifacts an agent needs on a track; declared high risk adds SECURITY-AUDIT.md for qa/cicd."""
    required = list(AGENT_PREREQUISITES_BY_TRACK[track][agent])
    if risk == "high" and agent in {"qa", "cicd"} and "SECURITY-AUDIT.md" not in required:
        required.append("SECURITY-AUDIT.md")
    return required


AGENT_OUTPUTS_BY_TRACK = {
    "full": AGENT_OUTPUTS,
    "light": {**AGENT_OUTPUTS, "planner": ["PRD.md"], "backend": []},
    "work": {**AGENT_OUTPUTS, "planner": ["WORK.md"], "backend": ["WORK.md"],
             "qa": ["WORK.md"], "cicd": ["WORK.md"]},
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


NOTION_TOKEN_PREFIXES = ("ntn_", "secret_")


def notion_config() -> dict[str, str]:
    """Return Notion connection config from environment variables.

    Read at call time only (never at import). Returns a dict with key: token.
    Raises ConfigError if NOTION_TOKEN is missing, or if it is not a Notion integration
    secret (`ntn_`/`secret_` prefix, printable ASCII without whitespace). The token value
    never appears in the error message.
    """
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        raise ConfigError("Missing env var: NOTION_TOKEN")
    if (not token.startswith(NOTION_TOKEN_PREFIXES) or not token.isascii() or not token.isprintable()
            or any(c.isspace() for c in token)):
        raise ConfigError("Invalid NOTION_TOKEN format")
    return {"token": token}
