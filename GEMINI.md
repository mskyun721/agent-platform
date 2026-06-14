# Agent Platform — Gemini Guide

This file is automatically loaded by the Gemini CLI as project context.

## Project Overview

agent-platform is a multi-agent workflow platform for generated/target backend
projects. The MCP server in this repository is Python/FastMCP; Kotlin, Java,
Spring WebFlux, and Hexagonal Architecture rules apply to target projects that
this platform creates or supports.

## Source of Truth

- Follow `CLAUDE.md` for shared project rules: `TARGET_PROJECT` resolution,
  `docs/<type>/<name>/` artifact paths, front-matter status, handoff, and
  security policy.

## Gemini Role

Gemini is a standalone execution backend selected by user request,
`[AI: gemini]`, the Gemini CLI, or `.agent-config.json`.
It is not tied to a specific Agent role.

Reviewer work runs with the explicitly selected CLI only.
When Gemini is selected, the reviewer writes a backend-neutral `REVIEW.md` with
summary, findings, positives, and action items.

Gemini-backed MCP tools and `agent-platform-agent` may produce planning,
backend, review, security audit, QA, and CICD draft artifacts. Raw
CLI-generated artifacts should remain `status: draft`; a human or owning Agent
reviews and promotes them to `approved` or `rejected`.

## Direct CLI Agent Execution

When the user asks Gemini CLI to run an agent role directly, execute the role in
the current Gemini session using the artifact contract below. Do not require MCP
or `agent-platform-agent run ...` for normal same-AI execution.

Use MCP only when the user explicitly asks to delegate to another AI backend, or
when a platform operation such as scaffold/gate/handoff should be reused.

Role output contract:

| User intent | Required output |
|---|---|
| planner | `{TARGET_PROJECT}/docs/<type>/<name>/PRD.md`, `TASK.md` |
| backend | target project code, `API-SPEC.md`, `DECISIONS.md` |
| reviewer | `REVIEW.md` |
| security | `SECURITY-AUDIT.md` |
| qa | `TEST-PLAN.md`, and test/BUG files when needed |
| cicd/release | `PR-BODY.md`, `RELEASE-NOTE.md`, `DEPLOY-CHECKLIST.md` |

Optional MCP delegation mapping:

| User intent | MCP tool |
|---|---|
| create/scaffold a feature | `feature_scaffold` |
| list/check feature artifacts | `feature_list_artifacts`, `feature_gate_check` |
| planner via Gemini wrapper | `plan_run_gemini` |
| backend via Gemini wrapper | `backend_run_gemini` |
| reviewer via another backend | `review_run` with `ai="codex"` |
| security via Gemini wrapper | `audit_run_gemini` |
| qa via Gemini wrapper | `qa_run_gemini` |
| cicd/release via Gemini wrapper | `release_run_gemini` |

Examples of user phrasing that should trigger direct Gemini execution:

- "planner로 payment-cancel PRD/TASK 작성해줘"
- "backend agent로 payment-cancel 구현해줘"
- "reviewer로 payment-cancel 리뷰해줘"
- "qa로 payment-cancel 테스트 계획 만들어줘"

Examples that should trigger MCP delegation:

- "reviewer는 codex로 실행해줘"
- "backend는 gemini wrapper로 실행해줘"
- "gate-check 돌려줘"

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
