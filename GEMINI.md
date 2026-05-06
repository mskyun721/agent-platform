# Agent Platform — Gemini Guide

This file is automatically loaded by the Gemini CLI as project context.

## Project Overview

agent-platform is a multi-agent workflow platform for generated/target backend
projects. The MCP server in this repository is Python/FastMCP; Kotlin, Java,
Spring WebFlux, and Hexagonal Architecture rules apply to target projects that
this platform creates or supports.

## Source of Truth

- Follow `CLAUDE.md` for shared project rules, especially `TARGET_PROJECT`,
  front-matter status, handoff, and security policy.
- Feature artifacts belong under `{TARGET_PROJECT}/docs/features/<feature>/`.
  `TARGET_PROJECT` is the absolute path stored in `agent-platform/.active-project`.
- Do not write feature artifacts under `agent-platform/docs/features/`.
- Relative paths such as `docs/features/<feature>/PRD.md` are always relative to
  `TARGET_PROJECT`, not this platform repository.

## Gemini Role

Gemini is an optional execution backend selected by user request,
`[AI: gemini]`, or `.agent-config.json`. It is not tied to a specific Agent
role.

Default orchestration policy uses Gemini together with Codex for reviewer work.
The reviewer preserves both raw outputs and writes a synthesized `REVIEW.md`.

Gemini-backed MCP tools may produce planning, review, security audit, QA, and
CICD draft artifacts. Raw CLI-generated artifacts should remain
`status: draft`; the owning Claude Subagent reviews and promotes them to
`approved` or `rejected`.

## Security Baseline

- Follow `standards/security-baseline.md`.
- Check OWASP Top 10 risks, hardcoded secrets, dependency risk, input
  validation, and unsafe shell commands.
- Mask suspected secrets in any report.

## Constraints

- Never read or output `.env`, `.pem`, `.key`, credential, or secret files.
- Never hardcode API keys, passwords, or tokens.
- Only assess files that actually exist.
- Platform-root `PROMPT/`, `claude_log.md`, and ignored `docs/**` files are
  local work/log areas; read them only when the user explicitly names them.
- `mcp-server/` Python code is part of this project and may be reviewed when the
  requested scope is the platform itself.
