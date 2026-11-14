"""Publish a feature to the project's configured target: none, confluence or notion.

Only runs when explicitly called (`publish_feature` MCP tool / `publish` CLI); handoff,
gate and role wrappers never call it. Unset settings mean `none`, so a project that has
not chosen a target makes no remote call. Never raises: failures are {"error"} dicts.
"""

from __future__ import annotations

from typing import Any

from agent_platform_mcp.tools import confluence as confluence_tools
from agent_platform_mcp.tools import notion, projects

OK_STATUSES = frozenset({"skipped", "planned", "published"})
NO_MD = "no .md files to publish"
NO_PUBLISHABLE = "no publishable .md files"


def _result(key: str, project_id: str | None, target: str, status: str,
            reason: str | None = None, result: dict | None = None) -> dict[str, Any]:
    return {"feature": key, "project_id": project_id, "target": target, "status": status,
            "reason": reason, "result": result}


def _status(overview: dict | None, results: list[dict], overview_blocks_children: bool) -> str:
    errors = [r for r in results if r.get("status") == "error"]
    overview_failed = bool(overview) and overview.get("status") == "error"
    if overview_failed and (overview_blocks_children or len(errors) == len(results)):
        return "failed"
    return "partial" if overview_failed or errors else "published"


def _confluence(key: str, feature: str, root: str | None, project_id: str | None,
                settings: dict, feature_dir, dry_run: bool) -> dict[str, Any]:
    space_key, parent_title = settings["space_key"], settings["parent_title"]
    if dry_run:
        files, skipped = notion.feature_files(feature_dir)
        plan = confluence_tools.flow_attachment_plan(feature_dir)
        return _result(key, project_id, "confluence", "planned", result={
            "feature": feature, "space_key": space_key, "parent_title": parent_title, "dry_run": True,
            "files": [p.name for p in files], "skipped": [s["file"] for s in skipped],
            "skipped_reasons": {s["file"]: s["error"] for s in skipped},
            "attachments": [plan] if plan else []})
    result = confluence_tools.sync_feature(space_key, parent_title, feature, overview=True,
                                           attach_flow=True, root=root)
    if set(result) == {"error"}:
        return result
    if "overview" not in result and result.get("warning"):
        # sync_feature found no .md to publish: nothing went out, so not "published".
        reason = NO_PUBLISHABLE if result.get("results") else NO_MD
        return _result(key, project_id, "confluence", "skipped", reason=reason, result=result)
    # Confluence keeps a failed overview's children under the parent page, so it is partial.
    status = _status(result.get("overview"), result.get("results") or [], overview_blocks_children=False)
    return _result(key, project_id, "confluence", status, result=result)


def publish_feature(feature: str, root: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Publish `docs/<type>/<name>/` to the target set by `project-publish-set`.

    Returns PublishResult {feature, project_id, target, status, reason, result} where status is
    skipped | planned | published | partial | failed, or {"error": "..."} before any work.
    """
    located = notion.locate_feature(feature, root)
    if "error" in located:
        return located
    context, key, feature_dir = located["context"], located["key"], located["feature_dir"]
    try:
        settings = projects.get_publish(context.project_id)
    except ValueError as exc:  # InvalidSettings names the field only
        return {"error": str(exc)}
    target = (settings or {}).get("target", "none")
    if target == "none":
        return _result(key, context.project_id, "none", "skipped", reason="publish target is none")
    files, skipped = notion.feature_files(feature_dir)
    if not files:
        # Nothing publishable: skipped before any remote call, the same for dry-run (REVIEW R3-1).
        return _result(key, context.project_id, target, "skipped", reason=NO_PUBLISHABLE if skipped else NO_MD,
                       result={"feature": feature, "dry_run": dry_run,
                               "skipped": [{"file": s["file"], "error": s["error"]} for s in skipped]})
    if target == "confluence":
        return _confluence(key, feature, root, context.project_id, settings["confluence"], feature_dir, dry_run)

    result = notion.sync_feature(feature, settings["notion"]["parent_page_id"], root=root, dry_run=dry_run)
    if set(result) == {"error"}:
        return result
    if dry_run:
        return _result(key, context.project_id, "notion", "planned", result=result)
    status = _status(result["overview"], result["results"], overview_blocks_children=True)
    reason = result["overview"]["error"] if status == "failed" else None
    return _result(key, context.project_id, "notion", status, reason=reason, result=result)
