"""agent-platform MCP server entry point.

Phase 2 tools: feature lifecycle, handoff validation, log append.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from agent_platform_mcp.tools import audit as audit_tools
from agent_platform_mcp.tools import backend as backend_tools
from agent_platform_mcp.tools import feature as feature_tools
from agent_platform_mcp.tools import handoff as handoff_tools
from agent_platform_mcp.tools import log as log_tools
from agent_platform_mcp.tools import plan as plan_tools
from agent_platform_mcp.tools import qa as qa_tools
from agent_platform_mcp.tools import release as release_tools
from agent_platform_mcp.tools import review as review_tools
from agent_platform_mcp.tools import project as project_tools
from agent_platform_mcp.tools import standards as standards_tools
from agent_platform_mcp.tools import confluence as confluence_tools

mcp = FastMCP("agent-platform")


@mcp.tool()
def hello(name: str = "agent-platform") -> str:
    """Smoke-test tool. Returns a greeting to confirm MCP wiring."""
    return f"Hello, {name}! agent-platform MCP server is alive."


@mcp.tool()
def feature_scaffold(name: str) -> dict[str, Any]:
    """Create docs/features/<name>/ with PRD.md and TASK.md from templates.

    Fails if the directory already exists.
    """
    return feature_tools.scaffold(name)


@mcp.tool()
def feature_list_artifacts(name: str) -> dict[str, Any]:
    """List all markdown artifacts under docs/features/<name>/ with front-matter status."""
    return feature_tools.list_artifacts(name)


@mcp.tool()
def feature_gate_check(name: str, agent: str | None = None) -> dict[str, Any]:
    """Validate front-matter and links for a feature.

    If `agent` is provided, additionally verify prerequisite artifacts
    for that agent are present and `approved`.
    """
    return feature_tools.gate_check(name, agent=agent)


@mcp.tool()
def handoff_validate(from_agent: str, to_agent: str, feature: str) -> dict[str, Any]:
    """Verify that `from_agent`'s outputs are approved and ready for `to_agent`."""
    return handoff_tools.validate(from_agent, to_agent, feature)


@mcp.tool()
def log_append(
    message: str,
    agent: str | None = None,
    feature: str | None = None,
) -> dict[str, Any]:
    """Append a timestamped entry to claude_log.md."""
    return log_tools.append(message, agent=agent, feature=feature)


@mcp.tool()
def plan_run_gemini(
    feature: str,
    requirements: str,
    action: str = "all",
    dry_run: bool = False,
    timeout_sec: int = 600,
) -> dict[str, Any]:
    """Run Gemini CLI to generate PRD and/or TASK for a feature.

    feature: feature name under docs/features/ (must exist via feature_scaffold)
    requirements: raw user requirements text
    action: one of {prd, task, all}
    dry_run: if true, returns the prompt/command without invoking Gemini.
    """
    return plan_tools.run_gemini(
        feature,
        requirements=requirements,
        action=action,
        dry_run=dry_run,
        timeout_sec=timeout_sec,
    )


@mcp.tool()
def plan_run_codex(
    feature: str,
    requirements: str,
    action: str = "all",
    dry_run: bool = False,
    timeout_sec: int = 600,
) -> dict[str, Any]:
    """Run Codex CLI to generate PRD and/or TASK for a feature."""
    return plan_tools.run_codex(
        feature,
        requirements=requirements,
        action=action,
        dry_run=dry_run,
        timeout_sec=timeout_sec,
    )


@mcp.tool()
def backend_run_codex(
    feature: str,
    dry_run: bool = False,
    timeout_sec: int = 1800,
) -> dict[str, Any]:
    """Run Codex CLI to implement backend code and backend artifacts."""
    return backend_tools.run_codex(
        feature,
        dry_run=dry_run,
        timeout_sec=timeout_sec,
    )


@mcp.tool()
def backend_run_gemini(
    feature: str,
    dry_run: bool = False,
    timeout_sec: int = 1800,
) -> dict[str, Any]:
    """Run Gemini CLI to implement backend code and backend artifacts."""
    return backend_tools.run_gemini(
        feature,
        dry_run=dry_run,
        timeout_sec=timeout_sec,
    )


@mcp.tool()
def review_run_gemini(
    feature: str,
    focus: str = "all",
    dry_run: bool = False,
    timeout_sec: int = 600,
) -> dict[str, Any]:
    """Run Gemini CLI to review a feature. Writes REVIEW.md.

    focus: one of {all, security, performance, style, hexagonal}
    dry_run: if true, returns the prompt/command without invoking Gemini.
    """
    return review_tools.run_gemini(
        feature, focus=focus, dry_run=dry_run, timeout_sec=timeout_sec
    )


@mcp.tool()
def review_run_codex(
    feature: str,
    focus: str = "all",
    dry_run: bool = False,
    timeout_sec: int = 600,
) -> dict[str, Any]:
    """Run Codex CLI to review a feature. Writes REVIEW.md.

    focus: one of {all, security, performance, style, hexagonal}
    dry_run: if true, returns the prompt/command without invoking Codex.
    """
    return review_tools.run_codex(
        feature, focus=focus, dry_run=dry_run, timeout_sec=timeout_sec
    )


@mcp.tool()
def audit_run_gemini(
    feature: str,
    scope: str = "all",
    dry_run: bool = False,
    timeout_sec: int = 600,
) -> dict[str, Any]:
    """Run Gemini CLI to security-audit a feature. Writes SECURITY-AUDIT.md.

    scope: one of {all, owasp, secrets, deps}
    """
    return audit_tools.run_gemini(
        feature, scope=scope, dry_run=dry_run, timeout_sec=timeout_sec
    )


@mcp.tool()
def audit_run_codex(
    feature: str,
    scope: str = "all",
    dry_run: bool = False,
    timeout_sec: int = 600,
) -> dict[str, Any]:
    """Run Codex CLI to security-audit a feature. Writes SECURITY-AUDIT.md."""
    return audit_tools.run_codex(
        feature, scope=scope, dry_run=dry_run, timeout_sec=timeout_sec
    )


@mcp.tool()
def standards_read(kind: str, name: str) -> dict[str, Any]:
    """Read a standards/workflows/templates document by name.

    kind: one of {standards, workflows, templates}
    name: file stem, e.g. "coding-style"
    """
    return standards_tools.read(kind, name)


@mcp.tool()
def standards_list() -> dict[str, list[str]]:
    """List available documents under standards/, workflows/, templates/."""
    return standards_tools.list_available()


@mcp.tool()
def qa_run_gemini(
    feature: str,
    scope: str = "plan",
    dry_run: bool = False,
    timeout_sec: int = 900,
) -> dict[str, Any]:
    """Run Gemini CLI to perform QA work. Writes TEST-PLAN.md (and optionally test code).

    scope: one of {plan, test-gen, regression, all}
    dry_run: if true, returns the prompt/command without invoking Gemini.
    """
    return qa_tools.run_gemini(
        feature, scope=scope, dry_run=dry_run, timeout_sec=timeout_sec
    )


@mcp.tool()
def qa_run_codex(
    feature: str,
    scope: str = "plan",
    dry_run: bool = False,
    timeout_sec: int = 900,
) -> dict[str, Any]:
    """Run Codex CLI to perform QA work. Writes TEST-PLAN.md (and optionally test code).

    scope: one of {plan, test-gen, regression, all}
    """
    return qa_tools.run_codex(
        feature, scope=scope, dry_run=dry_run, timeout_sec=timeout_sec
    )


@mcp.tool()
def release_run_gemini(
    feature: str,
    action: str = "all",
    dry_run: bool = False,
    timeout_sec: int = 600,
    model: str = "gemini-2.5-flash",
) -> dict[str, Any]:
    """Run Gemini CLI to produce CICD artifacts.

    action: one of {pr-body, release-note, checklist, all}
    Writes PR-BODY.md / RELEASE-NOTE.md / DEPLOY-CHECKLIST.md under the feature dir.
    """
    return release_tools.run_gemini(
        feature, action=action, dry_run=dry_run, timeout_sec=timeout_sec, model=model
    )


@mcp.tool()
def release_run_codex(
    feature: str,
    action: str = "all",
    dry_run: bool = False,
    timeout_sec: int = 600,
) -> dict[str, Any]:
    """Run Codex CLI to produce CICD artifacts."""
    return release_tools.run_codex(
        feature, action=action, dry_run=dry_run, timeout_sec=timeout_sec
    )


@mcp.tool()
def project_init(
    project_name: str,
    package_path: str,
    language: str = "kotlin",
    java_version: int | None = None,
    kotlin_version: str | None = None,
    spring_boot_version: str | None = None,
    gradle_version: str | None = None,
    dependencies: list[str] | None = None,
    target_dir: str | None = None,
    git_commit: bool = True,
) -> dict[str, Any]:
    """Create a Spring Boot project skeleton.

    project_name: kebab-case name (e.g. my-service)
    package_path: base package (e.g. com.example.myservice)
    language: "kotlin" (default, clones springboot-kotlin-skeleton) or "java" (Spring Initializr)
    dependencies: list of Spring Initializr IDs (e.g. ["webflux", "r2dbc", "actuator"])
    target_dir: destination parent directory (default: parent of agent-platform root)
    git_commit: if true (default), runs git init + initial commit in the new project
    """
    return project_tools.init(
        project_name=project_name,
        package_path=package_path,
        language=language,
        java_version=java_version,
        kotlin_version=kotlin_version,
        spring_boot_version=spring_boot_version,
        gradle_version=gradle_version,
        dependencies=dependencies,
        target_dir=target_dir,
        git_commit=git_commit,
    )


@mcp.tool()
def confluence_fetch_page(page_id: str) -> dict[str, Any]:
    """Fetch a Confluence Cloud page by ID and return its content as markdown.

    Requires env vars: CONFLUENCE_URL, CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN.
    Returns {title, body_markdown, url, last_modified} on success,
    or {error: "..."} on failure.
    """
    return confluence_tools.fetch_page(page_id)


@mcp.tool()
def confluence_list_space(space_key: str, limit: int = 20) -> dict[str, Any]:
    """List pages in a Confluence Cloud space by space key.

    Requires env vars: CONFLUENCE_URL, CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN.
    Returns {space_key, pages: [{id, title, last_modified}]} on success,
    or {error: "..."} on failure.
    """
    return confluence_tools.list_space(space_key, limit=limit)


@mcp.tool()
def confluence_create_page(
    space_key: str,
    parent_title: str,
    title: str,
    body_markdown: str,
) -> dict[str, Any]:
    """Create a Confluence Cloud page under a given parent page.

    Converts body_markdown (Markdown text) to Confluence storage format automatically.
    Requires env vars: CONFLUENCE_URL, CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN.
    Returns {title, page_id, url} on success, or {error: "..."} on failure.
    Duplicate page titles result in an error — no overwrite.
    """
    return confluence_tools.create_page(
        space_key=space_key,
        parent_title=parent_title,
        title=title,
        body_markdown=body_markdown,
    )


@mcp.tool()
def confluence_sync_feature(
    space_key: str,
    parent_title: str,
    feature_name: str,
) -> dict[str, Any]:
    """Upload all .md files from docs/features/<feature_name>/ as Confluence pages.

    Reads from the active target project (TARGET_PROJECT_ROOT env var or .active-project file).
    Each .md file becomes a child page of parent_title in the given space.
    Returns {feature, results: [{file, status, url|error}]}.
    Partial failures are collected — all files are attempted regardless of individual errors.
    """
    return confluence_tools.sync_feature(
        space_key=space_key,
        parent_title=parent_title,
        feature_name=feature_name,
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
