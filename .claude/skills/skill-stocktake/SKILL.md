---
name: skill-stocktake
description: Audit skills for overlap, stale references, conflicting instructions and maintenance value. Use for a requested skill inventory or cleanup review.
license: MIT
metadata:
  origin: affaan-m/ECC
  upstream_commit: e482e579415fde18357cafce70f177ae19fd7f03
  adaptation: agent-platform
---

# Skill Stocktake

Inventory the requested project skills and explicitly requested global/plugin scopes. Report which paths were inspected and which were unavailable. Use the existing platform skill registry when present, but distinguish package installation, native discovery and actual use.

## Procedure

1. List SKILL.md names, descriptions, source versions, content hashes and activation status. Do not read credential files or silently expand into all user configuration.
2. Choose full review for the first inventory; for a repeated review compare content hashes and review changed/new entries plus dependencies affected by those changes. An mtime change alone is not a content change.
3. Read the relevant skills and their actual referenced resources. Compare with AGENTS.md and role instructions for duplication and contradictions. Verify version-sensitive external commands against primary documentation.
4. Judge actionability, scope fit, uniqueness, currency and context cost. Usage frequency is unknown unless observed telemetry exists; installation is not usage.
5. Return one of keep, improve, update, merge, retire for each inspected skill, with concrete evidence and a specific action. For merge name the destination; for retire identify the replacement and affected callers.
6. Present changes before modifying or removing skills; follow existing task authorization. Preserve unmanaged/global files. Use the managed skill lifecycle for managed packages.

## Output

| Skill | Source/hash | Observed use | Verdict | Evidence and proposed action |
|---|---|---|---|---|

Write findings in the current task's review artifact. Cache hashes only in an allowed local working area; do not create global state implicitly. Run the review in the current session unless delegation was explicitly requested. A heuristic verdict is not a measured performance result.

## Platform integration

Use the current session's available tools and follow AGENTS.md, role-skills policy and authorized scope. This skill grants no additional permissions. Save outputs in the existing target task artifacts with draft status until reviewed; it does not require a new artifact for a simple answer. Log selected/used/result honestly. Both backends use this same workflow; native discovery does not prove a successful skill execution.

## Provenance

Adapted from [ECC skill-stocktake](https://github.com/affaan-m/ECC/tree/e482e579415fde18357cafce70f177ae19fd7f03/skills/skill-stocktake) under MIT; see LICENSE and skill.json for the fixed source revision and adaptation record. This package contains the platform workflow, not ECC runtime scripts.
