"""agent-platform MCP server entry point.

Phase 2 tools: feature lifecycle, handoff validation.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from agent_platform_mcp.tools import audit as audit_tools
from agent_platform_mcp.tools import backend as backend_tools
from agent_platform_mcp.tools import feature as feature_tools
from agent_platform_mcp.tools import handoff as handoff_tools
from agent_platform_mcp.tools import plan as plan_tools
from agent_platform_mcp.tools import qa as qa_tools
from agent_platform_mcp.tools import release as release_tools
from agent_platform_mcp.tools import review as review_tools
from agent_platform_mcp.tools import project as project_tools
from agent_platform_mcp.tools import standards as standards_tools
from agent_platform_mcp.tools import confluence as confluence_tools
from agent_platform_mcp.tools import apidog as apidog_tools

mcp = FastMCP("agent-platform")


@mcp.tool()
def hello(name: str = "agent-platform") -> str:
    """Smoke-test tool. Returns a greeting to confirm MCP wiring."""
    return f"Hello, {name}! agent-platform MCP server is alive."


@mcp.tool()
def feature_scaffold(name: str, root: str | None = None, contract: str | None = None) -> dict[str, Any]:
    """Create docs/<type>/<name>/ with PRD.md and TASK.md from templates.

    `name` may include a `<type>/` prefix (e.g. "fix/login-bug" ->
    docs/fix/login-bug); a bare name defaults to docs/features/<name>.
    Fails if the directory already exists.
    """
    return feature_tools.scaffold(name, root=root, contract=contract)


@mcp.tool()
def feature_list_artifacts(name: str, root: str | None = None) -> dict[str, Any]:
    """List all markdown artifacts under docs/<type>/<name>/ with front-matter status."""
    return feature_tools.list_artifacts(name, root=root)


@mcp.tool()
def feature_gate_check(
    name: str, agent: str | None = None, verify: bool = False,
    root: str | None = None, verify_profile: str | None = None,
    risk_base: str | None = None,
) -> dict[str, Any]:
    """Validate front-matter and links for a feature.

    If `agent` is provided, additionally verify prerequisite artifacts
    for that agent are present and `approved`. Items whose `name` starts
    with `fix/` or `hotfix/` use a lightweight prerequisite track (PRD +
    REVIEW); the result's `track` key reports `"full"` or `"light"`.
    Explicit root selects the project without mutating the active project.
    If verify is True, run verify_profile (argv) or the legacy shell command.
    A missing profile or execution error fails verification. Policy changes
    are advisory in P0. Raw build output is omitted.
    """
    return feature_tools.gate_check(name, agent=agent, verify=verify, root=root, verify_profile=verify_profile, risk_base=risk_base)


@mcp.tool()
def handoff_validate(
    from_agent: str, to_agent: str, feature: str,
    root: str | None = None, verify: bool | None = None,
    verify_profile: str | None = None, purpose: str | None = None,
    risk_base: str | None = None,
) -> dict[str, Any]:
    """Validate plan_review, implementation_complete or rejected-result rework.

    Explicit root does not mutate the active project. Verification defaults
    to completion handoffs into review/security/qa/cicd; profiles are explicit.
    Policy changes are advisory in P0, not independent approval evidence.
    """
    return handoff_tools.validate(
        from_agent, to_agent, feature, root=root, verify=verify,
        verify_profile=verify_profile, purpose=purpose, risk_base=risk_base,
    )


@mcp.tool()
def plan_run(
    feature: str,
    requirements: str,
    action: str = "all",
    cli: str = "auto",
    dry_run: bool = False,
    timeout_sec: int = 600,
) -> dict[str, Any]:
    """Generate PRD and/or TASK drafts via external CLI.

    cli: one of {auto, codex}; auto uses .agent-config.json preferred_cli.
    action: one of {prd, task, all}. dry_run returns prompt/command only.
    """
    return plan_tools.run(
        feature,
        requirements=requirements,
        action=action,
        cli=cli,
        dry_run=dry_run,
        timeout_sec=timeout_sec,
    )


@mcp.tool()
def backend_run(
    feature: str,
    cli: str = "auto",
    dry_run: bool = False,
    timeout_sec: int = 1800,
) -> dict[str, Any]:
    """Implement backend code and artifacts via external CLI (cli: auto|codex)."""
    return backend_tools.run(feature, cli=cli, dry_run=dry_run, timeout_sec=timeout_sec)


@mcp.tool()
def review_run(
    feature: str,
    focus: str = "all",
    cli: str = "auto",
    dry_run: bool = False,
    timeout_sec: int = 600,
) -> dict[str, Any]:
    """Review a feature via external CLI; writes REVIEW.md.

    focus: one of {all, security, performance, style, hexagonal}.
    cli: one of {auto, codex}; auto uses .agent-config.json preferred_cli.
    """
    return review_tools.run(feature, focus=focus, cli=cli, dry_run=dry_run, timeout_sec=timeout_sec)


@mcp.tool()
def audit_run(
    feature: str,
    scope: str = "all",
    cli: str = "auto",
    dry_run: bool = False,
    timeout_sec: int = 600,
) -> dict[str, Any]:
    """Security-audit a feature via external CLI; writes SECURITY-AUDIT.md (scope: all|owasp|secrets|deps)."""
    return audit_tools.run(feature, scope=scope, cli=cli, dry_run=dry_run, timeout_sec=timeout_sec)


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
def qa_run(
    feature: str,
    scope: str = "plan",
    cli: str = "auto",
    dry_run: bool = False,
    timeout_sec: int = 600,
) -> dict[str, Any]:
    """Run QA work via external CLI; writes TEST-PLAN.md drafts."""
    return qa_tools.run(feature, scope=scope, cli=cli, dry_run=dry_run, timeout_sec=timeout_sec)


@mcp.tool()
def release_run(
    feature: str,
    action: str = "all",
    cli: str = "auto",
    model: str | None = None,
    dry_run: bool = False,
    timeout_sec: int = 600,
) -> dict[str, Any]:
    """Produce CICD artifacts via external CLI (action: pr-body|release-note|checklist|all)."""
    return release_tools.run(
        feature, action=action, cli=cli, model=model, dry_run=dry_run, timeout_sec=timeout_sec
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
    """Upload all .md files from docs/<type>/<feature_name>/ as Confluence pages.

    `feature_name` may include a `<type>/` prefix (e.g. "fix/login-bug" ->
    docs/fix/login-bug); a bare name defaults to docs/features/<feature_name>.
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


@mcp.tool()
def apidog_list_endpoints(project_id: str) -> dict[str, Any]:
    """List all API endpoints from an API Dog project (summarized).

    Requires env var: APIDOG_API_TOKEN.
    Returns {project_id, title, version, endpoints_count,
             endpoints: [{method, path, summary, operation_id, tags}]}
    or {error: "..."} on failure.
    """
    return apidog_tools.list_endpoints(project_id)


@mcp.tool()
def apidog_export_openapi(project_id: str) -> dict[str, Any]:
    """Export full OpenAPI 3.0 spec from an API Dog project.

    Requires env var: APIDOG_API_TOKEN.
    Returns {project_id, openapi_version, title, version, endpoints_count, spec}
    or {error: "..."} on failure.
    """
    return apidog_tools.export_openapi(project_id)


@mcp.tool()
def apidog_fetch_endpoint_detail(
    project_id: str,
    path: str,
    method: str,
) -> dict[str, Any]:
    """Fetch full request/response detail for a single endpoint from an API Dog project.

    Requires env var: APIDOG_API_TOKEN.
    Returns {method, path, summary, description, parameters, request_body, responses}
    or {error: "..."} on failure.
    """
    return apidog_tools.fetch_endpoint_detail(project_id, path=path, method=method)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
