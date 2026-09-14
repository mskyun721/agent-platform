# Run Recovery

Recovery is a local inspection and explicit continuation protocol, not a new
native CLI session engine. Checkpoints contain bounded single-line decisions,
unresolved items, verification run IDs, existing docs-relative artifact paths,
and a content-hash manifest. Never put raw prompts, source or tool output in
metadata. Known secret patterns are rejected; arbitrary prose cannot be proven
secret-free by a regex.

```bash
agent-platform-agent state checkpoint RUN --phase implementation --next-action "run verification"
agent-platform-agent state heartbeat RUN --pid EXECUTION_PID
agent-platform-agent state resume RUN
agent-platform-agent state transition RUN interrupted --reason "process stopped"
```

Checkpoints require the original registered project and allowed workspace.
Unregister/rebind or unsafe paths fail closed. Resume reports `running`, `done`,
`no_checkpoint`, `resumable`, or `diverged`; divergence lists changed paths and
requires inspection and fresh verification. The response contains readable
`resume_prompt` Markdown, but never launches another AI or executes next_action.
Cancelled/completed runs are terminal. Stale heartbeat alone cannot prove death:
a live, inaccessible or foreign-host PID blocks duplicate execution. PID reuse
may conservatively require manual inspection; this tool never kills a recorded PID.

`resume.stale_after_sec` defaults to 600. Automatic native resume is not enabled,
even if an unrecognized configuration requests it; `automatic_resume_supported`
is false. No verified persisted native session handle is currently available,
so the portable checkpoint path is used. A finished attempt's P4 event history
is immutable; a new execution needs its own run record rather than overwriting
old timestamps. Direct sessions must supply their actual long-lived PID, not
the short-lived state command's PID.

Schema 3 snapshots preserve checkpoint/control rows. Conflicting imports never
overwrite live control state. Pruning retains checkpoint-linked runs and active
control rows. Source bodies are not read when inspecting stored checkpoint hashes.

## External Actions

Schema 4 adds an idempotency ledger, included in export/import and retained by
prune. `state actions --run-id RUN` lists intent, confirmation and remote result.
`state action-plan RUN push KEY --target-json '{"remote":"origin","branch":"feature/example","head":"COMMIT_SHA"}'`
records intent only. After actual user approval, `state action-confirm ACTION
--confirmed-by IDENTITY` records that decision; `state action-execute ACTION`
performs remote lookup and a normal, non-forced push. PR targets instead require
repository (`owner/repo`)/branch/base/head/title and create a draft PR. CLI confirmation is an auditable
convention, not proof of a human identity or a security boundary.

Concurrent execution is claimed before lookup. Existing remote results are
skipped. A timeout/crash after starting a write is uncertain and cannot be
blindly retried. `state action-reconcile ACTION` only reads the remote: a found
result closes it as a duplicate; absence does not prove the write never happened.
Resume only lists actions and never calls these adapters. Tests use fake adapters;
no real PR/push/deployment is a test side effect.

The CLI adapter supports Git push and GitHub draft PRs. Other kinds can be recorded
but need an explicitly supplied Python adapter with `lookup` and `execute` methods;
there is no generic automatic deployment/Confluence executor. Direct shell commands
outside this API cannot be made idempotent by a local ledger.

CLI push planning pins a hash of the configured remote push URL; destination changes
after confirmation are rejected. The URL is not stored or printed (it may contain
credentials). PR commands always specify the confirmed owner/repository. PR execution
also runs the committed-change size checker and refuses changes above 500 logic lines
or unclassifiable binary changes. Non-Python counts remain conservative upper bounds.

## Fresh Session

After a `resumable` verdict, explicitly call `state continue RUN --pid NEW_PID`
from the new session. It creates a fresh run linked by parent_run_id, copies the
checkpoint metadata, checks the workspace again, and claims the original checkpoint
once. A competing/repeated claim cannot create a second runnable continuation.
Use the returned new run ID for heartbeats, checkpoints and `state end`.
The old interrupted event remains unchanged. Resume of the parent points to the
child; resume of the child also lists pending actions from its ancestry. Schema 5
snapshots preserve these links. No native CLI or next_action is auto-executed.

`runs.outcome` records an attempt's process completion, while `runs.state` in
query responses also reflects the control record. Three consecutive owning-role
rejections put an active run into waiting. A subsequent successful CLI exit does
not clear that intervention requirement. Starting a new session is not approval.
