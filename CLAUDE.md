# Agent Platform - Project Instructions

이 프로젝트는 기획/백엔드/QA/CICD 등 7개 역할을 Claude Code Subagent로 구성한 팀 공통 개발 워크플로우 플랫폼이다.

> **중요**: `mcp-server/` 는 Python으로 구현된 MCP 서버다. Kotlin/Spring 스택은 이 플랫폼이 생성·지원하는 **대상 프로젝트**의 스택이다.

## 기본 원칙
- 모든 Subagent는 본 문서와 `standards/` 하위 표준을 **반드시** 참조한다
- 모든 산출물은 `templates/` 의 Front-matter 규약을 준수한다
- Feature 작업 산출물은 `docs/features/<feature-name>/` 하위에 저장한다
- Agent 간 Handoff는 `workflows/` 플로우를 따른다

## 플랫폼 기술 스택 (MCP 서버)
- Language: Python 3.11+
- MCP Framework: FastMCP
- Entry point: `mcp-server/src/agent_platform_mcp/server.py`

## 대상 프로젝트 기술 스택 (생성/지원 대상)
- Language: Kotlin (JVM 21+)
- Framework: Spring Boot 3.x + WebFlux (reactive, coRouter)
- Async: Kotlin Coroutine
- Build: Gradle Kotlin DSL + buildSrc
- Test: JUnit5 + MockK + Testcontainers
- Architecture: Hexagonal (Ports & Adapters)

## 공통 표준 참조
- 코드 스타일: `standards/coding-style.md`
- 커밋/브랜치: `standards/commit-convention.md`
- API 계약: `standards/api-contract.md`
- 테스트 정책: `standards/test-policy.md`
- 보안 베이스라인: `standards/security-baseline.md`

## Front-matter 규약 (모든 산출물 필수)
```yaml
---
agent: planner | backend | qa | cicd | orchestrator | reviewer | security
feature: <feature-name>
status: draft | review | approved | rejected
created: YYYY-MM-DD
updated: YYYY-MM-DD
links:
  prd: docs/features/<name>/PRD.md
  api: docs/features/<name>/API-SPEC.md
---
```

## Agent 역할 및 호출 규칙
| Agent | 역할 | 주요 산출물 |
|---|---|---|
| `orchestrator` | 요청 분석 및 Agent 라우팅 | — |
| `planner` | PRD·TASK 작성 | `PRD.md`, `TASK.md` |
| `backend` | 백엔드 구현 | `API-SPEC.md`, `DECISIONS.md` |
| `reviewer` | 코드 리뷰 | `REVIEW.md` |
| `security` | 보안 감사 | `SECURITY-AUDIT.md` |
| `qa` | 테스트 계획·코드 생성 | `TEST-PLAN.md` |
| `cicd` | PR·릴리즈·배포 체크리스트 | `PR-BODY.md`, `RELEASE-NOTE.md`, `DEPLOY-CHECKLIST.md` |

- 직접 호출: `@orchestrator`, `@planner`, `@backend`, `@reviewer`, `@security`, `@qa`, `@cicd`
- 자동 라우팅: 사용자 요청을 Orchestrator가 분석하여 적절한 Agent 위임
- 다음 Agent는 이전 Agent의 Quality Gate 통과 산출물만 수용

## 슬래시 커맨드
| 커맨드 | 설명 |
|---|---|
| `/new-feature <name>` | feature 디렉터리 생성 및 Planner 호출 |
| `/gate-check <name>` | feature 산출물 Front-matter·링크 정합성 검사 |
| `/handoff <from> <to> <feature>` | Quality Gate 검증 후 다음 Agent로 handoff |
| `/retrospective` | 완료된 feature 회고 문서 템플릿 생성 |
| `/init-project <name> <pkg> [opts]` | springboot-kotlin-skeleton 클론 및 커스터마이징 |

## MCP 툴 (agent-platform 서버)
`mcp-server/src/agent_platform_mcp/server.py` 에 등록된 툴 목록:
- `hello` — 서버 동작 확인
- `feature_scaffold` / `feature_list_artifacts` / `feature_gate_check` — feature 라이프사이클
- `handoff_validate` — Agent 간 handoff 검증
- `log_append` — `claude_log.md` 기록
- `review_run_codex` — Codex CLI 코드 리뷰
- `audit_run_gemini` — Gemini CLI 보안 감사
- `qa_run_codex` — Codex CLI QA
- `release_run_gemini` — Gemini CLI CICD 산출물 생성
- `standards_read` / `standards_list` — 표준 문서 조회
- `project_init` — springboot-kotlin-skeleton 클론 및 커스터마이징

## 글로벌 지침 상속
사용자 글로벌 `~/.claude/CLAUDE.md` 규칙(응답 한국어, 보안 절대 규칙 등)을 모두 상속한다.

## 작업 로그
모든 진행 작업은 루트 `claude_log.md`에 기록한다.
