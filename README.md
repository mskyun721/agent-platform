# Agent Platform

**Claude Code + Codex CLI + Gemini CLI 를 MCP 서버로 통합한 팀 공통 개발 워크플로우 플랫폼.**

기획 → 백엔드 개발 → 코드 리뷰 → 보안 감사 → QA → CI/CD 의 6단계 워크플로우를 7개 Subagent 로 자동화한다. 외부 CLI 는 전용 구독(ChatGPT Plus, Gemini) 으로 실행되어 **별도 API 과금 없음**.

## 주요 특징
- **멀티 CLI 협업**: Claude 가 기본, Gemini(2.5-flash) 가 기획·코드 리뷰·보안 감사·QA·CICD 를 담당, Codex(GPT-5.4) 는 리뷰·QA 대안
- **MCP 서버 허브**: 공용 툴(스캐폴딩, Quality Gate, 외부 CLI 래핑) 을 단일 MCP 서버가 제공
- **헥사곤 아키텍처 강제**: Backend Agent 가 도메인/애플리케이션/어댑터 구조를 자동 준수
- **Front-matter 기반 워크플로우**: 산출물 상태 (`draft → review → approved`) 로 Handoff 게이팅
- **Hook 기반 보안 강제**: 위험 명령 차단, 시크릿 필터링, 자동 린트
- **Langfuse 옵저빌리티**: Claude hook + MCP 서브프로세스 span 이중 계측, Prompt Management 지원
- **Slash Command**: `/new-feature`, `/gate-check`, `/handoff`, `/retrospective`, `/init-project`

---

## 구성
```
agent-platform/
├── CLAUDE.md                      # 프로젝트 전역 지침 (Claude 자동 로드)
├── AGENTS.md                      # Codex CLI 전역 지침 (Codex 자동 로드)
├── GEMINI.md                      # Gemini CLI 전역 지침 (Gemini 자동 로드)
├── .claude/
│   ├── agents/                    # 7개 Subagent 정의
│   │   ├── orchestrator.md        # 전체 플로우 관장 (model: haiku)
│   │   ├── planner.md             # PRD/TASK 작성 (model: haiku)
│   │   ├── backend.md             # Kotlin + Spring 구현 (model: opus)
│   │   ├── reviewer.md            # Gemini CLI 연동 코드 리뷰 (Codex 대안) (model: haiku)
│   │   ├── security.md            # Gemini CLI 연동 보안 감사 (model: haiku)
│   │   ├── qa.md                  # Gemini CLI 연동 테스트 계획·실행 (Codex 대안) (model: haiku)
│   │   └── cicd.md                # Gemini CLI 연동 PR·릴리스 (model: haiku)
│   ├── commands/                  # Slash Command (MCP 툴 경유)
│   │   ├── new-feature.md
│   │   ├── gate-check.md
│   │   ├── handoff.md
│   │   ├── retrospective.md
│   │   └── init-project.md
│   ├── settings.json              # Hook (보안 차단, 린트, Langfuse 계측)
│   └── settings.local.json        # 로컬 전용 설정 (gitignore)
├── .mcp.json                      # Claude 의 MCP 서버 등록
├── .gemini/settings.json          # Gemini 의 MCP 서버 등록
├── scripts/
│   ├── langfuse-hook.sh           # PostToolUse → Langfuse span 전송
│   └── langfuse-stop-hook.sh      # Stop → Langfuse session trace 전송
├── docker-compose.langfuse.yml    # Langfuse self-hosted (gitignore)
├── .env.local                     # Langfuse API 키 (gitignore)
├── mcp-server/                    # Python + uv + mcp[cli] MCP 서버
│   └── src/agent_platform_mcp/
│       ├── server.py              # FastMCP 엔트리 (13개 툴 등록)
│       ├── config.py              # 경로/Agent 상수
│       ├── frontmatter.py         # YAML Front-matter 파서
│       ├── observability.py       # Langfuse 싱글턴 클라이언트 (no-op 안전)
│       └── tools/
│           ├── feature.py         # scaffold / list_artifacts / gate_check
│           ├── handoff.py         # validate
│           ├── review.py          # run_gemini (기본) + run_codex (대안) + Langfuse span + Prompt Mgmt
│           ├── audit.py           # run_gemini + Langfuse span + Prompt Mgmt
│           ├── qa.py              # run_gemini (기본) + run_codex (대안) + Langfuse span + Prompt Mgmt
│           ├── release.py         # run_gemini + Langfuse span + Prompt Mgmt
│           ├── project.py         # init (스켈레톤 클론·커스터마이징)
│           ├── standards.py       # read / list
│           └── log.py             # append
├── standards/                     # 팀 공통 표준 (단일 진실 소스)
│   ├── coding-style.md
│   ├── commit-convention.md
│   ├── api-contract.md
│   ├── test-policy.md
│   └── security-baseline.md
├── templates/                     # 산출물 템플릿 10종
├── workflows/                     # Handoff 플로우
│   ├── feature-flow.md
│   └── hotfix-flow.md
├── docs/features/<name>/          # 실제 산출물 저장소
└── PROMPT/                        # 로드맵·Phase 리포트 (개인 작업 영역, gitignored)
```

---

## Agent 구성

| Agent | 역할 | 모델 | 툴 범위 | 주요 산출물 |
|---|---|---|---|---|
| `orchestrator` | 요청 분석·Agent 라우팅 | haiku | 네이티브 + Task | — |
| `planner` | PRD·TASK 작성 | haiku | 네이티브 + MCP | `PRD.md`, `TASK.md` |
| `backend` | Kotlin/Spring 구현 | opus | 네이티브 (Read/Write/Edit/Bash) | `API-SPEC.md`, `DECISIONS.md`, 코드 |
| `reviewer` | 코드 리뷰 (Gemini 위임, Codex 대안) | haiku | 네이티브 + MCP | `REVIEW.md` |
| `security` | 보안 감사 (Gemini 위임) | haiku | 네이티브 + MCP | `SECURITY-AUDIT.md` |
| `qa` | 테스트 계획·실행 (Gemini 위임, Codex 대안) | haiku | 네이티브 + MCP | `TEST-PLAN.md` |
| `cicd` | PR·릴리스·배포 (Gemini 위임) | haiku | 네이티브 + MCP | `PR-BODY.md`, `RELEASE-NOTE.md`, `DEPLOY-CHECKLIST.md` |

> **네이티브 툴**: Read, Write, Edit, Glob, Grep, Bash, TaskCreate/Update/List  
> **MCP 툴**: `mcp__agent-platform__*` — MCP 서버 경유

---

## 요구사항
| 도구 | 용도 | 필수/선택 |
|---|---|---|
| Claude Code CLI | 메인 Agent 실행 | 필수 |
| Claude Pro/Max 구독 | Claude 과금 | 필수 |
| `uv` (Python) | MCP 서버 실행 | 필수 (`brew install uv`) |
| `jq` | Hook 스크립트 | 필수 (`brew install jq`) |
| Codex CLI + ChatGPT Plus/Pro 구독 | Reviewer·QA Agent | 선택 (없으면 reviewer·qa 비활성) |
| Gemini CLI + Google 계정 | Security·CICD Agent | 선택 (무료 쿼터로도 사용 가능) |
| Docker | Langfuse self-hosted | 선택 (옵저빌리티 사용 시) |

---

## 초기 세팅

### 1. 도구 설치
```bash
brew install uv jq
npm install -g @anthropic-ai/claude-code
# Codex / Gemini 는 각자 공식 채널 참고
```

### 2. 로그인
```bash
unset ANTHROPIC_API_KEY        # Pro/Max 구독 사용을 위해
claude login                    # Claude
codex login                     # Codex (ChatGPT 계정)
gemini                          # Gemini (첫 실행 시 브라우저 인증)
```

### 3. 프로젝트 클론
```bash
git clone <repo> agent-platform && cd agent-platform
```

### 4. MCP 서버 등록
`.mcp.json`, `.gemini/settings.json` 이 커밋되어 있어 Claude/Gemini 는 자동 인식.  
Codex 는 사용자 전역 설정이라 한 번만 수동 등록:
```bash
codex mcp add agent-platform -- uv --directory ./mcp-server run agent-platform-mcp
```

### 5. Langfuse 옵저빌리티 세팅 (선택)

Docker 가 설치되어 있어야 한다.

```bash
# 1. Langfuse 서버 시작
docker compose -f docker-compose.langfuse.yml up -d

# 2. http://localhost:3000 → 계정 생성 → 프로젝트 생성 → API 키 발급

# 3. .env.local 에 키 입력
cat > .env.local <<EOF
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://localhost:3000
EOF

# 4. MCP 서버 의존성 설치 (langfuse 패키지 포함)
cd mcp-server && uv sync && cd ..
```

키가 없으면 모든 Langfuse 계측은 no-op으로 동작하며 워크플로우에 영향 없음.

### 6. 연결 확인
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

생성 후 agent-platform 워크플로우로 개발하려면 **방식 1** 으로 이어서 진행.

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
[Orchestrator]  (haiku)
     ↓
[@planner]      (haiku)  ──► PRD.md, TASK.md
     ↓
[@backend]      (opus)   ──► src/, API-SPEC.md, DECISIONS.md
     ↓
    ┌──────────────────────────────────────┐
    ▼                                      ▼
[@reviewer] (haiku)               [@security] (haiku)
Gemini → REVIEW.md                Gemini → SECURITY-AUDIT.md
    │                                      │
    └────────────────┬─────────────────────┘
                     ↓ 둘 다 approved + HIGH/Critical 0건
              [@qa]  (haiku)  ──► TEST-PLAN.md, 테스트 코드
                     ↓ P0/P1 결함 없음
              [@cicd] (haiku) ──► PR-BODY.md, RELEASE-NOTE.md, DEPLOY-CHECKLIST.md
```

- `@reviewer` 가 HIGH 이슈 탐지 → Backend 반려
- `@security` 가 Critical/High 탐지 → Backend 반려 + hotfix 권장
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

---

## MCP 툴 목록 (16종)

| 툴 | 기능 | 내부 동작 |
|---|---|---|
| `project_init` | Kotlin/Spring 프로젝트 생성 | 스켈레톤 클론 → 버전·패키지·의존성 교체 |
| `feature_scaffold` | feature 디렉터리 + PRD/TASK 생성 | 파일 복사 + Front-matter 치환 |
| `feature_list_artifacts` | feature 내 파일별 agent/status 요약 | `docs/features/<name>/*.md` 스캔 |
| `feature_gate_check` | Front-matter·링크·선행조건 검증 | Agent별 prerequisite 매핑 |
| `handoff_validate` | Agent 전환 사전 게이트 | `gate_check` + from_agent 산출물 검증 |
| `log_append` | `claude_log.md` 타임스탬프 기록 | — |
| `plan_run_gemini` | Gemini CLI 로 PRD/TASK 생성 | `gemini --approval-mode plan` (planner 기본) |
| `review_run_gemini` | Gemini CLI 로 코드 리뷰 → REVIEW.md | `gemini --approval-mode plan` + Langfuse span (reviewer 기본) |
| `review_run_codex` | Codex CLI 로 코드 리뷰 → REVIEW.md | `codex exec --full-auto` + Langfuse span (reviewer 대안) |
| `audit_run_gemini` | Gemini CLI 로 보안 감사 → SECURITY-AUDIT.md | `gemini --approval-mode plan` + Langfuse span |
| `qa_run_gemini` | Gemini CLI 로 QA → TEST-PLAN.md | `gemini --approval-mode plan` + Langfuse span (qa 기본) |
| `qa_run_codex` | Codex CLI 로 QA → TEST-PLAN.md | `codex exec --full-auto` + Langfuse span (qa 대안) |
| `release_run_gemini` | Gemini CLI 로 CICD 산출물 생성 | `gemini -m gemini-2.5-flash --approval-mode auto_edit` + Langfuse span |
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
| `PreToolUse` | (전체) | `scripts/langfuse-hook.sh pre` — tool 시작 시각, span id, trace id 상태 저장 |
| `PreToolUse` | `Bash` | `rm -rf /`, `curl`, `sudo rm`, `DROP DATABASE` 등 차단 |
| `PostToolUse` | `Edit\|Write` | `.kt` 변경 시 `ktlintCheck` 자동 실행 / feature 문서 Front-matter 누락 경고 |
| `PostToolUse` | (전체) | `scripts/langfuse-hook.sh post` — 모든 tool call 의 요약 메타데이터와 duration 을 Langfuse span 으로 기록 |
| `UserPromptSubmit` | — | `API_KEY=...` 등 시크릿 패턴 차단 |
| `Stop` | — | `claude_log.md` 세션 종료 스탬프 + `scripts/langfuse-stop-hook.sh` — 세션 trace 전송 |
| `SessionStart` | — | MCP 서버 health check — 실패 시 경고 |

커스텀 Hook 추가 시 `jq` 로 stdin JSON 파싱, `{"decision":"block","reason":"..."}` 로 차단.

---

## 옵저빌리티 (Langfuse)

Claude Code + Codex + Gemini 의 모든 tool call 과 subprocess 실행을 Langfuse self-hosted 로 추적한다. 원문 payload 대신 요약 메타데이터와 timing 만 전송한다.

### 계측 경로

| 경로 | 커버 범위 | 구현 위치 |
|---|---|---|
| Claude Code hooks | 7개 Agent 의 모든 tool call 요약, start/end/duration, 세션 trace | `scripts/langfuse-hook.sh`, `langfuse-stop-hook.sh` |
| MCP 서브프로세스 span | Codex·Gemini CLI 실행 시간, exit code, stdout/stderr 길이 요약, hook trace 연계 | `tools/review.py`, `audit.py`, `qa.py`, `release.py` |

### Langfuse 세팅

```bash
# 1. Langfuse 서버 시작
docker compose -f docker-compose.langfuse.yml up -d

# 2. http://localhost:3000 → 계정 생성 → API 키 발급

# 3. .env.local 에 키 입력
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://localhost:3000

# 4. MCP 서버 의존성 설치
cd mcp-server && uv sync
```

### Prompt Management (선택)

Langfuse UI → Prompts 에서 다음 이름으로 템플릿을 등록하면 코드 재배포 없이 프롬프트를 업데이트할 수 있다. 미등록 시 코드 내 fallback 프롬프트가 자동 사용된다.

| 프롬프트 이름 | 사용 도구 | 변수 |
|---|---|---|
| `gemini-review` | `review_run_gemini`, `review_run_codex` | `feature`, `feature_dir`, `focus`, `focus_desc`, `source_hint` |
| `gemini-audit` | `audit_run_gemini` | `feature`, `feature_dir`, `scope`, `scope_desc`, `source_hint` |
| `gemini-qa` | `qa_run_gemini`, `qa_run_codex` | `feature`, `feature_dir`, `scope`, `scope_desc`, `source_hint` |
| `gemini-release` | `release_run_gemini` | `feature`, `feature_dir`, `action`, `action_desc`, `pr_body_file`, `release_file`, `checklist_file` |

> Langfuse 키가 없으면 모든 계측은 no-op 으로 동작하며 기존 워크플로우에 영향 없음.
>
> 보안 기본값:
> raw `tool_input` / `tool_output` / CLI prompt / stdout / stderr 원문은 전송하지 않는다.
> Langfuse 에는 top-level key 목록, 크기, 오류 여부, duration 같은 요약값만 남긴다.

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
├── PR-BODY.md            # @cicd
├── RELEASE-NOTE.md       # @cicd
├── DEPLOY-CHECKLIST.md   # @cicd
└── bugs/BUG-*.md         # @qa (결함 발견 시)
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

## 로드맵

### 완료
- Claude Code Hooks (보안 차단, 린트, 세션 로그)
- Slash Commands 5종 (`/new-feature`, `/gate-check`, `/handoff`, `/retrospective`, `/init-project`)
- MCP 서버 16개 툴 (feature lifecycle, CLI 래핑, 로그)
- reviewer / security Agent (Codex·Gemini 교차 검증)
- `handoff_validate` 기반 Quality Gate 자동 검증
- **Langfuse self-hosted 옵저빌리티** (Phase 1–4)
  - Docker Compose 기반 Langfuse 서버
  - Claude Code PostToolUse / Stop hook → trace·span 전송
  - MCP 서브프로세스(Codex·Gemini) Langfuse span 주입
  - Prompt Management — Langfuse 템플릿 fetch + fallback

### 예정
- MCP progress notification (장시간 리뷰 중 사용자 피드백)
- `examples/sample-feature/` 완전한 E2E 예제
- `standards/observability.md`, `standards/error-catalog.md` 추가
- GitHub Actions 에서 MCP 서버 자동 테스트
- **Langfuse Phase 5**: hook↔SDK trace 상관관계 통합 (OTel 경로)

---

## 라이선스
내부 사용. 팀 표준에 맞춰 수정/확장 자유.
