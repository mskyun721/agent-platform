# P5 Evaluation Evidence

On 2026-09-14, revision `dfb63b4` ran five evaluator-owned tasks in fresh
temporary workspaces, three times per backend in platform instruction mode.
Claude CLI 2.1.269 and Codex CLI 0.154.0 were used. Default model identities
and global skill versions were not verified. No model superiority is claimed.

| Task | Claude passes | Codex passes |
|---|---:|---:|
| small-feature | 3/3 | 3/3 |
| seeded-bug | 3/3 | 3/3 |
| broken-test | 3/3 | 3/3 |
| api-add | 1/3 | 3/3 |
| skill-remove | 3/3 | 3/3 |

Total: 28/30. Both failures were evaluator checks after successful Claude CLI
exit, not timeouts. Failed IDs: `81ddb7ec-0c5a-4e76-923b-13ccaa447a76` and
`5179ca1d-588a-4108-925c-4ae0597a0f9a`. Raw output and candidate workspaces
were not retained, so the precise test/implementation cause is unverified.
Do not turn this result into a claim that the API task always succeeds.

`evals/baseline.json` preserves cohort counts and marks Claude API-add as a
known unstable baseline, not a passing regression guard. The other nine
cohorts are passing guards. A zero *new regression* count is not zero known
failures. This is a prospective baseline: historical P1-P4 revisions were
not rerun and no before/after improvement percentage was measured.

Numeric native usage is collected when available, but cost is unknown without
verified model/rate snapshots. Use `evals/summarize.py` for field-level missingness
and durations. Local records are ignored; the tracked baseline preserves hashes
and counts. Documentation/test edits during the final cohorts changed the dirty
flag but not the evaluator task hash or selected platform source fingerprint.

The real HTTP checks use an evaluator-owned loopback adapter, not a generated
production web server. Skill removal invokes the actual manager with isolated
registries and proves enabled removal is blocked, disable/remove succeeds, and
product source remains. Existing evidence-gate tests additionally execute actual
verification subprocesses for success, failure and stale approval cases.

Evidence/policy enforcement remains opt-in pending project-owner review. Fixture
observation is not a two-week production rollout. Profile approval and document
promotion were not fabricated by the implementing agent.
