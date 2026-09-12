"""Standalone agent-platform runner for Codex."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from agent_platform_mcp.tools import audit, backend, feature, handoff, plan, projects, qa, release, review

VALID_RUN_AGENTS = {"planner", "backend", "reviewer", "security", "qa", "cicd"}
VALID_AI = {"codex"}


def _print_result(result: dict[str, Any]) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _run_agent(args: argparse.Namespace) -> dict[str, Any]:
    ai = args.ai
    if ai not in VALID_AI:
        raise ValueError(f"--ai must be one of {sorted(VALID_AI)}")

    if args.agent == "planner":
        if not args.requirements:
            raise ValueError("--requirements is required for planner")
        return plan.run(
            args.feature,
            requirements=args.requirements,
            action=args.action,
            cli=ai,
            dry_run=args.dry_run,
            timeout_sec=args.timeout_sec,
            root=args.root,
        )

    if args.agent == "backend":
        return backend.run(
            args.feature,
            cli=ai,
            dry_run=args.dry_run,
            timeout_sec=args.timeout_sec,
            root=args.root,
        )

    if args.agent == "reviewer":
        return review.run(
            args.feature,
            focus=args.focus,
            cli=ai,
            dry_run=args.dry_run,
            timeout_sec=args.timeout_sec,
            root=args.root,
        )

    if args.agent == "security":
        return audit.run(
            args.feature,
            scope=args.scope,
            cli=ai,
            dry_run=args.dry_run,
            timeout_sec=args.timeout_sec,
            root=args.root,
        )

    if args.agent == "qa":
        return qa.run(
            args.feature,
            scope=args.scope,
            cli=ai,
            dry_run=args.dry_run,
            timeout_sec=args.timeout_sec,
            root=args.root,
        )

    if args.agent == "cicd":
        return release.run(
            args.feature,
            action=args.action,
            cli=ai,
            dry_run=args.dry_run,
            timeout_sec=args.timeout_sec,
            root=args.root,
        )

    raise ValueError(f"Unknown agent: {args.agent}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-platform-agent",
        description="Run agent-platform agents without Claude Code.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    registration = subparsers.add_parser("project-register", help="Register a stable local project identity")
    registration.add_argument("path")
    registration.add_argument("--project-id")
    registration.add_argument("--verify-profile")
    subparsers.add_parser("project-list", help="List registered projects")
    rebinding = subparsers.add_parser("project-rebind", help="Rebind an identity after moving a project")
    rebinding.add_argument("project_id")
    rebinding.add_argument("path")
    removal = subparsers.add_parser("project-unregister", help="Remove a registry entry without deleting project files")
    removal.add_argument("project_id")

    new_feature = subparsers.add_parser("new-feature", help="Scaffold feature artifacts")
    new_feature.add_argument("feature")
    new_feature.add_argument("--root")
    new_feature.add_argument("--contract", choices=["work-v1"])

    gate_check = subparsers.add_parser("gate-check", help="Validate feature artifacts")
    gate_check.add_argument("feature")
    gate_check.add_argument("--agent", choices=sorted(VALID_RUN_AGENTS))
    gate_check.add_argument("--root")
    gate_check.add_argument("--verify", action="store_true")
    gate_check.add_argument("--verify-profile")
    gate_check.add_argument("--risk-base", help="Compare committed changes from the merge base, plus pending changes")

    listing = subparsers.add_parser("list-artifacts", help="List feature artifacts")
    listing.add_argument("feature")
    listing.add_argument("--root")
    transfer = subparsers.add_parser("handoff", help="Validate a handoff")
    transfer.add_argument("from_agent", choices=sorted(VALID_RUN_AGENTS))
    transfer.add_argument("to_agent", choices=sorted(VALID_RUN_AGENTS))
    transfer.add_argument("feature")
    transfer.add_argument("--root")
    transfer.add_argument("--purpose", choices=["plan_review", "implementation_complete", "rework"])
    transfer.add_argument("--verify", action=argparse.BooleanOptionalAction, default=None)
    transfer.add_argument("--verify-profile")
    transfer.add_argument("--risk-base")

    run_parser = subparsers.add_parser("run", help="Run an agent with Codex")
    run_parser.add_argument("agent", choices=sorted(VALID_RUN_AGENTS))
    run_parser.add_argument("feature")
    run_parser.add_argument("--ai", choices=sorted(VALID_AI), default="codex")
    run_parser.add_argument("--requirements")
    run_parser.add_argument("--action", default="all")
    run_parser.add_argument("--scope", default="all")
    run_parser.add_argument("--focus", default="all")
    run_parser.add_argument("--timeout-sec", type=int, default=900)
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--root", help="Project path or registered project_id")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "project-register":
            _print_result(projects.register(args.path, args.project_id, args.verify_profile))
            return 0
        if args.command == "project-list":
            _print_result(projects.list_projects())
            return 0
        if args.command == "project-rebind":
            _print_result(projects.rebind(args.project_id, args.path))
            return 0
        if args.command == "project-unregister":
            _print_result(projects.unregister(args.project_id))
            return 0
        if args.command == "new-feature":
            _print_result(feature.scaffold(args.feature, root=args.root, contract=args.contract))
            return 0
        if args.command == "gate-check":
            result = feature.gate_check(args.feature, agent=args.agent, verify=args.verify,
                                        root=args.root, verify_profile=args.verify_profile, risk_base=args.risk_base)
            _print_result(result)
            return 0 if result["passed"] else 1
        if args.command == "list-artifacts":
            _print_result(feature.list_artifacts(args.feature, root=args.root))
            return 0
        if args.command == "handoff":
            result = handoff.validate(args.from_agent, args.to_agent, args.feature,
                                     root=args.root, purpose=args.purpose, verify=args.verify,
                                     verify_profile=args.verify_profile, risk_base=args.risk_base)
            _print_result(result)
            return 0 if result["passed"] else 1
        if args.command == "run":
            _print_result(_run_agent(args))
            return 0
    except Exception as exc:  # pragma: no cover - CLI boundary
        print(f"agent-platform-agent: error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
