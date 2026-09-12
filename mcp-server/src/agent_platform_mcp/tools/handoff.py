"""Agent handoff validation tool."""

from __future__ import annotations

from typing import Any
from pathlib import Path

from agent_platform_mcp.config import AGENT_OUTPUTS, AGENT_OUTPUTS_BY_TRACK, VALID_AGENTS
from agent_platform_mcp.tools.feature import gate_check


def validate(
    from_agent: str, to_agent: str, feature: str,
    root: str | Path | None = None, verify: bool | None = None,
    verify_profile: str | None = None, purpose: str | None = None,
    risk_base: str | None = None,
) -> dict[str, Any]:
    """Validate plan review, completion, or rework without promoting artifacts."""
    for label, agent in (("from_agent", from_agent), ("to_agent", to_agent)):
        if agent not in VALID_AGENTS:
            raise ValueError(f"{label} '{agent}' is not a known agent")

    if purpose is None:
        purpose = "plan_review" if from_agent == "planner" and to_agent in {"reviewer", "security"} else (
            "rework" if from_agent in {"reviewer", "security", "qa"} and to_agent == "backend"
            else "implementation_complete"
        )
    if purpose not in {"plan_review", "implementation_complete", "rework"}:
        raise ValueError(f"Unknown handoff purpose: {purpose}")
    if purpose == "rework" and (from_agent not in {"reviewer", "security", "qa"} or to_agent != "backend"):
        raise ValueError("rework must hand a review/security/qa result to backend")
    if purpose == "plan_review" and from_agent != "planner":
        raise ValueError("plan_review must originate from planner")
    if verify is None:
        verify = purpose == "implementation_complete" and to_agent in {"reviewer", "security", "qa", "cicd"}
    result = gate_check(
        feature, agent=to_agent if purpose == "implementation_complete" else None,
        root=root, verify=verify, verify_profile=verify_profile, risk_base=risk_base,
    )

    required_by_source = (AGENT_OUTPUTS if purpose == "rework" else
                          AGENT_OUTPUTS_BY_TRACK[result["track"]]).get(from_agent, [])
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
        elif purpose == "rework" and found.get("status") != "rejected":
            source_errors.append(f"{artifact} must be rejected for rework")
        elif purpose == "implementation_complete" and found.get("status") != "approved":
            source_errors.append(f"{artifact} not approved (status={found.get('status')})")
        elif purpose == "plan_review" and found.get("status") == "rejected":
            source_errors.append(f"{artifact} is rejected; revise the plan first")

    passed = result["passed"] and not source_errors
    return {
        "from_agent": from_agent,
        "to_agent": to_agent,
        "feature": result["feature"],
        "project_dir": result["project_dir"],
        "project_id": result["project_id"],
        "verify_profile_id": result["verify_profile_id"],
        "purpose": purpose,
        "passed": passed,
        "artifact_status": "passed" if result["artifact_status"] == "passed" and not source_errors else "failed",
        "verification_status": result["verification_status"],
        "policy_status": result["policy_status"],
        "notes": ["Verification policy requires review before final sign-off."] if result["policy_status"] in {"changed", "unreviewed"} else [],
        "source_output_errors": source_errors,
        "gate_check": result,
        "message": (
            f"Handoff {from_agent} → {to_agent} approved."
            if passed
            else f"Handoff blocked. Resolve issues before calling @{to_agent}."
        ),
    }
