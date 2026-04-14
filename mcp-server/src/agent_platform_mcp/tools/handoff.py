"""Agent handoff validation tool."""

from __future__ import annotations

from typing import Any

from agent_platform_mcp.config import AGENT_OUTPUTS, VALID_AGENTS
from agent_platform_mcp.tools.feature import gate_check


def validate(from_agent: str, to_agent: str, feature: str) -> dict[str, Any]:
    """Verify that `from_agent`'s outputs are approved before handing off to `to_agent`."""
    for label, agent in (("from_agent", from_agent), ("to_agent", to_agent)):
        if agent not in VALID_AGENTS:
            raise ValueError(f"{label} '{agent}' is not a known agent")

    result = gate_check(feature, agent=to_agent)

    required_by_source = AGENT_OUTPUTS.get(from_agent, [])
    source_errors: list[str] = []
    for artifact in required_by_source:
        found = next(
            (f for f in result["files"] if f["file"] == artifact),
            None,
        )
        if found is None:
            source_errors.append(f"{artifact} missing (from_agent={from_agent})")
        elif found["errors"]:
            source_errors.append(f"{artifact} has validation errors")

    passed = result["passed"] and not source_errors
    return {
        "from_agent": from_agent,
        "to_agent": to_agent,
        "feature": feature,
        "passed": passed,
        "source_output_errors": source_errors,
        "gate_check": result,
        "message": (
            f"Handoff {from_agent} → {to_agent} approved."
            if passed
            else f"Handoff blocked. Resolve issues before calling @{to_agent}."
        ),
    }
