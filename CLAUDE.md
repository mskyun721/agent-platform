# Agent Platform - Project Instructions

agent-platform은 Claude Code Subagent와 MCP 서버로 대상 백엔드 프로젝트의 기획→개발→리뷰→보안→QA→릴리스를 조율한다. 이 repo의 서버는 Python/FastMCP이고, Kotlin/Java Spring WebFlux 규칙은 생성·지원 대상 프로젝트에 적용된다.

## Core Policy
- 산출물은 항상 `{TARGET_PROJECT}/docs/features/<feature>/` 에 저장한다.
- `TARGET_PROJECT` 는 `agent-platform/.active-project` 의 절대 경로다.
- `docs/features/...` 상대 경로는 항상 `TARGET_PROJECT` 기준이다.
- `agent-platform/docs/features/` 에 feature 산출물을 쓰지 않는다.
- 플랫폼 repo 루트의 `PROMPT/`, `claude_log.md`, `docs/**` 는 Agent 산출물/로컬 작업 영역이다. 사용자가 명시한 경우만 읽고, 공통 reference는 `standards/reference/**`에 둔다.
- 산출물은 `templates/` front-matter를 따른다.
- 외부 CLI 원본 산출물은 `status: draft`; 담당 Subagent가 검수 후 `approved` 또는 `rejected` 로 승격한다.
- PR 생성, push, 배포 등 외부 변경 액션은 사용자 확인 후에만 수행한다.

## CLI Defaults
- `backend`: Claude Code
- `reviewer`: Codex + Gemini 둘 다 실행 후 `REVIEW.md` 종합
- `planner`, `security`, `qa`, `cicd`: Orchestrator가 사용자에게 CLI를 물어본 뒤 진행
- 사용자 `[AI: claude|gemini|codex]` 태그가 있으면 그 지시가 우선한다.
- `.agent-config.json` 의 `preferred_cli` 는 사용자가 답할 수 없는 MCP wrapper fallback 용도다.

## Agents
| Agent | 역할 | 산출물 |
|---|---|---|
| `orchestrator` | 라우팅·handoff·질문 | - |
| `planner` | 요구사항/작업계획 | `PRD.md`, `TASK.md` |
| `backend` | 구현·테스트·문서화 | `API-SPEC.md`, `DECISIONS.md`, 코드 |
| `reviewer` | Codex+Gemini 교차 리뷰 | `REVIEW.md`, `REVIEW-CODEX.md`, `REVIEW-GEMINI.md` |
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
- Langfuse status: `standards/reference/observability-langfuse.md`
- Standards: `standards/*.md`

## Maintenance
코드나 설정을 바꾸면 사용자 참고용 `README.md`도 최신화한다.
