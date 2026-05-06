# Agent Platform - Project Instructions

이 프로젝트는 기획/백엔드/QA/CICD 등 7개 역할을 Claude Code Subagent로 구성한 팀 공통 개발 워크플로우 플랫폼이다.

> **중요**: `mcp-server/` 는 Python으로 구현된 MCP 서버다. Kotlin/Spring 스택은 이 플랫폼이 생성·지원하는 **대상 프로젝트**의 스택이다.

## 기본 원칙
- 모든 Subagent는 본 문서와 `standards/` 하위 표준을 **반드시** 참조한다
- 모든 산출물은 `templates/` 의 Front-matter 규약을 준수한다
- Feature 작업 산출물은 **타겟 프로젝트**의 `docs/features/<feature-name>/` 하위에 저장한다
  - 타겟 프로젝트 경로: `agent-platform/.active-project` 파일에 기록된 절대 경로
  - MCP 툴(`plan_run_gemini`, `review_run_gemini` 등)은 자동으로 타겟 경로를 사용한다
  - Write/Edit 도구로 직접 저장 시에도 반드시 타겟 프로젝트 절대 경로를 사용할 것
  - **agent-platform/docs/features/ 에 저장 금지** (gitignore 대상이며 타겟 프로젝트와 무관)
- `docs/features/...` 처럼 상대 경로로 표기된 산출물 경로는 항상 타겟 프로젝트 기준이다
- 플랫폼 repo 루트의 `PROMPT/`, `claude_log.md`, `docs/**` 는 로컬 작업/로그 영역이다. 사용자가 명시한 파일만 읽고, 일반 분석·리뷰 대상에 포함하지 않는다
- Agent 간 Handoff는 `workflows/` 플로우를 따른다

## 플랫폼 기술 스택 (MCP 서버)
- Language: Python 3.11+
- MCP Framework: FastMCP
- Entry point: `mcp-server/src/agent_platform_mcp/server.py`

## 대상 프로젝트 기술 스택 (생성/지원 대상)
- Language: **Kotlin** (JVM 21+) 또는 **Java** (JVM 21+)
- Framework: Spring Boot 3.x + WebFlux (reactive)
- Async: **[Kotlin]** Coroutine (`suspend fun`, `coRouter`) / **[Java]** Project Reactor (`Mono`, `Flux`, `RouterFunction`)
- Build: Gradle Kotlin DSL 또는 Maven
- Test: JUnit5 + **[Kotlin]** MockK / **[Java]** Mockito + Testcontainers
- Architecture: Hexagonal (Ports & Adapters)
- 언어는 타겟 프로젝트 `src/main/kotlin|java/` 경로로 자동 감지

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

## Status 책임 규칙
- 외부 CLI(Gemini/Codex)가 MCP 툴로 생성한 원본 산출물은 기본 `status: draft` 로 둔다
- 담당 Claude Subagent가 원본을 검수·분류·보완한 뒤 `status: approved` 또는 `status: rejected` 로 승격한다
- PR 생성, push, 배포 같은 외부 변경 액션은 사용자 확인 후에만 수행한다

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
| `/handoff <next-agent> <feature>` | Quality Gate 검증 후 다음 Agent로 handoff |
| `/retrospective` | 완료된 feature 회고 문서 템플릿 생성 |
| `/init-project <name> <pkg> [opts]` | springboot-kotlin-skeleton 클론 및 커스터마이징 |

## MCP 툴 (agent-platform 서버)
`mcp-server/src/agent_platform_mcp/server.py` 에 등록된 툴 목록:
- `hello` / `feature_scaffold` / `feature_list_artifacts` / `feature_gate_check` / `handoff_validate` / `log_append`
- `plan_run_gemini` / `review_run_gemini` / `review_run_codex` / `audit_run_gemini`
- `qa_run_gemini` / `qa_run_codex` / `release_run_gemini`
- `standards_read` / `standards_list` / `project_init`

## CLI 선택 및 모델 설정
Claude Code, Gemini CLI, Codex CLI는 선택 가능한 실행 백엔드다. 사용자가 `[AI: claude|gemini|codex]` 태그로 지정하면 해당 CLI를 우선한다.

미지정 시 기본 정책:
- `backend`: Claude Code
- `reviewer`: Codex와 Gemini를 모두 실행한 뒤 `REVIEW.md` 종합
- `planner`, `security`, `qa`, `cicd`: Orchestrator가 사용자에게 사용할 CLI를 물어본 뒤 진행

`preferred_cli` 는 사용자에게 물어볼 수 없는 MCP wrapper의 fallback 용도다.

`agent-platform/.agent-config.json` 으로 기본 CLI 및 Claude 모델 조정 가능:
```json
{
  "preferred_cli": "gemini",   // "gemini" | "codex"
  "agent_cli_defaults": {
    "backend": "claude",
    "reviewer": ["codex", "gemini"],
    "planner": "ask",
    "security": "ask",
    "qa": "ask",
    "cicd": "ask"
  },
  "model_overrides": {
    "orchestrator": "haiku",   // claude 모델
    "backend": "opus",
    "planner": "haiku",
    ...
  }
}
```

## Superpowers 플러그인 (선택적 품질 강화)
Claude Code·Gemini CLI·Codex CLI 각각에 설치하면 해당 CLI 호출 시 스킬 컨텍스트가 자동 로드된다.

| CLI | 설치 명령 |
|---|---|
| Claude Code | `/plugin install superpowers@claude-plugins-official` |
| Gemini CLI | `gemini extensions install https://github.com/obra/superpowers` |
| Codex CLI | `codex` 실행 → 플러그인 UI → "superpowers" 검색 |

활용 시점:
- `/new-feature` 전 설계가 불확실한 기능 → `/superpowers:brainstorm`
- 버그 해결 난항 시 → `/superpowers:systematic-debugging`
- Backend Phase 구현 시 TDD 강제 → `/superpowers:test-driven-development`

> Gemini/Codex에 설치하면 `review_run_gemini`, `qa_run_gemini` 등 MCP 툴 호출 품질이 자동으로 향상된다.

## 글로벌 지침 상속
사용자 글로벌 `~/.claude/CLAUDE.md` 규칙(응답 한국어, 보안 절대 규칙 등)을 모두 상속한다.

## 작업 로그
모든 진행 작업은 타겟 프로젝트의 `claude_log.md`에 기록한다. 타겟 프로젝트가 설정되지 않은 플랫폼 자체 작업만 루트 `claude_log.md`를 사용한다.

## README.md
현재 프로젝트의 코드 또는 설정 값 등 변경 후 README.md 파일의 내용을 최신화 한다.
