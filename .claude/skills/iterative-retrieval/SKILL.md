---
name: iterative-retrieval
description: Refine code and document retrieval in bounded passes when relevant context is missing or too large. Use for complex investigations or explicitly delegated tasks needing scoped context.
license: MIT
metadata:
  origin: affaan-m/ECC
  upstream_commit: e482e579415fde18357cafce70f177ae19fd7f03
  adaptation: agent-platform
---

# Iterative Retrieval

Retrieve enough context to answer the question without loading the whole repository. This is a retrieval procedure usable in the current session; it does not require creating subagents.

## Bounded loop

1. Dispatch a focused query using the task's terminology. Where graphify-out/graph.json exists, follow the project's graphify-first rule and query the graph before raw source exploration.
2. Evaluate candidates: directly relevant, supporting, unrelated; record why and what critical context remains missing. A ranking is a heuristic, not proof of coverage.
3. Refine using discovered symbols, callers, domain synonyms and boundaries. Use graphify path/explain for relationships, then targeted rg and actual source reads for confirmation. Retain relevant tests; do not exclude all tests as a default.
4. Repeat up to three passes by default, stopping early when the question is supported. If critical gaps remain, report them and the next precise retrieval instead of asserting completeness or dumping all files.

## Context packet

Return the question, selected file/symbol references, verified relationships, relevant test cases, exclusions, unresolved gaps and the next recommended action. Keep facts separate from inference. If a caller explicitly requested delegation, pass this scoped packet rather than the entire session history.

Respect project content boundaries: ignored docs/PROMPT are not automatically searchable, and credentials/secret files are excluded. A stale graph requires source verification; graph matches are impact candidates, not passing test or review evidence.

## Platform integration

Use the current session's available tools and follow AGENTS.md, role-skills policy and authorized scope. This skill grants no additional permissions. Save outputs in the existing target task artifacts with draft status until reviewed; it does not require a new artifact for a simple answer. Log selected/used/result honestly. Both backends use this same workflow; native discovery does not prove a successful skill execution.

## Provenance

Adapted from [ECC iterative-retrieval](https://github.com/affaan-m/ECC/tree/e482e579415fde18357cafce70f177ae19fd7f03/skills/iterative-retrieval) under MIT; see LICENSE and skill.json for the fixed source revision and adaptation record. This package contains the platform workflow, not ECC runtime scripts.
