# Agent Platform

**Claude Code + Codex CLI + Gemini CLI 를 MCP 서버로 통합한 팀 공통 개발 워크플로우 플랫폼.**

기획 → 백엔드 개발 → 코드 리뷰 → 보안 감사 → QA → CI/CD 의 6단계 워크플로우를 7개 Subagent 로 자동화한다. 외부 CLI 는 전용 구독(ChatGPT Plus, Gemini) 으로 실행되어 **별도 API 과금 없음**.

## 주요 특징
- **멀티 CLI 협업**: Claude 가 기본, Codex 가 코드 리뷰, Gemini 가 보안 감사를 담당
- **MCP 서버 허브**: 공용 툴(스캐폴딩, Quality Gate, 외부 CLI 래핑) 을 단일 MCP 서버가 제공
- **헥사곤 아키텍처 강제**: Backend Agent 가 도메인/애플리케이션/어댑터 구조를 자동 준수
- **Front-matter 기반 워크플로우**: 산출물 상태 (`draft → review → approved`) 로 Handoff 게이팅
- **Hook 기반 보안 강제**: 위험 명령 차단, 시크릿 필터링, 자동 린트
- **Slash Command**: `/new-feature`, `/gate-check`, `/handoff`, `/retrospective`, `/init-project`

---

## 구성
```
agent-platform/
├── CLAUDE.md                      # 프로젝트 전역 지침 (Claude 자동 로드)
├── AGENTS.md                      # Codex CLI 전역 지침 (Codex 자동 로드)
├── GEMINI.md                      # Gemini CLI 전역 지침 (Gemini 자동 로드)
├── .claude/
│   ├── agents/                    # 7개 Subagent
│   │   ├── orchestrator.md        # 전체 플로우 관장
│   │   ├── planner.md             # PRD/TASK 작성
│   │   ├── backend.md             # Kotlin + Spring 구현
│   │   ├── reviewer.md            # Codex CLI 연동 코드 리뷰
│   │   ├── security.md            # Gemini CLI 연동 보안 감사
│   │   ├── qa.md                  # 테스트 계획·실행
│   │   └── cicd.md                # PR·릴리스
│   ├── commands/                  # Slash Command (MCP 툴 경유)
│   │   ├── new-feature.md
│   │   ├── gate-check.md
│   │   ├── handoff.md
│   │   ├── retrospective.md
│   │   └── init-project.md
│   └── settings.json              # Hook (보안 차단, 린트, MCP health check)
├── .mcp.json                      # Claude 의 MCP 서버 등록
├── .gemini/settings.json          # Gemini 의 MCP 서버 등록
├── mcp-server/                    # Python + uv + mcp[cli] MCP 서버
│   └── src/agent_platform_mcp/
│       ├── server.py              # FastMCP 엔트리
│       ├── config.py              # 경로/Agent 상수
│       ├── frontmatter.py
│       └── tools/                 # 13개 MCP 툴
│           ├── feature.py         # scaffold / list / gate_check
│           ├── handoff.py         # validate
│           ├── review.py          # run_codex (코드 리뷰)
│           ├── audit.py           # run_gemini (보안 감사)
│           ├── qa.py              # run_codex (테스트 계획·코드 생성)
│           ├── release.py         # run_gemini (PR·릴리즈·배포 체크리스트)
│           ├── project.py         # init (스켈레톤 클론·커스터마이징)
│           ├── standards.py       # read / list
│           └── log.py             # append
├── standards/                     # 팀 공통 표준 (단일 진실 소스)
├── templates/                     # 산출물 템플릿 10종
├── workflows/                     # Handoff 플로우
├── docs/features/<name>/          # 실제 산출물 저장소
└── PROMPT/                        # 로드맵·Phase 리포트 (개인 작업 영역, gitignored)
```

---

## 요구사항
| 도구 | 용도 | 필수/선택 |
|---|---|---|
| Claude Code CLI | 메인 Agent 실행 | 필수 |
| Claude Pro/Max 구독 | Claude 과금 | 필수 |
| `uv` (Python) | MCP 서버 실행 | 필수 (`brew install uv`) |
| `jq` | Hook 스크립트 | 필수 (`brew install jq`) |
| Codex CLI + ChatGPT Plus/Pro 구독 | Reviewer Agent | 선택 (없으면 reviewer 비활성) |
| Gemini CLI + Google 계정 | Security Agent | 선택 (무료 쿼터로도 사용 가능) |

---

## 초기 세팅

### 1. 도구 설치
```bash
brew install uv jq
npm install -g @anthropic-ai/claude-code  # 또는 다른 설치 방법
# Codex / Gemini 는 각자 공식 채널 참고
```

### 2. 로그인
```bash
unset ANTHROPIC_API_KEY                # Pro/Max 구독 사용을 위해
claude login                            # Claude
codex login                             # Codex (ChatGPT 계정)
gemini                                  # Gemini (첫 실행 시 브라우저 인증)
```

### 3. 프로젝트 클론
```bash
git clone <repo> agent-platform && cd agent-platform
```

### 4. MCP 서버 등록
이미 `.mcp.json`, `.gemini/settings.json` 이 커밋되어 있어 Claude/Gemini 는 자동 인식.
Codex 는 사용자 전역 설정이라 한 번만 수동 등록:
```bash
codex mcp add agent-platform -- uv --directory ./mcp-server run agent-platform-mcp
```

### 5. 연결 확인
```bash
cd /path/to/agent-platform      # ⚠️ 반드시 프로젝트 루트에서 실행
claude mcp list                  # agent-platform: ✓ Connected 표시되어야 함
codex mcp list                   # agent-platform: enabled
```

`No MCP servers configured` 가 나오면:
1. **실행 위치 확인** — `pwd` 가 `agent-platform` 루트인지 확인 (`.mcp.json` 은 프로젝트 스코프)
2. **프로젝트 신뢰 승인** — `claude mcp reset-project-choices` 후 `claude` 세션 진입 시 승인 프롬프트 수락
3. **세션 내 확인** — Claude 세션 안에서 `/mcp` 실행해 상태 재확인
4. **최후 수단 — user 스코프로 등록**:
   ```bash
   claude mcp add agent-platform -s user -- uv --directory "$(pwd)/mcp-server" run agent-platform-mcp
   ```
   (user 스코프는 어느 디렉터리에서도 인식됨. `$(pwd)` 가 절대 경로로 치환되는지 확인)

---

## 기본 사용법

### 방식 0. 신규 Kotlin/Spring 프로젝트 생성

`springboot-kotlin-skeleton` 을 클론해 프로젝트명·패키지·버전·의존성을 한 번에 교체한다.

```
claude                    # 세션 진입
```
```
> /init-project my-service com.example.myservice
```

옵션 지정 예:
```
# 버전 일괄 지정
> /init-project my-service com.example.myservice java=21 kotlin=2.1.20 spring-boot=3.4.5 gradle=8.13

# 의존성 교체
> /init-project my-service com.example.myservice deps=webflux,r2dbc,security,validation,actuator

# 생성 위치 지정 (기본값: claude 실행 경로의 상위 디렉터리 ../)
> /init-project my-service com.example.myservice target=/Users/me/Projects
```

지원 의존성 ID:
`web` `webflux` `r2dbc` `jpa` `security` `validation` `actuator` `cache`
`redis` `postgresql` `r2dbc-postgresql` `h2` `flyway` `kafka` `test` `mockk` `testcontainers`

생성 후 프로젝트를 agent-platform 워크플로우로 개발하려면 **방식 1** 으로 이어서 진행.

---

### 방식 1. Slash Command 로 시작 (권장)
```
claude                                  # 세션 진입
```
```
> /new-feature payment-cancel           # feature 디렉터리 + PRD/TASK 생성
> @planner PRD 작성                     # Planner 가 요구사항 정리
> @backend 구현해                       # Backend 가 코드 작성
> @reviewer @security 교차 검증         # 병렬 실행
> /handoff qa payment-cancel            # Quality Gate 검증 후 QA 호출
> @qa 테스트
> @cicd PR 올려줘
```

### 방식 2. 자동 오케스트레이션
Orchestrator 에게 요구사항만 전달, 나머지는 자동:
```
> 회원 탈퇴 기능 추가. 탈퇴 시 개인정보는 90일 후 완전 삭제.
```
Orchestrator 가 `workflows/feature-flow.md` 에 따라 전 단계를 순차 실행.

### 방식 3. 핫픽스
```
> @orchestrator 핫픽스: 로그인 시 NPE. stack trace: ...
```
`workflows/hotfix-flow.md` 로 Backend → Security → QA → CICD 단축 플로우 실행.

---

## 워크플로우 상세

```
[사용자 요청]
     ↓
[Orchestrator]
     ↓
[@planner]    ──► PRD.md, TASK.md
     ↓
[@backend]    ──► src/, API-SPEC.md, DECISIONS.md
     ↓
    ┌─────────────────────────────────────┐
    ▼                                     ▼
[@reviewer]                         [@security]
(Codex CLI → REVIEW.md)             (Gemini CLI → SECURITY-AUDIT.md)
    │                                     │
    └───────────────┬─────────────────────┘
                    ▼
              [@qa]  ──► TEST-PLAN.md
                    ↓
              [@cicd] ──► PR + RELEASE-NOTE.md
```

- `@reviewer` 가 HIGH 이슈 탐지 → Backend 반려
- `@security` 가 Critical 탐지 → Backend 반려 + hotfix 권장
- 둘 다 `approved` 여야 QA 진입
- 모든 Handoff 는 `handoff_validate` MCP 툴로 자동 검증

---

## Slash Command

| 명령 | 용도 | 예시 |
|---|---|---|
| `/init-project <name> <pkg> [opts]` | Kotlin/Spring 프로젝트 생성 | `/init-project my-service com.example.myservice` |
| `/new-feature <name>` | feature 스캐폴딩 | `/new-feature payment-cancel` |
| `/gate-check [name]` | Front-matter·링크 검증 | `/gate-check` 또는 `/gate-check payment-cancel` |
| `/handoff <next> <feature>` | Quality Gate 후 다음 Agent 호출 | `/handoff qa payment-cancel` |
| `/retrospective <feature>` | 회고 문서 생성 | `/retrospective payment-cancel` |

- `.claude/commands/` 에 파일 하나 = 명령 하나
- Front-matter 의 `allowed-tools` 로 도구 제한
- 내부는 MCP 툴 호출 + 파일 fallback 패턴

---

## MCP 툴 목록 (13종)

| 툴 | 기능 | 내부 동작 |
|---|---|---|
| `project_init` | Kotlin/Spring 프로젝트 생성 | 스켈레톤 클론 → 버전·패키지·의존성 교체 |
| `feature_scaffold` | feature 디렉터리 + PRD/TASK 생성 | 파일 복사 + Front-matter 치환 |
| `feature_list_artifacts` | feature 내 파일별 agent/status 요약 | `docs/features/<name>/*.md` 스캔 |
| `feature_gate_check` | Front-matter·링크·선행조건 검증 | Agent별 prerequisite 매핑 |
| `handoff_validate` | Agent 전환 사전 게이트 | `gate_check` + from_agent 산출물 검증 |
| `log_append` | `claude_log.md` 타임스탬프 기록 | — |
| `review_run_codex` | Codex CLI 로 코드 리뷰 → REVIEW.md | `codex exec --full-auto` 서브프로세스 |
| `audit_run_gemini` | Gemini CLI 로 보안 감사 → SECURITY-AUDIT.md | `gemini --approval-mode plan` |
| `qa_run_codex` | Codex CLI 로 QA → TEST-PLAN.md | `codex exec --full-auto` 서브프로세스 |
| `release_run_gemini` | Gemini CLI 로 CICD 산출물 생성 | `gemini --approval-mode auto_edit` |
| `standards_read` | standards/workflows/templates 본문 조회 | 화이트리스트 경로 |
| `standards_list` | 사용 가능 문서 카탈로그 | — |
| `hello` | 연결 확인 | — |

### 직접 툴 호출 예 (디버깅용)
```bash
printf '%s\n%s\n%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"s","version":"0.1"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"feature_gate_check","arguments":{"name":"payment-cancel"}}}' \
  | uv --directory ./mcp-server run agent-platform-mcp
```

---

## Hooks (자동화·보안)

`.claude/settings.json` 에 정의. Claude Code 이벤트마다 shell 명령이 강제 실행.

| Event | Matcher | 동작 |
|---|---|---|
| `PreToolUse` | `Bash` | `rm -rf /`, `curl`, `sudo rm`, `DROP DATABASE` 등 차단 |
| `PostToolUse` | `Edit\|Write` | `.kt` 변경 시 `ktlintCheck` / feature 문서 Front-matter 누락 경고 |
| `UserPromptSubmit` | — | `API_KEY=...` 등 시크릿 패턴 차단 |
| `Stop` | — | `claude_log.md` 에 세션 종료 스탬프 |
| `SessionStart` | — | MCP 서버 health check — 실패 시 경고 |

커스텀 Hook 추가 시 `jq` 로 stdin JSON 파싱, `{"decision":"block","reason":"..."}` 로 차단.

---

## 산출물 구조

```
docs/features/payment-cancel/
├── PRD.md                # @planner
├── TASK.md               # @planner
├── API-SPEC.md           # @backend
├── DECISIONS.md          # @backend
├── REVIEW.md             # @reviewer (Codex 원문 + Reviewer Notes)
├── SECURITY-AUDIT.md     # @security (Gemini 원문 + Triage)
├── TEST-PLAN.md          # @qa
├── RELEASE-NOTE.md       # @cicd
└── bugs/BUG-*.md         # @qa (발견 시)
```

모든 문서는 Front-matter 로 `status` 추적:
```yaml
---
agent: backend
feature: payment-cancel
status: approved
created: 2026-04-14
updated: 2026-04-14
links: { prd: docs/features/payment-cancel/PRD.md }
---
```

---

## 아키텍처 표준 (Backend Agent)

모든 도메인은 **헥사곤 구조** 로 강제:
```
{base-package}/
├── {domain-name}/
│   ├── domain/              # Entity, ValueObject
│   ├── application/
│   │   ├── port/{in,out}/   # UseCase / Repository 인터페이스
│   │   └── service/         # UseCase 구현
│   └── adapter/
│       ├── in/web/          # coRouter + Handler + dto
│       └── out/persistence/ # PersistenceAdapter + Repository + entity
├── common/
└── config/
```
- Domain Entity ≠ Persistence Entity (매핑은 Adapter 에서)
- `domain/` 은 Spring/JPA/R2DBC import 금지

표준 상세: `standards/coding-style.md`, `standards/security-baseline.md`.

---

## 문서 분류 규칙

| 위치 | 용도 |
|---|---|
| `docs/features/<name>/` | Agent 산출물 (PRD / API-SPEC / REVIEW 등) |
| `standards/` | 팀 공통 표준 |
| `templates/` | 산출물 템플릿 |
| `workflows/` | Agent 간 Handoff 플로우 |
| `PROMPT/` | 개인 작업 영역 (로드맵·Phase 리포트), **gitignore** |
| `CLAUDE.md` | 프로젝트 지침 (Claude 자동 로드) |
| `AGENTS.md` | Codex CLI 지침 (Codex 자동 로드) |
| `GEMINI.md` | Gemini CLI 지침 (Gemini 자동 로드) |
| `claude_log.md` | 작업 로그 (gitignore) |

---

## 확장 로드맵

- MCP progress notification (장시간 리뷰 중 사용자 피드백)
- `examples/sample-feature/` 완전한 E2E 예제
- `triage_rules.yaml` false positive 자동 분류
- GitHub Actions 에서 MCP 서버 자동 테스트
- Claude Agent SDK 로 Headless 파이프라인 (CI 직접 연동)

---

## 라이선스
내부 사용. 팀 표준에 맞춰 수정/확장 자유.
