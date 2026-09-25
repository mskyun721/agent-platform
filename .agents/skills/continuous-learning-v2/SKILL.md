---
name: continuous-learning-v2
description: Turn explicitly selected corrections, recurring failures and successful fixes into evidence-backed project-scoped learning candidates. Use for requested learning or retrospective work.
license: MIT
metadata:
  origin: affaan-m/ECC
  upstream_commit: e482e579415fde18357cafce70f177ae19fd7f03
  adaptation: agent-platform
---

# Continuous Learning v2 — Platform Adaptation

Create small reusable lessons from explicitly selected feedback. This adaptation supports manual candidate capture and review now; ECC background observers, automatic promotion and its instinct CLI are not installed. Do not claim automatic learning is running.

## Candidate contract

Each candidate contains id, project/workspace, trigger, action, evidence references, counterevidence, status, created/updated time and proposed target. Keep one trigger/action pair per candidate. Separate observed facts from proposed generalizations.

Example: trigger="reporting automatic collection health"; action="check the active session ID and latest source timestamp, not only historical record counts". This applies to collection health, not every coding task.

## Procedure

1. Resolve the selected target using the project's existing root rules. Platform improvements use explicit platform root; never overwrite active-project. Do not combine unrelated projects' lessons.
2. Read only user-selected feedback or artifacts within scope. Conversation capture opt-in does not authorize bulk transcript learning. Do not copy raw prompts, code, tool outputs or secrets into a lesson.
3. Identify a recurring correction, resolved failure or repeatable workflow and write a draft trigger/action with evidence. One incident can justify a narrow bug fix; it does not prove a universal preference.
4. Search existing rules/candidates for duplicates and counterexamples. Mark uncertainty and contradictory evidence explicitly. Confidence scores, if used, are heuristic metadata, not permission to enforce.
5. Define a regression case or before/after evaluation that could falsify the proposed improvement. Reuse the platform eval runner when available.
6. Record the candidate in the current task's DECISIONS or retrospective artifact with status draft. If feedback/improvement commands are actually installed, their --help may be used; do not invent or run commands that exist only in a plan.
7. Review the concrete diff and evaluation evidence before promoting to a rule or skill. Respect existing authorization and invalidate approval after content/target changes. Track the applied revision and a safe revert path; preserve later user edits.

## Boundaries

No automatic global promotion, background LLM analysis, hook installation, export of observations or self-approval. Project-specific lessons stay project-specific unless cross-project adoption is explicitly requested and reviewed. State plainly whether this run captured a candidate, evaluated it or applied it.

## Platform integration

Use the current session's available tools and follow AGENTS.md, role-skills policy and authorized scope. This skill grants no additional permissions. Save outputs in the existing target task artifacts with draft status until reviewed; it does not require a new artifact for a simple answer. Log selected/used/result honestly. Both backends use this same workflow; native discovery does not prove a successful skill execution.

## Provenance

Adapted from [ECC continuous-learning-v2](https://github.com/affaan-m/ECC/tree/e482e579415fde18357cafce70f177ae19fd7f03/skills/continuous-learning-v2) under MIT; see LICENSE and skill.json for the fixed source revision and adaptation record. This package contains the platform workflow, not ECC runtime scripts.
