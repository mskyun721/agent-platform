# Agent Platform — Shared Agent Guide

This file is the single source of shared rules for every CLI backend (Claude
Code, Codex). `CLAUDE.md` imports/points here and adds
only their own CLI-specific notes; Codex reads this file directly, so its
own notes live in `## Codex Notes` below.

## Project Overview

agent-platform은 Codex/Claude 실행 backend와 MCP 서버로 대상 백엔드 프로젝트의 기획→개발→리뷰→보안→QA→릴리스를 조율한다. 이 repo의 서버는 Python/FastMCP이고, Kotlin/Java Spring WebFlux, Hexagonal Architecture 규칙은 생성·지원 대상 프로젝트에 적용된다.

## Core Policy

- 산출물은 항상 `{TARGET_PROJECT}/docs/<type>/<name>/` 에 저장한다. `<type>`은 작업
  종류에 따라 `features`(신규 기능), `fix`(버그 수정), `refactor`(리팩토링) 등으로
  구분한다 (브랜치 타입은 `standards/commit-convention.md` 참조).
- `TARGET_PROJECT` 는 `agent-platform/.active-project` 의 절대 경로다.
- `docs/<type>/<name>/...` 상대 경로는 항상 `TARGET_PROJECT` 기준이다.
- `agent-platform/docs/<type>/` 에 산출물을 쓰지 않는다.
- 예외: 플랫폼 자체 개선은 명시적 `root`/`--root`로 플랫폼 루트를 선택하고
  `agent-platform/docs/<type>/<name>/`에 저장한다. `.active-project`는 바꾸지 않는다.
  이 예외는 플랫폼 루트 자체에만 적용하며 외부 프로젝트는 기존 allowlist를 따른다.
- 플랫폼 repo 루트의 `PROMPT/`, `docs/**` 는 Agent 산출물/로컬 작업 영역이다. 사용자가 명시한 경우만 읽고, 공통 reference는 `standards/reference/**`에 둔다.
- 산출물은 `templates/` front-matter를 따른다.
- 외부 CLI 원본 산출물은 `status: draft`; 담당 Subagent가 검수 후 `approved` 또는 `rejected` 로 승격한다.
- PR 생성, push, 배포 등 외부 변경 액션은 사용자 확인 후에만 수행한다.

## CLI Defaults

- `backend`: Claude Code (기본); 사용자 요청 시 `[AI: codex]`로 전환 가능
- `reviewer`, `planner`, `security`, `qa`, `cicd`: 선택된 AI backend로 실행 가능하며, reviewer 산출물은 backend-neutral `REVIEW.md` 형식을 따른다
- 사용자 `[AI: claude|codex]` 태그가 있으면 그 지시가 우선한다.
- `.agent-config.json` 의 `preferred_cli` 는 사용자가 답할 수 없는 MCP wrapper fallback 용도다.

## Agents

| Agent | 역할 | 산출물 |
|---|---|---|
| `orchestrator` | 라우팅·handoff·질문 | - |
| `planner` | 요구사항/작업계획 | `PRD.md`, `TASK.md` |
| `backend` | 구현·테스트·문서화 | `API-SPEC.md`, `DECISIONS.md`, 코드 |
| `reviewer` | 구현 코드 리뷰 | `REVIEW.md` |
| `security` | 보안 감사 | `SECURITY-AUDIT.md` |
| `qa` | 테스트 계획·검증 | `TEST-PLAN.md`, `bugs/BUG-*.md` |
| `cicd` | PR/릴리스/배포 준비 | `PR-BODY.md`, `RELEASE-NOTE.md`, `DEPLOY-CHECKLIST.md` |

## Commands

- `/init-project <name> <pkg> [opts]`
- `/new-feature <name>`
- `/gate-check <name>`
- `/handoff <next-agent> <feature>`
- `/retrospective <feature>`

## References

- Workflow: `workflows/feature-flow.md`, `workflows/hotfix-flow.md`
- Backend phases: `standards/reference/backend-phase-flow.md`
- Release policy: `standards/reference/cicd-release-policy.md`
- MCP tools: `standards/reference/mcp-tools.md`
- Setup: `standards/reference/setup.md`
- Standards: `standards/*.md`

## Artifact Promotion

### Optional Single Work Contract

작은 작업은 `feature_scaffold(..., contract="work-v1")` 또는
`new-feature <name> --contract work-v1`로 `WORK.md` 하나를 선택할 수 있다.
이 계약에서는 직접 세션이 목표·범위·위험·검증·결정·결과를 기록하며 별도 planner 호출은 필수가 아니다.
기존 PRD/TASK 계약은 기본값으로 유지한다. 역할 wrapper의 문서 생성은 아직 기존 계약이므로
WORK 작업에 `plan_run`/`backend_run` 등을 자동 호출하지 않는다.
위험은 low/high를 명시하고 high에는 사유와 완료 전 보안 검토를 남긴다.
리뷰 요청 시 REVIEW.md, 보안 검토 시 SECURITY-AUDIT.md를 별도로 작성한다.
검증 명령의 성공과 문서 승인은 다르며, 구현 변경 후 이전 승인을 재사용하지 않는다.
자동 위험 교차 검사와 코드 상태별 승인 유효성 검사는 후속 구현이다.

When a CLI generates artifacts through MCP tools or a direct agent role, leave
raw CLI output as `status: draft`. A human or owning Agent reviews and
promotes the artifact to `approved` or `rejected`.

## Direct CLI Agent Execution

When the user asks a CLI (Claude Code or Codex) to run an agent role
directly, execute the role in the current session using the artifact
contract below. Do not require MCP or `agent-platform-agent run ...` for
normal same-AI execution.

Use MCP only when the user explicitly asks to delegate to another AI
backend, or when a platform operation such as scaffold/gate/handoff should be
reused.

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
| planner via CLI wrapper | `plan_run` with `cli="codex"` |
| backend via CLI wrapper | `backend_run` with `cli="codex"` |
| reviewer via another backend | `review_run` with `cli="codex"` |
| security via CLI wrapper | `audit_run` with `cli="codex"` |
| qa via CLI wrapper | `qa_run` with `cli="codex"` |
| cicd/release via CLI wrapper | `release_run` with `cli="codex"` |

Examples of user phrasing that should trigger direct execution:

- "planner로 payment-cancel PRD/TASK 작성해줘"
- "backend agent로 payment-cancel 구현해줘"
- "reviewer로 payment-cancel 리뷰해줘"
- "qa로 payment-cancel 테스트 계획 만들어줘"

Examples that should trigger MCP delegation:

- "backend는 codex wrapper로 실행해줘"
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
- Platform-root `PROMPT/` and ignored `docs/**` files are local work areas;
  read them only when the user explicitly names them.
- `mcp-server/` Python code is part of this project and may be reviewed when
  the requested scope is the platform itself.

## Maintenance

- 사용법·설정·사용자에게 보이는 동작이 바뀌면 `README.md`를 갱신한다. 내부 리팩토링·테스트만의
  변경은 제외.
- Claude subagent 모델은 `.agent-config.json`의 `claude_models`에서만 바꾼다.
  `scripts/sync_claude_settings.py`(SessionStart hook)가 `.claude/agents/*.md`에 주입한다.
- 회고(`/retrospective`)와 worktree 격리는 필요할 때만 쓴다(반복 문제, 병렬·평가·격리). 어떤
  흐름에서도 강제하지 않는다.

## Codex Notes

Codex is the default standalone execution backend selected by user request,
`[AI: codex]`, the Codex CLI, or `.agent-config.json`. It is not tied to a
specific Agent role.
