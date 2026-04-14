"""agent-platform MCP server entry point.

Phase 2 tools: feature lifecycle, handoff validation, log append.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from agent_platform_mcp.tools import audit as audit_tools
from agent_platform_mcp.tools import feature as feature_tools
from agent_platform_mcp.tools import handoff as handoff_tools
from agent_platform_mcp.tools import log as log_tools
from agent_platform_mcp.tools import qa as qa_tools
from agent_platform_mcp.tools import release as release_tools
from agent_platform_mcp.tools import review as review_tools
from agent_platform_mcp.tools import standards as standards_tools

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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
