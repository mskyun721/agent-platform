"""Standalone agent-platform runner for Codex and Gemini."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from agent_platform_mcp.tools import audit, backend, feature, plan, qa, release, review

VALID_RUN_AGENTS = {"planner", "backend", "reviewer", "security", "qa", "cicd"}
VALID_AI = {"codex", "gemini"}


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
        )

    if args.agent == "backend":
        return backend.run(
            args.feature,
            cli=ai,
            dry_run=args.dry_run,
            timeout_sec=args.timeout_sec,
        )

    if args.agent == "reviewer":
        return review.run(
            args.feature,
            focus=args.focus,
            cli=ai,
            dry_run=args.dry_run,
            timeout_sec=args.timeout_sec,
        )

    if args.agent == "security":
        return audit.run(
            args.feature,
            scope=args.scope,
            cli=ai,
            dry_run=args.dry_run,
            timeout_sec=args.timeout_sec,
        )

    if args.agent == "qa":
        return qa.run(
            args.feature,
            scope=args.scope,
            cli=ai,
            dry_run=args.dry_run,
            timeout_sec=args.timeout_sec,
        )

    if args.agent == "cicd":
        return release.run(
            args.feature,
            action=args.action,
            cli=ai,
            dry_run=args.dry_run,
            timeout_sec=args.timeout_sec,
        )

    raise ValueError(f"Unknown agent: {args.agent}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-platform-agent",
        description="Run agent-platform agents without Claude Code.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    new_feature = subparsers.add_parser("new-feature", help="Scaffold feature artifacts")
    new_feature.add_argument("feature")

    gate_check = subparsers.add_parser("gate-check", help="Validate feature artifacts")
    gate_check.add_argument("feature")
    gate_check.add_argument("--agent", choices=sorted(VALID_RUN_AGENTS))

    run_parser = subparsers.add_parser("run", help="Run an agent with Codex or Gemini")
    run_parser.add_argument("agent", choices=sorted(VALID_RUN_AGENTS))
    run_parser.add_argument("feature")
    run_parser.add_argument("--ai", choices=sorted(VALID_AI), default="codex")
    run_parser.add_argument("--requirements")
    run_parser.add_argument("--action", default="all")
    run_parser.add_argument("--scope", default="all")
    run_parser.add_argument("--focus", default="all")
    run_parser.add_argument("--timeout-sec", type=int, default=900)
    run_parser.add_argument("--dry-run", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "new-feature":
            _print_result(feature.scaffold(args.feature))
            return 0
        if args.command == "gate-check":
            _print_result(feature.gate_check(args.feature, agent=args.agent))
            return 0
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
