---
description: Diagnose project hook configuration and native observation freshness
argument-hint: <project-id-or-absolute-root>
allowed-tools:
  - Bash
  - Read
---

Use the explicitly supplied registered project ID or absolute root; for platform work use the platform checkout root. Run `agent-platform-agent doctor --root <root>` through the existing platform uv environment. Quote arguments without executing user-supplied shell syntax. Do not change active-project.

Explain configured versus observed/stale/unknown. Historical turn counts do not prove that the user's active session is captured. Show backend latest session ID and time, capture setting, poll freshness and errors. Do not execute configured hook commands or install missing CLIs as a diagnostic side effect. Report unavailable fields honestly.
