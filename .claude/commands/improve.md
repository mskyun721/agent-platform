---
description: Inspect and explicitly evaluate project-scoped instruction improvements
argument-hint: <list|show|propose|evaluate|review|apply|revert> [candidate-id]
allowed-tools:
  - Bash
  - Read
---

Read standards/reference/improvement-workflow.md and use the shared
`agent-platform-agent improvement` CLI with an explicit root. Default to list/show
when no action is specified. Proposals require selected feedback and exact target
and replacement text; pass JSON through a file/structured stdin, never shell
interpolation. Do not infer an approval from a passing evaluation or automatically
call review/apply. Show the diff and obey the user's existing authorization scope.
Report failed, stale and pending operations accurately. Never overwrite later
user edits or change active-project. Evaluation runs require explicit models and
a bounded budget; report real run IDs and missing evidence without fabricating
results. Recording a candidate is not learning completion.
