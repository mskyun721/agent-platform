# Agent Platform — Codex Guide

This file is automatically loaded by the Codex CLI as project context.
Codex is used in this project for **code review** and **QA** tasks only.

---

## Project Overview

agent-platform is a multi-agent workflow platform that orchestrates 7 Claude Code
subagents (planner / backend / reviewer / security / qa / cicd / orchestrator).
Feature work is tracked under `docs/features/<feature-name>/`.

---

## Repository Structure

```
agent-platform/
├── mcp-server/src/agent_platform_mcp/   # Python MCP server (FastMCP)
│   ├── server.py                         # Tool registration entry point
│   ├── config.py                         # Paths, agent/status constants
│   ├── tools/                            # One module per MCP tool
│   └── frontmatter.py                    # YAML front-matter parser
├── docs/features/<name>/                 # Feature artifacts (PRD, API-SPEC, …)
├── standards/                            # Coding-style, test-policy, security-baseline, …
├── templates/                            # Front-matter templates for each artifact
├── workflows/                            # Feature-flow, hotfix-flow
└── .claude/commands/                     # Slash command definitions
```

> The Kotlin/Spring stack (hexagonal architecture, WebFlux, Coroutine) is the
> target of **generated projects**, not the source language of this repo.
> The MCP server itself is Python.

---

## Coding Standards

- Full rules: `standards/coding-style.md`
- Security rules: `standards/security-baseline.md`
- Key principles:
  - `val` over `var`, immutable-first
  - Early return to minimize nesting
  - Magic numbers → named constants
  - Functions ≤ 30 lines; split if longer
  - Comments explain WHY, not WHAT/HOW
  - No empty catch blocks
  - No hardcoded secrets

---

## What Codex Does in This Project

### 1. Code Review (`review_run_codex`)
- Input: `docs/features/<name>/PRD.md`, `API-SPEC.md`, `DECISIONS.md`, source code
- Output: write `docs/features/<name>/REVIEW.md`
- Focus areas: `all` | `security` | `performance` | `style` | `hexagonal`
- Severity labels: `[HIGH]` / `[MEDIUM]` / `[LOW]`
- Required sections: Summary · Findings · Positive · Action Items

### 2. QA (`qa_run_codex`)
- Input: PRD.md (AC list), API-SPEC.md, DECISIONS.md, REVIEW.md, SECURITY-AUDIT.md, source
- Output: write `docs/features/<name>/TEST-PLAN.md`; optionally generate test code
- Scope: `plan` | `test-gen` | `regression` | `all`
- Test template: `templates/TEST-PLAN.md`
- Test policy: `standards/test-policy.md`

---

## Output Conventions

Every artifact **must** start with YAML front-matter:
```yaml
---
agent: reviewer   # or: qa
feature: <name>
status: draft
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

- Write files to `docs/features/<feature-name>/` only
- Kotlin test code → `src/test/kotlin/`; Python test code → `tests/`
- P0/P1 bugs found during QA → create `docs/features/<name>/bugs/BUG-<id>.md`
- Do **not** evaluate files that do not exist in the repository

---

## Constraints

- Never read or output: `.env`, `.pem`, `.key`, `credentials`, `secret` files
- Never hardcode API keys, passwords, or tokens
- Only assess files that actually exist — do not assume missing files
- `mcp-server/` Python code is part of this project and within review scope
