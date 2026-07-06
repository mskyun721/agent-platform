# Agent Platform — Codex Guide

This file is automatically loaded by the Codex CLI as project context.

## Project Overview

agent-platform is a multi-agent workflow platform for generated/target backend
projects. The MCP server in this repository is Python/FastMCP; Kotlin, Java,
Spring WebFlux, and Hexagonal Architecture rules apply to target projects that
this platform creates or supports.

## Source of Truth

- Follow `CLAUDE.md` for shared project rules: `TARGET_PROJECT` resolution,
  `docs/<type>/<name>/` artifact paths, front-matter status, handoff, and
  security policy.

## Codex Role

Codex is the default standalone execution backend selected by user request,
`[AI: codex]`, the Codex CLI, or `.agent-config.json`.
It is not tied to a specific Agent role.


When Codex generates artifacts through MCP tools or `agent-platform-agent`, leave
raw CLI output as `status: draft`. A human or owning Agent reviews and promotes
the artifact to `approved` or `rejected`.

## Direct CLI Agent Execution

When the user asks Codex CLI to run an agent role directly, execute the role in
the current Codex session using the artifact contract below. Do not require MCP
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
| planner via Codex wrapper | `plan_run` with `cli="codex"` |
| backend via Codex wrapper | `backend_run` with `cli="codex"` |
| reviewer via another backend | `review_run` with `cli="gemini"` |
| security via Codex wrapper | `audit_run` with `cli="codex"` |
| qa via Codex wrapper | `qa_run` with `cli="codex"` |
| cicd/release via Codex wrapper | `release_run` with `cli="codex"` |

Examples of user phrasing that should trigger direct Codex execution:

- "planner로 payment-cancel PRD/TASK 작성해줘"
- "backend agent로 payment-cancel 구현해줘"
- "reviewer로 payment-cancel 리뷰해줘"
- "qa로 payment-cancel 테스트 계획 만들어줘"

Examples that should trigger MCP delegation:

- "reviewer는 gemini로 실행해줘"
- "backend는 codex wrapper로 실행해줘"
- "gate-check 돌려줘"

## Constraints

- Never read or output `.env`, `.pem`, `.key`, credential, or secret files.
- Never hardcode API keys, passwords, or tokens.
- Only assess files that actually exist.
- Platform-root `PROMPT/`, `claude_log.md`, and ignored `docs/**` files are
  local work/log areas; read them only when the user explicitly names them.
- `mcp-server/` Python code is part of this project and may be reviewed when the
  requested scope is the platform itself.
