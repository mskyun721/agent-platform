---
description: Record explicitly selected project-scoped feedback
argument-hint: <correction-or-failure-or-suggestion> <summary>
allowed-tools:
  - Bash
  - Read
---

Resolve the explicit target project before recording. Use `agent-platform-agent feedback add --root <root> --source-kind manual --kind <kind>` with a JSON object containing only `summary` on stdin. For an explicitly selected observation run, use `platform_run` or `native_turn` plus its source ID. Use a JSON file/structured stdin; do not interpolate the summary into executable shell code.

Record only the selected feedback, not the conversation transcript. Return the feedback ID and explain that recording is not rule approval or automatic learning. Use feedback list/show/purge for explicit inspection or deletion requests. Never change active-project or apply an improvement silently.
