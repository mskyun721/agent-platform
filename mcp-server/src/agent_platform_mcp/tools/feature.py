"""Feature lifecycle tools: scaffold, list artifacts, gate check."""

from __future__ import annotations

import fnmatch
import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from agent_platform_mcp import frontmatter
from agent_platform_mcp.config import (
    AGENT_PREREQUISITES_BY_TRACK,
    LIGHT_TRACK_PREFIXES,
    TEMPLATES_DIR,
    VALID_AGENTS,
    VALID_STATUSES,
    VALID_CONTRACTS,
    VALID_RISK,
    agent_config,
    docs_dir,
    resolve_project,
    risk_rules,
)
from agent_platform_mcp.tools import verification

FEATURE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}(?:/[a-z][a-z0-9-]{1,63})*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TEMPLATE_FILES = ("PRD.md", "TASK.md")
WORK_SECTIONS = ("## 1. 목표", "## 2. 범위", "## 3. 위험", "## 4. 검증", "## 5. 결정", "## 6. 결과")


def _ensure_safe_name(name: str) -> None:
    if not FEATURE_NAME_RE.fullmatch(name):
        raise ValueError(
            f"Invalid feature name '{name}'. Allowed: lowercase alnum + dashes, "
            "2-64 chars per path segment, separated by '/'."
        )


def canonical_feature(name: str) -> str:
    _ensure_safe_name(name)
    parts = name.split("/")
    return parts[1] if len(parts) == 2 and parts[0] == "features" else name


def _safe_path(path: Path, project: Path) -> None:
    """Reject symlinks before reading or creating artifacts."""
    if not path.is_relative_to(project):
        raise ValueError("artifact path escapes project")
    node = path
    while node != project:
        if node.is_symlink():
            raise ValueError(f"artifact symlink not allowed: {path.relative_to(project)}")
        node = node.parent
    if not path.resolve().is_relative_to(project):
        raise ValueError("artifact path escapes project")


def _link_error(rel: str, project: Path, document: Path) -> str | None:
    if rel.startswith(("https://", "http://")):
        return None
    if Path(rel).is_absolute():
        return "must be relative"
    target = (project if rel.startswith("docs/") else document) / rel
    try:
        _safe_path(target, project)
    except ValueError as exc:
        return str(exc)
    if not target.resolve().is_relative_to(project / "docs"):
        return "escapes docs/"
    if not target.is_file():
        return "path missing"
    return None


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


def scaffold(name: str, root: str | Path | None = None, contract: str | None = None) -> dict[str, Any]:
    """Create `docs/<type>/<name>/` with PRD.md and TASK.md from templates.

    `name` may include a `<type>/` prefix (e.g. "fix/login-bug" ->
    docs/fix/login-bug); a bare name defaults to docs/features/<name>.
    Docs are written to the active target project (set by project_init);
    raises when no target project is active.
    """
    if contract is not None and contract not in VALID_CONTRACTS:
        raise ValueError(f"contract must be one of {sorted(VALID_CONTRACTS)}")
    name = canonical_feature(name)
    context = resolve_project(root)
    base = context.path
    target = docs_dir(name, project_dir=base)
    _safe_path(target, base)
    if target.exists():
        raise FileExistsError(f"Feature directory already exists: {target}")

    rendered_files = {}
    for fname in (("WORK.md",) if contract else TEMPLATE_FILES):
        src = TEMPLATES_DIR / fname
        if not src.is_file():
            raise FileNotFoundError(f"Template missing: {src}")
        rendered_files[fname] = _render_template(src.read_text(encoding="utf-8"), name)
    target.mkdir(parents=True, exist_ok=False)
    created: list[str] = []
    for fname, rendered in rendered_files.items():
        (target / fname).write_text(rendered, encoding="utf-8")
        created.append(str((target / fname).relative_to(base)))

    return {
        "feature": name,
        "project_dir": str(base),
        "project_id": context.project_id,
        "directory": str(target),
        "created_files": created,
        "next": "Complete WORK.md and declare risk before validation." if contract else "Invoke @planner to draft the PRD.",
    }


def list_artifacts(name: str, root: str | Path | None = None) -> dict[str, Any]:
    """Return per-file metadata (agent, status, updated) for a feature."""
    name = canonical_feature(name)
    context = resolve_project(root)
    project = context.path
    target = docs_dir(name, project_dir=project)
    _safe_path(target, project)
    if not target.is_dir():
        raise FileNotFoundError(f"Feature not found: {target}")

    items: list[dict[str, Any]] = []
    for path in sorted(target.glob("*.md")):
        _safe_path(path, project)
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
    return {"feature": name, "project_dir": str(project), "project_id": context.project_id, "artifacts": items, "count": len(items)}


def _validate_file(path: Path, expected_feature: str, project: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    item = {"file": path.name, "errors": errors, "warnings": warnings, "status": None, "passed": False}
    try:
        _safe_path(path, project)
    except ValueError as exc:
        errors.append(str(exc))
        return item
    fm = frontmatter.read(path)
    if fm is None:
        errors.append("front-matter missing")
        return item
    item["status"] = fm.get("status")
    if path.name == "WORK.md":
        if not isinstance(fm.get("contract"), str) or fm["contract"] not in VALID_CONTRACTS:
            errors.append(f"contract must be one of {sorted(VALID_CONTRACTS)}")
        risk = fm.get("risk")
        if not isinstance(risk, str) or risk not in VALID_RISK:
            errors.append(f"risk must be one of {sorted(VALID_RISK)}")
        if risk == "high" and not str(fm.get("risk_reason") or "").strip():
            errors.append("risk_reason required when risk is high")
        headings = set()
        fence = None
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("```", "~~~")):
                marker = stripped[:3]
                fence = None if fence == marker else marker if fence is None else fence
            elif fence is None:
                headings.add(line.rstrip())
        for heading in WORK_SECTIONS:
            if heading not in headings:
                errors.append(f"section missing: {heading}")

    for field in ("agent", "feature", "status", "created", "updated"):
        if field not in fm or not fm[field]:
            errors.append(f"field '{field}' missing")

    if (agent := fm.get("agent")) and str(agent) not in VALID_AGENTS:
        errors.append(f"invalid agent '{agent}'")
    if (status := fm.get("status")) and str(status) not in VALID_STATUSES:
        errors.append(f"invalid status '{status}'")
    if feat := fm.get("feature"):
        try:
            actual = canonical_feature(str(feat))
        except ValueError:
            actual = None
        if actual != expected_feature:
            if len(expected_feature.split("/")) == 2 and feat == expected_feature.split("/")[1]:
                warnings.append(f"legacy bare feature name '{feat}'; canonical is '{expected_feature}'")
            else:
                errors.append(f"feature mismatch (expected '{expected_feature}', got '{feat}')")
    for dkey in ("created", "updated"):
        if (dval := fm.get(dkey)) and not DATE_RE.match(str(dval)):
            errors.append(f"{dkey} not YYYY-MM-DD: '{dval}'")

    # Forward-reference links are expected to be broken during `draft`.
    # Only enforce link integrity once a document moves to review/approved.
    if str(fm.get("status")) in {"review", "approved"}:
        links = fm.get("links") or {}
        if isinstance(links, dict):
            for key, rel in links.items():
                if not rel:
                    continue
                if error := _link_error(str(rel), project, path.parent):
                    errors.append(f"links.{key} {error}: {rel}")

    item["passed"] = not errors
    return item


def _gate_verify_command() -> str | None:
    cmd = agent_config().get("gate_verify_command")
    return cmd if isinstance(cmd, str) and cmd.strip() else None


def _git_output(project: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=project, capture_output=True, text=True,
        timeout=10, check=False,
    )
    if proc.returncode:
        # Do not expose raw Git errors, which may include local/private data.
        raise ValueError(f"git {args[0]} failed")
    return proc.stdout


def _changed_paths(project: Path, base: str | None = None) -> tuple[list[str], str | None]:
    """Inspect only this repo, including staged/untracked files on an unborn branch."""
    root = _git_output(project, "rev-parse", "--show-toplevel").strip()
    if Path(root).resolve() != project.resolve():
        raise ValueError("project must be the Git working tree root")
    comparison = None
    commands = [
        ["diff", "--name-only", "-z", "--no-renames", "--"],
        ["diff", "--cached", "--name-only", "-z", "--no-renames", "--"],
        ["ls-files", "--others", "--exclude-standard", "-z", "--"],
    ]
    if base is not None:
        if not isinstance(base, str) or not base.strip() or "\0" in base:
            raise ValueError("risk_base must be a non-empty Git revision")
        revision = _git_output(project, "rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}").strip()
        comparison = _git_output(project, "merge-base", revision, "HEAD").strip()
        # Union with pending diffs retains changes later reverted in the worktree.
        commands.append(["diff", "--name-only", "-z", "--no-renames", comparison, "HEAD", "--"])
    paths = set()
    for args in commands:
        paths.update(p for p in _git_output(project, *args).split("\0") if p)
    return sorted(paths), comparison


def _risk_report(project: Path, declared: str | None, base: str | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {
        "declared": declared, "path_hits": None, "status": "unverified",
        "scope": "branch-and-pending" if base is not None else "pending-only",
        "base_ref": base, "comparison_revision": None,
    }
    try:
        patterns = risk_rules()["paths"]
        if not patterns:
            raise ValueError("no risk path rules configured")
        paths, comparison = _changed_paths(project, base)
        # Leading **/ also matches paths directly under the repository root.
        hits = [p for p in paths if any(
            fnmatch.fnmatchcase(p, pat) or (pat.startswith("**/") and fnmatch.fnmatchcase(p, pat[3:]))
            for pat in patterns
        )]
        report.update(path_hits=hits, comparison_revision=comparison,
                      status="conflict" if declared == "low" and hits else "ok")
    except (ValueError, OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
        report["reason"] = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
    if declared is None and (base is None or "reason" not in report):
        report["status"] = "undeclared"
    return report


def gate_check(
    name: str, agent: str | None = None, verify: bool = False,
    root: str | Path | None = None, verify_profile: str | None = None,
    risk_base: str | None = None,
) -> dict[str, Any]:
    """Validate all artifacts in a feature.

    If `agent` is provided, additionally verify that the prerequisite
    outputs for that agent are present and `approved`. Items whose `name`
    starts with `fix/` or `hotfix/` use the lightweight prerequisite track
    (PRD + REVIEW) instead of the full 7-document chain; the result's
    `track` key reports which one applied.

    Explicit root selects one request's workspace. Verification uses the
    selected argv profile, or the legacy shell command. Requested but
    unavailable verification fails; policy changes are reported separately.
    """
    name = canonical_feature(name)
    context = resolve_project(root)
    project = context.path
    selected_profile = verify_profile if verify_profile is not None else context.verify_profile_id
    target = docs_dir(name, project_dir=project)
    _safe_path(target, project)
    if not target.is_dir():
        raise FileNotFoundError(f"Feature not found: {target}")

    results: list[dict[str, Any]] = []
    for path in sorted(target.glob("*.md")):
        results.append(_validate_file(path, name, project))

    artifact_passed = bool(results) and all(r["passed"] for r in results)
    passed = artifact_passed

    # Presence selects the contract even when invalid; never silently downgrade.
    work = target / "WORK.md"
    track = "work" if any(r["file"] == "WORK.md" for r in results) else (
        "light" if name.startswith(LIGHT_TRACK_PREFIXES) else "full"
    )
    prereqs = AGENT_PREREQUISITES_BY_TRACK[track]
    work_fm = {}
    if track == "work":
        _safe_path(work, project)
        work_fm = frontmatter.read(work) or {}

    # Declared risk: WORK.md on the work track, else an optional PRD field.
    declaration = work_fm
    if track != "work":
        prd = target / "PRD.md"
        try:
            _safe_path(prd, project)
        except ValueError:
            declaration = {}  # File validation already reports the unsafe path.
        else:
            declaration = frontmatter.read(prd) or {}
    declared_risk = declaration.get("risk")
    valid_risk = isinstance(declared_risk, str) and declared_risk in VALID_RISK
    risk = _risk_report(project, declared_risk if valid_risk else None, risk_base)
    if "risk" in declaration and not valid_risk:
        risk.update(status="invalid", reason="risk must be low or high")
    if declared_risk == "high" and not str(declaration.get("risk_reason") or "").strip():
        risk.update(status="invalid", reason="high risk requires risk_reason")
    if risk["status"] in {"conflict", "invalid", "unverified"}:
        passed = False

    agent_check: dict[str, Any] | None = None
    if agent:
        if agent not in prereqs:
            raise ValueError(f"Unknown agent '{agent}'")
        missing: list[str] = []
        not_approved: list[str] = []
        required_files = list(prereqs[agent])
        if declared_risk == "high" and agent in {"qa", "cicd"} and "SECURITY-AUDIT.md" not in required_files:
            required_files.append("SECURITY-AUDIT.md")
        for required in required_files:
            fpath = target / required
            if not fpath.is_file():
                missing.append(required)
                continue
            entry = next((item for item in results if item["file"] == required), {})
            if entry.get("status") != "approved":
                not_approved.append(f"{required} (status={entry.get('status')})")
        agent_check = {
            "agent": agent,
            "missing": missing,
            "not_approved": not_approved,
            "passed": not missing and not not_approved,
        }
        passed = passed and agent_check["passed"]

    result: dict[str, Any] = {
        "feature": name,
        "project_dir": str(project),
        "project_id": context.project_id,
        "verify_profile_id": selected_profile,
        "empty": not results,
        "artifact_status": "passed" if artifact_passed else "failed",
        "verification_status": None,
        "policy_status": None,
        "track": track,
        "risk": risk,
        "passed": passed,
        "files": results,
        "agent_gate": agent_check,
    }
    if verify:
        verification.run(result, project, selected_profile, agent_config(), _gate_verify_command())
    return result
