---
name: search-first
description: Research existing libraries, MCP tools, skills and maintained implementations before adding a dependency or building substantial new infrastructure.
license: MIT
metadata:
  origin: affaan-m/ECC
  upstream_commit: e482e579415fde18357cafce70f177ae19fd7f03
  adaptation: agent-platform
---

# Search First

Before creating a new utility, integration or infrastructure feature, compare reuse, extension and custom implementation. Small routine edits do not require a fresh external search.

## Procedure

1. State the required behavior, language/runtime, integration constraints and acceptance criteria.
2. Check which search channels are available. Start with project code and tests: use graphify first when the project requires it, then targeted rg and source reads.
3. Search relevant primary documentation, package registries, MCP/skill catalogs and GitHub sources. Use only channels relevant to the task. Missing access means unsearched, not no solution exists.
4. Compare the strongest candidates on functional fit, maintenance evidence, license, dependencies, security/permissions, version compatibility and operational cost. Cite the actual source and version where known; popularity alone does not prove quality.
5. Recommend adopt, extend, compose or build. Explain why the cheapest adequate option meets the constraints and why alternatives fall short.
6. Implement only within the user's authorized task. Research does not itself authorize package installation, account connection, remote mutation or configuration changes.

## Output

| Candidate | Fit/gaps | Maintenance/version | License/dependencies | Decision |
|---|---|---|---|---|

Record the selected option and key tradeoff in the existing DECISIONS or planning artifact. Use inline research by default; no mandatory researcher subagent. If no candidate fits, retain the search evidence and build the minimal local solution.

## Platform integration

Use the current session's available tools and follow AGENTS.md, role-skills policy and authorized scope. This skill grants no additional permissions. Save outputs in the existing target task artifacts with draft status until reviewed; it does not require a new artifact for a simple answer. Log selected/used/result honestly. Both backends use this same workflow; native discovery does not prove a successful skill execution.

## Provenance

Adapted from [ECC search-first](https://github.com/affaan-m/ECC/tree/e482e579415fde18357cafce70f177ae19fd7f03/skills/search-first) under MIT; see LICENSE and skill.json for the fixed source revision and adaptation record. This package contains the platform workflow, not ECC runtime scripts.
