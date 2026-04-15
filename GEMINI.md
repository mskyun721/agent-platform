# Agent Platform — Gemini Guide

This file is automatically loaded by the Gemini CLI as project context.
Gemini is used in this project for **security auditing** and **CICD artifact generation**.

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

## Security Baseline

Full rules: `standards/security-baseline.md`

Key checks:
- OWASP Top 10: injection, broken auth, XSS, CSRF, insecure deserialization
- Hardcoded secrets: API keys, passwords, tokens, credentials in source or config
- Dependency vulnerabilities: outdated packages with known CVEs
- Input validation at all system boundaries (user input, external APIs)
- No `chmod 777`, no `sudo`, no `rm -rf /`
- No empty catch blocks that swallow exceptions silently

---

## What Gemini Does in This Project

### 1. Security Audit (`audit_run_gemini`)
- Input: `docs/features/<name>/PRD.md`, `API-SPEC.md`, source code, `standards/security-baseline.md`
- Output: write `docs/features/<name>/SECURITY-AUDIT.md`
- Scope: `all` | `owasp` | `secrets` | `deps`
- Required sections:
  1. **Risk Level** — Overall: Critical / High / Medium / Low / None
  2. **Findings** — `### [Severity] Title` + file:line + impact + recommended fix
  3. **Checklist** — items that passed this audit
  4. **Recommendations** — prioritised action list
- Severity Critical/High → findings must be resolved before QA proceeds

### 2. CICD Artifacts (`release_run_gemini`)
- Input: PRD.md, API-SPEC.md, DECISIONS.md, REVIEW.md, SECURITY-AUDIT.md, TEST-PLAN.md,
  git log, `templates/PR-TEMPLATE.md`, `templates/RELEASE-NOTE.md`, `standards/commit-convention.md`
- Output files under `docs/features/<name>/`:
  - `PR-BODY.md` — GitHub PR body following `templates/PR-TEMPLATE.md`
  - `RELEASE-NOTE.md` — Semantic Versioning, migration steps, rollback procedure
  - `DEPLOY-CHECKLIST.md` — monitoring dashboards, alerts, canary, rollback commands
- Action: `pr-body` | `release-note` | `checklist` | `all`
- PR title must follow Conventional Commits format, ≤ 70 characters
- All artifact status must be set to `draft` — final approval is human-driven

---

## Output Conventions

Every artifact **must** start with YAML front-matter:
```yaml
---
agent: security   # or: cicd
feature: <name>
status: draft
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

- Write files to `docs/features/<feature-name>/` only
- Do **not** evaluate or reference files that do not exist in the repository
- `mcp-server/` Python code is within audit scope

---

## Constraints

- Never read or output: `.env`, `.pem`, `.key`, `credentials`, `secret` files
- Never hardcode API keys, passwords, or tokens
- Only assess files that actually exist — do not assume missing files
- Status is always `draft` — never set to `approved` autonomously
