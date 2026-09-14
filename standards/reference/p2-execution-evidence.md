# P2 Independent CLI Smoke Evidence

Date: 2026-09-14. Platform revision: `d3feffb9b0b57fdd41cfdc7a792f2c2dd7814e37`.
Tracked platform state was clean at setup.

## Method

- Prepared `seeded-bug` twice with `evals/run_task.py setup --instructions platform` in separate temporary workspaces outside the platform and active service.
- Each CLI received the same explicit platform AGENTS.md and canonical backend role text, plus fixture constraints: only fix `calc/__init__.py`, keep tests unchanged, run pytest, no delegation, no credentials, no platform/service edits, no commit/push, no documentation required for this isolated task.
- These were independent noninteractive CLI executions, not interactive UI sessions or calls through the platform's role wrappers. Native skill discovery and all-role parity were not tested.
- Claude used print mode, safe-mode, strict MCP configuration, no session persistence, and only Read/Edit/Bash tools. Its allowed shell command was the existing platform virtualenv's Python running `-m pytest -q`.
- Codex used `exec --sandbox workspace-write --skip-git-repo-check`. No permission-bypass flag was used.
- The initial parent-sandbox attempts failed (Claude authentication error; Codex runtime permission error). Both were retried with explicit execution approval. Successful process exit codes were 0.
- No human or supervising agent modified fixture source or tests. Operational retry approvals are recorded here, not counted as task/source interventions.
- The evaluator ran independently afterward, checking arithmetic behavior and unchanged tests. Pytest was also rerun directly in both workspaces.

## Results

| Backend | CLI version | Run ID | Evaluator | Pytest |
|---|---|---|---|---|
| Claude | 2.1.269 | `cd747dd3-af79-4fff-b903-a2ecb5192a23` | passed | 2 passed |
| Codex | 0.154.0 | `1cf88918-6840-49c4-95e3-4ad0377ac374` | passed | 2 passed |

Both fixed subtraction to `return a - b`; original tests remained unchanged.
Task hash: `c73e4003e0c7b4e3c7010233604125277f1e85915bfc2ff385b7136858024897`.
Platform source fingerprint: `023ee12f7d95a64715a5c993dbcc7d953b3f693938e62e6b487abaf124008ded`.
Local structured evidence remains in ignored `evals/results/<run-id>.json`.
Historical `not_run` records were preserved; these are new `checked/passed` records, not overwritten history.

Model identity and usage were not collected and remain null, not zero.
Raw stdout/stderr was captured transiently for exit classification and was not retained by the evaluator.
Native CLI runtime storage follows each CLI's own behavior; the evaluator does not claim to disable it globally.
Session wall time includes approval/idle time and is not model latency. Do not compare speed from it.

This satisfies the small independent-execution smoke criterion, not model superiority,
production readiness, full platform completion, or verified native skill support.
Repository regression verification: 216 tests and 110 subtests passed; generated Claude role adapter check passed.
