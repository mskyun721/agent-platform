"""Standalone agent-platform role runner."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from agent_platform_mcp.tools import audit, backend, feature, handoff, plan, projects, qa, release, review, skill_packages, skills
from agent_platform_mcp.tools import observation, state_queries, store
from agent_platform_mcp.tools import recovery
from agent_platform_mcp.tools import continuation
from agent_platform_mcp.tools import actions as external_actions, git_remote
from agent_platform_mcp.tools import profile_review, graph, investment, quant, investment_risk

VALID_RUN_AGENTS = {"planner", "backend", "reviewer", "security", "qa", "cicd", "investment", "quant", "investment-risk"}
VALID_AI = {"auto", "codex", "claude"}


def _print_result(result: dict[str, Any]) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _run_agent(args: argparse.Namespace) -> dict[str, Any]:
    ai = args.ai
    if ai not in VALID_AI:
        raise ValueError(f"--ai must be one of {sorted(VALID_AI)}")

    if args.agent in {"investment", "quant", "investment-risk"}:
        if not args.requirements or not args.as_of:
            raise ValueError(f"--requirements and --as-of are required for {args.agent}")
        module = {"investment": investment, "quant": quant, "investment-risk": investment_risk}[args.agent]
        return module.run(args.feature, requirements=args.requirements, as_of=args.as_of,
                              cli=ai, model=args.model, dry_run=args.dry_run, timeout_sec=args.timeout_sec, root=args.root)

    if args.agent == "planner":
        if not args.requirements:
            raise ValueError("--requirements is required for planner")
        return plan.run(
            args.feature,
            requirements=args.requirements,
            action=args.action,
            cli=ai, model=args.model,
            dry_run=args.dry_run,
            timeout_sec=args.timeout_sec,
            root=args.root,
        )

    if args.agent == "backend":
        return backend.run(
            args.feature,
            cli=ai, model=args.model,
            dry_run=args.dry_run,
            timeout_sec=args.timeout_sec,
            root=args.root,
        )

    if args.agent == "reviewer":
        return review.run(
            args.feature,
            focus=args.focus,
            cli=ai, model=args.model,
            dry_run=args.dry_run,
            timeout_sec=args.timeout_sec,
            root=args.root,
        )

    if args.agent == "security":
        return audit.run(
            args.feature,
            scope=args.scope,
            cli=ai, model=args.model,
            dry_run=args.dry_run,
            timeout_sec=args.timeout_sec,
            root=args.root,
        )

    if args.agent == "qa":
        return qa.run(
            args.feature,
            scope=args.scope,
            cli=ai, model=args.model,
            dry_run=args.dry_run,
            timeout_sec=args.timeout_sec,
            root=args.root,
        )

    if args.agent == "cicd":
        return release.run(
            args.feature,
            action=args.action,
            cli=ai, model=args.model,
            dry_run=args.dry_run,
            timeout_sec=args.timeout_sec,
            root=args.root,
        )

    raise ValueError(f"Unknown agent: {args.agent}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-platform-agent",
        description="Run roles through the selected Claude Code or Codex backend.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    observe = subparsers.add_parser('observe', help='Local LLM observability viewer and opt-in content')
    observe_actions = observe.add_subparsers(dest='observe_action', required=True)
    observe_actions.add_parser('serve').add_argument('--port', type=int, default=8765)
    capture = observe_actions.add_parser('capture')
    capture.add_argument('mode', choices=['on', 'off'])
    capture.add_argument('--root', required=True)
    observe_actions.add_parser('purge-content')
    observe_actions.add_parser('record', help='Explicit prompt/response JSON from stdin for an existing run').add_argument('--run-id', required=True)
    observe_actions.add_parser('status').add_argument('--root', required=True)
    observe_actions.add_parser('efficiency', help='Bounded token usage summary without inferred savings').add_argument('--root', required=True)
    subparsers.add_parser('doctor', help='Diagnose configuration and collection without executing hooks').add_argument('--root', required=True)
    feedback = subparsers.add_parser('feedback', help='Explicit project-scoped feedback')
    feedback_actions = feedback.add_subparsers(dest='feedback_action', required=True)
    for action in ('add', 'list', 'show', 'purge'):
        command = feedback_actions.add_parser(action)
        command.add_argument('--root', required=True)
        if action == 'add':
            command.add_argument('--source-kind', choices=['manual','platform_run','native_turn'], required=True)
            command.add_argument('--source-id')
            command.add_argument('--kind', choices=['correction','failure','suggestion'], required=True)
        elif action == 'show':
            command.add_argument('feedback_id')
    improvement = subparsers.add_parser('improvement', help='Reviewed, evaluation-bound instruction improvements')
    improvement_actions = improvement.add_subparsers(dest='improvement_action', required=True)
    for action in ('propose', 'list', 'show', 'evaluate', 'review', 'apply', 'revert'):
        command = improvement_actions.add_parser(action)
        command.add_argument('--root', required=True)
        if action == 'propose':
            command.add_argument('--feedback', required=True)
        elif action != 'list':
            command.add_argument('candidate_id')
        if action == 'evaluate':
            command.add_argument('--baseline', nargs='+', required=True)
            command.add_argument('--candidate', nargs='+', required=True)
        if action == 'review':
            command.add_argument('--decision', choices=['approved','rejected'], required=True)
            command.add_argument('--reviewer', required=True)
        if action in ('apply','revert'):
            command.add_argument('--dry-run', action='store_true')
    route = subparsers.add_parser('route', help='Preview role backend/model selection without execution')
    route.add_argument('role', choices=sorted(VALID_RUN_AGENTS))
    route.add_argument('--root', required=True)
    route.add_argument('--ai', choices=sorted(VALID_AI), default='auto')
    route.add_argument('--model')
    graph_parser = subparsers.add_parser("graph", help="Read-only graph health and impact candidates")
    graph_actions = graph_parser.add_subparsers(dest="graph_action", required=True)
    graph_status = graph_actions.add_parser("status")
    graph_status.add_argument("--root", help="Project path or registered project_id")
    graph_impact = graph_actions.add_parser("impact")
    graph_impact.add_argument("paths", nargs="+", help="Changed project-relative source paths")
    graph_impact.add_argument("--root", help="Project path or registered project_id")
    graph_impact.add_argument("--depth", type=int, default=3)
    graph_impact.add_argument("--limit", type=int, default=100)
    profile = subparsers.add_parser("verify-profile", help="Record explicit operator review of a verification profile")
    profile_actions = profile.add_subparsers(dest="profile_action", required=True)
    approve = profile_actions.add_parser("approve")
    approve.add_argument("profile_id")
    approve.add_argument("--reviewer", required=True)

    state = subparsers.add_parser("state", help="Local observation lifecycle and queries")
    state_actions = state.add_subparsers(dest="state_action", required=True)
    action_list = state_actions.add_parser("actions")
    action_list.add_argument("--run-id")
    action_plan = state_actions.add_parser("action-plan")
    action_plan.add_argument("run_id")
    action_plan.add_argument("kind", choices=sorted(external_actions.KINDS))
    action_plan.add_argument("key")
    action_plan.add_argument("--target-json", required=True)
    action_confirm = state_actions.add_parser("action-confirm")
    action_confirm.add_argument("action_id")
    action_confirm.add_argument("--confirmed-by", required=True)
    for action in ("action-execute", "action-reconcile"):
        state_actions.add_parser(action).add_argument("action_id")
    start = state_actions.add_parser("start")
    start.add_argument("task_id")
    start.add_argument("--role", required=True)
    start.add_argument("--backend")
    start.add_argument("--model")
    start.add_argument("--root")
    end = state_actions.add_parser("end")
    end.add_argument("run_id")
    end.add_argument("outcome", choices=["completed", "failed", "interrupted", "cancelled"])
    checkpoint = state_actions.add_parser("checkpoint")
    checkpoint.add_argument("run_id")
    checkpoint.add_argument("--phase", required=True)
    checkpoint.add_argument("--next-action", required=True)
    for name in ("decisions", "unresolved", "verification", "artifacts"):
        checkpoint.add_argument("--" + name, action="append", default=[])
    resume = state_actions.add_parser("resume")
    resume.add_argument("run_id")
    continued = state_actions.add_parser("continue")
    continued.add_argument("run_id")
    continued.add_argument("--pid", required=True, type=int)
    pulse = state_actions.add_parser("heartbeat")
    pulse.add_argument("run_id")
    pulse.add_argument("--pid", required=True, type=int)
    transition = state_actions.add_parser("transition")
    transition.add_argument("run_id")
    transition.add_argument("state", choices=list(recovery.TRANSITIONS))
    transition.add_argument("--reason")
    runs = state_actions.add_parser("runs")
    runs.add_argument("--project-id")
    runs.add_argument("--since")
    status = state_actions.add_parser("review-status")
    status.add_argument("task_id")
    status.add_argument("--project-id", required=True)
    status.add_argument("--threshold", type=int, default=3)
    decision = state_actions.add_parser("review-record")
    decision.add_argument("task_id")
    for name in ("role", "decision", "artifact", "code-fingerprint", "reviewer-id", "decision-id"):
        decision.add_argument("--" + name, required=True)
    decision.add_argument("--root")
    decision.add_argument("--run-id")
    usage = state_actions.add_parser("usage")
    usage.add_argument("--project-id")
    usage.add_argument("--since")
    state_actions.add_parser("export").add_argument("--out", required=True)
    state_actions.add_parser("import").add_argument("path")
    prune = state_actions.add_parser("prune")
    prune.add_argument("--before")
    prune.add_argument("--retention-days", type=int, default=180)

    skill = subparsers.add_parser("skill", help="Manage local skill packages")
    actions = skill.add_subparsers(dest="skill_action", required=True)
    actions.add_parser("add").add_argument("path")
    actions.add_parser("remove").add_argument("skill_id")
    actions.add_parser("list").add_argument("--project-id")
    for action in ("enable", "disable"):
        command = actions.add_parser(action)
        command.add_argument("skill_id")
        command.add_argument("project_id")

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
    gate_check.add_argument("--evidence", action="store_true")

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
    transfer.add_argument("--evidence", action="store_true")

    run_parser = subparsers.add_parser("run", help="Run a role with Claude Code or Codex")
    run_parser.add_argument("agent", choices=sorted(VALID_RUN_AGENTS))
    run_parser.add_argument("feature")
    run_parser.add_argument("--model", help="Explicit model for the selected backend")
    run_parser.add_argument("--ai", choices=sorted(VALID_AI), default="auto")
    run_parser.add_argument("--requirements")
    run_parser.add_argument("--as-of", help="Investment research cutoff date (YYYY-MM-DD)")
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
        if args.command == 'route':
            from agent_platform_mcp.tools import routing
            _print_result(routing.resolve(args.role, projects.resolve(args.root), args.ai, args.model))
            return 0
        if args.command == 'improvement':
            from agent_platform_mcp.tools import improvements
            action = args.improvement_action
            if action == 'propose':
                raw = sys.stdin.read(400001)
                if len(raw) > 400000:
                    raise ValueError('candidate JSON too large')
                body = json.loads(raw)
                if not isinstance(body, dict) or set(body) != {'trigger','action','target','replacement'}:
                    raise ValueError('provide trigger, action, target and replacement JSON fields')
                result = improvements.propose(args.root,args.feedback,**body)
            elif action == 'list':
                result = improvements.list_candidates(args.root)
            elif action == 'evaluate':
                result = improvements.evaluate(args.root,args.candidate_id,args.baseline,args.candidate)
            elif action == 'review':
                result = improvements.review(args.root,args.candidate_id,args.decision,args.reviewer)
            elif action in ('apply','revert'):
                result = getattr(improvements,action)(args.root,args.candidate_id,args.dry_run)
            else:
                result = improvements.show(args.root,args.candidate_id)
            _print_result(result)
            return 1 if action == 'evaluate' and not result['evaluation']['passed'] else 0
        if args.command == 'doctor':
            from agent_platform_mcp.tools import doctor
            _print_result(doctor.diagnose(args.root))
            return 0
        if args.command == 'feedback':
            from agent_platform_mcp.tools import learning
            if args.feedback_action == 'add':
                raw = sys.stdin.read(16001)
                if len(raw) > 16000:
                    raise ValueError('feedback JSON exceeds 16000 characters')
                body = json.loads(raw)
                if not isinstance(body, dict) or set(body) != {'summary'}:
                    raise ValueError('provide a JSON object with only summary')
                result = learning.add(args.root, args.source_kind, args.source_id, args.kind, body['summary'])
            elif args.feedback_action == 'show':
                result = learning.show(args.root, args.feedback_id)
            elif args.feedback_action == 'purge':
                result = learning.purge(args.root)
            else:
                result = learning.list_feedback(args.root)
            _print_result(result)
            return 0
        if args.command == 'observe':
            from agent_platform_mcp.tools import llm_view
            if args.observe_action == 'efficiency':
                from agent_platform_mcp.tools import usage_efficiency
                _print_result(usage_efficiency.report(args.root))
            elif args.observe_action == 'serve':
                llm_view.serve(args.port)
            elif args.observe_action == 'status':
                from agent_platform_mcp.tools import doctor
                _print_result(doctor.observation_status(args.root))
            elif args.observe_action == 'capture':
                _print_result(llm_view.configure(args.root, args.mode == 'on'))
            elif args.observe_action == 'record':
                raw = sys.stdin.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise ValueError('content input exceeds 1 MiB characters')
                content = json.loads(raw)
                if not isinstance(content, dict) or not content or set(content) - {'prompt', 'response'}:
                    raise ValueError('provide prompt and/or response JSON text fields')
                _print_result(llm_view.record(args.run_id, **content))
            else:
                _print_result(llm_view.purge())
            return 0
        if args.command == "graph":
            result = graph.status(args.root) if args.graph_action == "status" else graph.impact(
                args.paths, args.root, args.depth, args.limit)
            _print_result(result)
            return 0
        if args.command == "verify-profile":
            _print_result(profile_review.approve(args.profile_id, args.reviewer))
            return 0
        if args.command == "state":
            if args.state_action == "actions":
                result = {"actions": external_actions.list_actions(args.run_id)}
            elif args.state_action == "action-plan":
                target = git_remote.GitRemote().prepare(args.run_id, args.kind, json.loads(args.target_json))
                result = external_actions.plan(args.run_id, args.kind, args.key, target)
            elif args.state_action == "action-confirm":
                result = external_actions.confirm(args.action_id, args.confirmed_by)
            elif args.state_action == "action-execute":
                result = external_actions.execute(args.action_id, git_remote.GitRemote())
            elif args.state_action == "action-reconcile":
                result = external_actions.reconcile(args.action_id, git_remote.GitRemote())
            elif args.state_action == "checkpoint":
                result = recovery.checkpoint(args.run_id, args.phase, args.next_action, args.decisions,
                                             args.unresolved, args.verification, args.artifacts)
            elif args.state_action == "resume":
                result = recovery.resume(args.run_id)
            elif args.state_action == "continue":
                result = continuation.claim(args.run_id, args.pid)
            elif args.state_action == "heartbeat":
                result = recovery.heartbeat(args.run_id, args.pid)
            elif args.state_action == "transition":
                result = recovery.transition(args.run_id, args.state, args.reason)
            elif args.state_action == "usage":
                result = state_queries.usage_summary(args.project_id, args.since)
            elif args.state_action == "export":
                result = state_queries.export_file(args.out)
            elif args.state_action == "import":
                result = state_queries.import_file(args.path)
            elif args.state_action == "prune":
                result = state_queries.prune(args.before, args.retention_days)
            elif args.state_action == "start":
                result = observation.run_start(args.task_id, args.role, args.backend, args.model, args.root)
            elif args.state_action == "end":
                result = observation.run_end(args.run_id, args.outcome)
            elif args.state_action == "review-record":
                result = observation.review_result_record(args.task_id, args.role, args.decision, args.artifact,
                    args.code_fingerprint, args.reviewer_id, args.decision_id, args.root, args.run_id)
            else:
                with store.open() as db:
                    result = ({"runs": db.runs(args.project_id, args.since)} if args.state_action == "runs"
                              else db.review_status(args.project_id, args.task_id, args.threshold))
            _print_result(result)
            return 1 if result.get("observability", {}).get("stored") is False else 0
        if args.command == "skill":
            if args.skill_action == "add":
                result = skill_packages.add(args.path)
            elif args.skill_action == "remove":
                result = skill_packages.remove(args.skill_id)
            elif args.skill_action in {"enable", "disable"}:
                result = getattr(skills, args.skill_action)(args.skill_id, args.project_id)
            else:
                result = skills.list_skills(args.project_id)
            _print_result(result)
            return 0
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
                                        root=args.root, verify_profile=args.verify_profile, risk_base=args.risk_base, evidence=args.evidence)
            _print_result(result)
            return 0 if result["passed"] else 1
        if args.command == "list-artifacts":
            _print_result(feature.list_artifacts(args.feature, root=args.root))
            return 0
        if args.command == "handoff":
            result = handoff.validate(args.from_agent, args.to_agent, args.feature,
                                     root=args.root, purpose=args.purpose, verify=args.verify,
                                     verify_profile=args.verify_profile, risk_base=args.risk_base, evidence=args.evidence)
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
