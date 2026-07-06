"""Feature lifecycle tools: scaffold, list artifacts, gate check."""

from __future__ import annotations

import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from agent_platform_mcp import frontmatter
from agent_platform_mcp.config import (
    AGENT_OUTPUTS,
    AGENT_PREREQUISITES,
    AGENT_PREREQUISITES_LIGHT,
    LIGHT_TRACK_PREFIXES,
    TEMPLATES_DIR,
    VALID_AGENTS,
    VALID_STATUSES,
    agent_config,
    docs_dir,
    docs_root,
)

FEATURE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}(?:/[a-z][a-z0-9-]{1,63})*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TEMPLATE_FILES = ("PRD.md", "TASK.md")


def _ensure_safe_name(name: str) -> None:
    if not FEATURE_NAME_RE.match(name):
        raise ValueError(
            f"Invalid feature name '{name}'. Allowed: lowercase alnum + dashes, "
            "2-64 chars per path segment, separated by '/'."
        )


def _render_template(raw: str, feature: str) -> str:
    today = date.today().isoformat()
    doc_path = feature if "/" in feature else f"features/{feature}"
    # Replace the docs/features/<feature-name> link pattern first so a
    # type-prefixed name (e.g. "fix/login-bug") resolves to docs/fix/login-bug
    # instead of docs/features/fix/login-bug.
    out = raw.replace("docs/features/<feature-name>", f"docs/{doc_path}")
    out = out.replace("<feature-name>", feature)
    out = re.sub(r"^(created|updated):\s*YYYY-MM-DD", rf"\1: {today}", out, flags=re.M)
    return out


def scaffold(name: str) -> dict[str, Any]:
    """Create `docs/<type>/<name>/` with PRD.md and TASK.md from templates.

    `name` may include a `<type>/` prefix (e.g. "fix/login-bug" ->
    docs/fix/login-bug); a bare name defaults to docs/features/<name>.
    Docs are written to the active target project (set by project_init);
    raises when no target project is active.
    """
    _ensure_safe_name(name)
    base = docs_root()
    target = docs_dir(name, project_dir=base)
    if target.exists():
        raise FileExistsError(f"Feature directory already exists: {target}")

    target.mkdir(parents=True, exist_ok=False)
    created: list[str] = []
    for fname in TEMPLATE_FILES:
        src = TEMPLATES_DIR / fname
        if not src.is_file():
            raise FileNotFoundError(f"Template missing: {src}")
        rendered = _render_template(src.read_text(encoding="utf-8"), name)
        (target / fname).write_text(rendered, encoding="utf-8")
        created.append(str((target / fname).relative_to(base)))

    return {
        "feature": name,
        "directory": str(target),
        "created_files": created,
        "next": "Invoke @planner to draft the PRD.",
    }


def list_artifacts(name: str) -> dict[str, Any]:
    """Return per-file metadata (agent, status, updated) for a feature."""
    _ensure_safe_name(name)
    target = docs_dir(name)
    if not target.is_dir():
        raise FileNotFoundError(f"Feature not found: {target}")

    items: list[dict[str, Any]] = []
    for path in sorted(target.glob("*.md")):
        fm = frontmatter.read(path)
        items.append(
            {
                "file": path.name,
                "path": str(path),
                "has_frontmatter": fm is not None,
                "agent": (fm or {}).get("agent"),
                "status": (fm or {}).get("status"),
                "updated": (fm or {}).get("updated"),
            }
        )
    return {"feature": name, "artifacts": items, "count": len(items)}


def _validate_file(path: Path, expected_feature: str) -> list[str]:
    errors: list[str] = []
    fm = frontmatter.read(path)
    if fm is None:
        errors.append("front-matter missing")
        return errors

    for field in ("agent", "feature", "status", "created", "updated"):
        if field not in fm or not fm[field]:
            errors.append(f"field '{field}' missing")

    if (agent := fm.get("agent")) and agent not in VALID_AGENTS:
        errors.append(f"invalid agent '{agent}'")
    if (status := fm.get("status")) and status not in VALID_STATUSES:
        errors.append(f"invalid status '{status}'")
    if (feat := fm.get("feature")) and feat != expected_feature:
        errors.append(f"feature mismatch (expected '{expected_feature}', got '{feat}')")
    for dkey in ("created", "updated"):
        if (dval := fm.get(dkey)) and not DATE_RE.match(str(dval)):
            errors.append(f"{dkey} not YYYY-MM-DD: '{dval}'")

    # Forward-reference links are expected to be broken during `draft`.
    # Only enforce link integrity once a document moves to review/approved.
    if fm.get("status") in {"review", "approved"}:
        links = fm.get("links") or {}
        if isinstance(links, dict):
            for key, rel in links.items():
                if not rel:
                    continue
                ref = (docs_root() / rel).resolve()
                if not ref.exists():
                    errors.append(f"links.{key} path missing: {rel}")

    return errors


def _gate_verify_command() -> str | None:
    cmd = agent_config().get("gate_verify_command")
    return cmd if isinstance(cmd, str) and cmd.strip() else None


def _run_gate_verify(result: dict[str, Any]) -> None:
    cmd = _gate_verify_command()
    if not cmd:
        result["verify_skipped"] = "gate_verify_command not configured"
        return
    proc = subprocess.run(
        cmd, shell=True, capture_output=True, text=True,
        cwd=str(docs_root()), timeout=900, check=False,
    )
    result["verify_command"] = cmd
    result["verify_exit_code"] = proc.returncode
    result["verify_output_tail"] = (proc.stdout + proc.stderr)[-800:]
    if proc.returncode != 0:
        result["passed"] = False


def gate_check(name: str, agent: str | None = None, verify: bool = False) -> dict[str, Any]:
    """Validate all artifacts in a feature.

    If `agent` is provided, additionally verify that the prerequisite
    outputs for that agent are present and `approved`. Items whose `name`
    starts with `fix/` or `hotfix/` use the lightweight prerequisite track
    (PRD + REVIEW) instead of the full 7-document chain; the result's
    `track` key reports which one applied.

    If `verify` is True, additionally runs the `gate_verify_command`
    configured in `.agent-config.json` inside the target project and gates
    `passed` on its exit code (see `verify_command`/`verify_exit_code`/
    `verify_output_tail` in the result).
    """
    _ensure_safe_name(name)
    target = docs_dir(name)
    if not target.is_dir():
        raise FileNotFoundError(f"Feature not found: {target}")

    results: list[dict[str, Any]] = []
    for path in sorted(target.glob("*.md")):
        errors = _validate_file(path, name)
        results.append({"file": path.name, "errors": errors, "passed": not errors})

    passed = all(r["passed"] for r in results)

    track = "light" if name.startswith(LIGHT_TRACK_PREFIXES) else "full"
    prereqs = AGENT_PREREQUISITES_LIGHT if track == "light" else AGENT_PREREQUISITES

    agent_check: dict[str, Any] | None = None
    if agent:
        if agent not in prereqs:
            raise ValueError(f"Unknown agent '{agent}'")
        missing: list[str] = []
        not_approved: list[str] = []
        for required in prereqs[agent]:
            fpath = target / required
            if not fpath.is_file():
                missing.append(required)
                continue
            fm = frontmatter.read(fpath) or {}
            if fm.get("status") != "approved":
                not_approved.append(f"{required} (status={fm.get('status')})")
        agent_check = {
            "agent": agent,
            "missing": missing,
            "not_approved": not_approved,
            "passed": not missing and not not_approved,
        }
        passed = passed and agent_check["passed"]

    result: dict[str, Any] = {
        "feature": name,
        "track": track,
        "passed": passed,
        "files": results,
        "agent_gate": agent_check,
    }
    if verify:
        _run_gate_verify(result)
    return result
