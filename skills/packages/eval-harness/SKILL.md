---
name: eval-harness
description: Design repeatable capability and regression evaluations for agent prompts, skills or workflow changes. Use for measured before/after comparisons rather than ordinary unit-test execution.
license: MIT
metadata:
  origin: affaan-m/ECC
  upstream_commit: e482e579415fde18357cafce70f177ae19fd7f03
  adaptation: agent-platform
---

# Eval Harness

Treat behavior changes to agents as testable hypotheses. Reuse this platform's evals runner and evidence system rather than creating a competing .claude/evals store.

## Procedure

1. Define the task, success/failure criteria and unchanged regression behaviors before changing the agent instructions. Include failure cases, not only happy paths.
2. Choose graders: deterministic code/schema checks where possible, a stated model rubric for open outputs, or human adjudication for ambiguity. Keep grader definitions outside the candidate's editable workspace. This does not create an OS security boundary.
3. Fix task/judge hashes, initial fixture, model/CLI versions, instruction variants and time/retry budget. Use independent workspaces and record environmental differences.
4. Read evals/README.md and runner --help in the platform checkout. For existing supported tasks use the run_task.py setup/check or explicitly requested auto flow. Do not run costly repeated AI trials solely because this skill was selected.
5. Record actual checked results, skips, tool failures, user interventions, measured duration and available usage. Missing usage/cost stays unknown; wall time is not pure model latency.
6. Compare only compatible groups. Report success counts and denominators. pass@k means at least one success in k attempts; all-k success measures consistency. Do not relabel a retry success as first-attempt success or use three trials to claim statistical superiority.
7. Require regression evidence before recommending promotion. An agent saying it succeeded is not a grader result. Attach the candidate/target hashes so later edits invalidate the prior comparison.

## Existing platform commands

From the platform root, for already supported fixtures:
```bash
uv --directory mcp-server run python ../evals/summarize.py
uv --directory mcp-server run python ../evals/summarize.py --regress --baseline evals/baseline.json
```

The caller chooses the matching baseline. Do not compare different task/judge hashes as the same experiment. Record definitions and conclusions in the current task artifacts and runtime records in the runner's existing ignored results location. For another repository without this runner, provide the eval specification and report the unavailable execution capability.

## Platform integration

Use the current session's available tools and follow AGENTS.md, role-skills policy and authorized scope. This skill grants no additional permissions. Save outputs in the existing target task artifacts with draft status until reviewed; it does not require a new artifact for a simple answer. Log selected/used/result honestly. Both backends use this same workflow; native discovery does not prove a successful skill execution.

## Provenance

Adapted from [ECC eval-harness](https://github.com/affaan-m/ECC/tree/e482e579415fde18357cafce70f177ae19fd7f03/skills/eval-harness) under MIT; see LICENSE and skill.json for the fixed source revision and adaptation record. This package contains the platform workflow, not ECC runtime scripts.
