# Evidence Gates

Use `--evidence` on gate-check/handoff or `evidence=true` on their MCP equivalents.
Default mode reports findings without changing legacy gate results. Setting
`gate.evidence_enforced: true` also enables the checks when the flag is omitted.
Do not enable enforcement until representative work has been observed and reviewed.

Explicit verification profiles map tests to acceptance criteria:

```json
{"verify_profiles":{"unit":{"argv":["python","-m","pytest","-q"],"scope":{"acs":["AC-1","AC-2"]}}}}
```

Only explicit AC mappings record evidence. An unmapped suite does not establish
every criterion. Criteria are read from WORK.md section 4 or PRD.md section 12;
empty/duplicate IDs and incomplete rows are refused, fenced examples ignored.

Evidence stores workspace, task, AC, run, profile hash, criterion-set hash and
before/after code state. A successful command which changes code is stale, not
current passed evidence. Changing criteria or profile configuration also invalidates
old evidence. No required ACs means incomplete, not vacuous success.

Fingerprints hash current relevant tracked/untracked content and executable bits,
including tracked deletions. Git HEAD is provenance, not the content identity:
documentation-only commits do not invalidate unchanged code. `tracked_diff` is
a content-manifest hash, not a raw patch (raw Git diffs could expose tracked secrets).
Docs, Git metadata, local state, caches, virtualenvs, dependency directories and
protected filenames are excluded before reading. Relevant symlinks and unreadable
inputs fail closed. The configured observation DB is excluded even with a custom path.

HIGH/Critical findings remain unresolved until their own block contains
`- 상태: resolved (<current full fingerprint>)` (or `- status:`). A marker in a
different heading or fenced example does not resolve a finding. Resolution is still
an owning reviewer's claim, not an automated proof of correctness.
Approved review/security/QA artifacts need `approved_fingerprint` matching current
code for enforced completion. The platform proposes fingerprints, never approvals.

SQLite migrates schema 1 to 2 transactionally to add evidence. State exports now use
snapshot schema 2 and retain evidence; schema 1 imports remain supported. Evidence
referenced runs are retained by prune. This is a local audit mechanism, not a secure
boundary against an actor who can edit the verifier or its database.

## Verification Policy Review

The operator CLI `verify-profile approve <id> --reviewer <identity>` records the
semantic profile hash, platform HEAD, time, reviewer and verifier-source hash.
There is no MCP approval tool. Review metadata does not hash itself. Uncommitted
verifier code can be reviewed explicitly; a clean Git commit is not substituted
for review. Later committed or pending verifier content changes are detected.
Legacy hash-only approval remains distinguishable as incomplete provenance.

Completion handoffs report `handoff_allowed: false` when policy provenance is
missing/changed or requested evidence is incomplete, while retaining the actual
verification_status. `gate.policy_enforced: true` additionally fails the gate.
No real profile is approved automatically during platform development. The CLI
is operator-facing convention, not proof that an AI cannot run it; reviewer
identity and local configuration remain reviewable claims, not authentication.
