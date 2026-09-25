---
description: Inspect measured token usage and select focused context for the current task
argument-hint: [explicit-project-root]
allowed-tools:
  - Bash
  - Read
---

Resolve the requested project root and run the shared CLI:
`agent-platform-agent observe efficiency --root <root>`.
Explain the sample window, missing usage, source overlap and backend/model grouping.
Do not sum native/wrapper records or call a completed run an approved task.
Do not claim savings, cache hit rates or retry costs that are not measured.

For the current task, identify the smallest relevant context and verification:
- Use existing graphify guidance for relationships, then read only relevant files.
- Use iterative-retrieval when the first retrieval is insufficient; stop once the
  required context is found. Do not load every skill or role into the prompt.
- Use skill-stocktake only when a skill inventory/cleanup is actually requested.
- Choose role skills by standards/reference/role-skills.md and retain required
  security/review gates. Token reduction does not authorize skipping checks.

Report at most the leading usage observation, the selected context/skill, and the
required verification. Do not automatically launch model trials, change policy,
install skills, purge evidence or modify the active project.
