# Evolution Validation Closeout

The 2026-09-15 follow-up fixes these bounded review findings:

| Fix | Regression proof |
|---|---|
| Preserve PID ownership on duplicate running transition | tests/test_recovery.py |
| Include process execution/observation/context/parser modules in verifier identity | tests/test_profile_review.py |
| Mutate qualified/aliased function calls | tests/test_evals_auto.py |
| Accept valid pytest/explicit exception assertions without syntax-only gates | tests/test_evals_auto.py |

Judge v4 retains behavior and mutation checks; an empty exception test still fails.
v2 records remain historical. v3 completed 26 of 30 requested evaluations: 23
passed, one test-contract failure and two five-minute budget failures. Its two
incomplete cohorts are not three-trial samples. v4 results must be reported with
their own task hashes; do not claim statistical improvement across changed criteria.

## Verified V4 Result

At revision 76f7755, all five tasks passed three trials on each backend: 30/30.
Claude CLI 2.1.269 and Codex CLI 0.154.0 used platform instructions in fresh
temporary workspaces, with eight minutes per task/backend combination. Model
identities were not independently verified. Each record has native usage, but
cost remains unknown without verified model/rate snapshots.

`evals/baseline.json` is the new prospective baseline and preserves all 30 run IDs.
`evals/baseline-v2.json` archives the prior 28/30 result including its two failures.
The local v3 failure and timeout records are also retained. Criteria and time budgets
changed, so this is not evidence of a statistically measured model improvement.

Locked local tests: 315 passed, 116 subtests passed. GitHub CI passed on the evaluated
code revision: https://github.com/seongkyunmun/agent-platform/actions/runs/34911663689.
The final documentation/baseline commit has no additional runtime code changes.

## Owner Review

Code review performed during implementation does not replace human review.
Current verification profiles lack owner-review provenance, and the platform
profile uses a legacy scope label rather than task AC IDs. Historical planning
requirements are not automatically equivalent to the standard WORK/PRD AC table.

Before enforcing evidence/policy gates:

1. Define the current task's AC table in WORK section 4 or PRD section 12.
2. Map specific profile scope.acs to tests that prove those criteria, not every AC to one broad suite.
3. Run verification in report mode and inspect missing/stale/failing evidence.
4. Have the actual owner review the code/profile and record their identity using verify-profile approve.
5. Enable enforcement only for the reviewed project and confirm expected rejection/success behavior.

No owner approval, global profile migration or external service policy change is
performed by this closeout report. Native automatic resume and remote dashboards
remain optional expansion work, not unfinished fixes in this follow-up.
