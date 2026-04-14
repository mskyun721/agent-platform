# Agent Platform

**Claude Code + Codex CLI + Gemini CLI 를 MCP 서버로 통합한 팀 공통 개발 워크플로우 플랫폼.**

기획 → 백엔드 개발 → 코드 리뷰 → 보안 감사 → QA → CI/CD 의 6단계 워크플로우를 7개 Subagent 로 자동화한다. 외부 CLI 는 전용 구독(ChatGPT Plus, Gemini) 으로 실행되어 **별도 API 과금 없음**.

## 주요 특징
- **멀티 CLI 협업**: Claude 가 기본, Codex 가 코드 리뷰, Gemini 가 보안 감사를 담당
- **MCP 서버 허브**: 공용 툴(스캐폴딩, Quality Gate, 외부 CLI 래핑) 을 단일 MCP 서버가 제공
- **헥사곤 아키텍처 강제**: Backend Agent 가 도메인/애플리케이션/어댑터 구조를 자동 준수
- **Front-matter 기반 워크플로우**: 산출물 상태 (`draft → review → approved`) 로 Handoff 게이팅
- **Hook 기반 보안 강제**: 위험 명령 차단, 시크릿 필터링, 자동 린트
- **Slash Command**: `/new-feature`, `/gate-check`, `/handoff`, `/retrospective`

---

## 구성
```
agent-platform/
├── CLAUDE.md                      # 프로젝트 전역 지침
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
│   │   └── retrospective.md
│   └── settings.json              # Hook (보안 차단, 린트, MCP health check)
├── .mcp.json                      # Claude 의 MCP 서버 등록
├── .gemini/settings.json          # Gemini 의 MCP 서버 등록
├── mcp-server/                    # Python + uv + mcp[cli] MCP 서버
│   └── src/agent_platform_mcp/
│       ├── server.py              # FastMCP 엔트리
│       ├── config.py              # 경로/Agent 상수
│       ├── frontmatter.py
│       └── tools/                 # 10개 MCP 툴
│           ├── feature.py         # scaffold / list / gate_check
│           ├── handoff.py         # validate
│           ├── review.py          # run_codex
│           ├── audit.py           # run_gemini
│           ├── standards.py       # read / list
│           └── log.py             # append
├── standards/                     # 팀 공통 표준 (단일 진실 소스)
├── templates/                     # 산출물 템플릿 10종
├── workflows/                     # Handoff 플로우
├── docs/features/<name>/          # 실제 산출물 저장소
└── PLAN/                          # 로드맵·Phase 리포트 (개인 작업 영역, gitignored)
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
claude mcp list        # agent-platform: ✓ Connected 표시되어야 함
codex mcp list         # agent-platform: enabled
```

---

## 기본 사용법

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
| `/new-feature <name>` | feature 스캐폴딩 | `/new-feature payment-cancel` |
| `/gate-check [name]` | Front-matter·링크 검증 | `/gate-check` 또는 `/gate-check payment-cancel` |
| `/handoff <next> <feature>` | Quality Gate 후 다음 Agent 호출 | `/handoff qa payment-cancel` |
| `/retrospective <feature>` | 회고 문서 생성 | `/retrospective payment-cancel` |

- `.claude/commands/` 에 파일 하나 = 명령 하나
- Front-matter 의 `allowed-tools` 로 도구 제한
- 내부는 MCP 툴 호출 + 파일 fallback 패턴

---

## MCP 툴 목록 (10종)

| 툴 | 기능 | 내부 동작 |
|---|---|---|
| `feature_scaffold` | feature 디렉터리 + PRD/TASK 생성 | 파일 복사 + Front-matter 치환 |
| `feature_list_artifacts` | feature 내 파일별 agent/status 요약 | `docs/features/<name>/*.md` 스캔 |
| `feature_gate_check` | Front-matter·링크·선행조건 검증 | Agent별 prerequisite 매핑 |
| `handoff_validate` | Agent 전환 사전 게이트 | `gate_check` + from_agent 산출물 검증 |
| `log_append` | `claude_log.md` 타임스탬프 기록 | — |
| `review_run_codex` | Codex CLI 로 코드 리뷰 | `codex exec` 서브프로세스 |
| `audit_run_gemini` | Gemini CLI 로 보안 감사 | `gemini -p --approval-mode plan` |
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

## 커스터마이징

### 기술 스택 변경
`standards/` 파일만 수정. Agent 는 `standards/` 를 참조하므로 Agent 파일 직접 수정 불필요.

### 새 Agent 추가
1. `.claude/agents/<name>.md` 작성
2. `mcp-server/src/agent_platform_mcp/config.py` 의 `VALID_AGENTS`, `AGENT_OUTPUTS`, `AGENT_PREREQUISITES` 에 추가
3. `workflows/*.md` 에 Handoff 지점 편집

### 새 MCP 툴 추가
1. `mcp-server/src/agent_platform_mcp/tools/<name>.py` 작성
2. `server.py` 에 `@mcp.tool()` 데코레이터로 등록
3. Agent `tools:` 필드 또는 Slash Command `allowed-tools` 에 `mcp__agent-platform__<tool>` 명시

### 외부 CLI 교체 (예: Reviewer 를 Gemini 로)
`mcp-server/src/agent_platform_mcp/tools/review.py` 의 subprocess 명령을 `gemini -p` 로 교체. Agent 정의 변경 불필요.

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `/agents` 에 Subagent 미표시 | Front-matter 오류 | `.claude/agents/*.md` Front-matter 검증 |
| `claude mcp list` 에 서버 없음 | `.mcp.json` 미커밋 | 프로젝트 루트에서 `claude mcp add` 재실행 |
| MCP 서버가 `connecting...` 에서 멈춤 | `uv` 미설치 또는 Python 3.11 미만 | `brew install uv`, `uv python install 3.11` |
| `review_run_codex` 타임아웃 | Codex 응답 지연 | `timeout_sec` 인자 증가 또는 `dry_run: true` 확인 |
| `audit_run_gemini` 가 429 반환 | 무료 쿼터 소진 | 유료 업그레이드 또는 잠시 대기 (MCP 는 stderr 로 노출하지만 exit 0 반환) |
| API 과금이 청구됨 | `ANTHROPIC_API_KEY` 환경변수 존재 | `unset ANTHROPIC_API_KEY` 후 `claude login` 재실행 |
| Gemini 인증 만료 | 구독 세션 만료 | `gemini` 실행하여 재인증 |

---

## 문서 분류 규칙

| 위치 | 용도 |
|---|---|
| `docs/features/<name>/` | Agent 산출물 (PRD / API-SPEC / REVIEW 등) |
| `standards/` | 팀 공통 표준 |
| `templates/` | 산출물 템플릿 |
| `workflows/` | Agent 간 Handoff 플로우 |
| `PLAN/` | 개인 작업 영역 (로드맵·Phase 리포트), **gitignore** |
| `CLAUDE.md` | 프로젝트 지침 (Claude 자동 로드) |
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
