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
