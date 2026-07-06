# Agent Platform

Codex/Gemini/Claude 실행 backend와 MCP 서버로 대상 백엔드 프로젝트의 기획 → 개발 → 리뷰 → 보안 → QA → 릴리스 흐름을 조율하는 팀 공통 워크플로우 플랫폼.

이 repository의 MCP 서버는 Python/FastMCP로 구현되어 있다. Kotlin/Java Spring WebFlux와 Hexagonal Architecture 규칙은 이 플랫폼이 생성·지원하는 target project에 적용된다.

## 핵심 정책
- 산출물은 `{TARGET_PROJECT}/docs/<type>/<name>/` 에 저장한다 (`<type>`: features/fix/refactor 등).
- `TARGET_PROJECT` 는 `agent-platform/.active-project` 에 기록된 절대 경로다.
- 활성 target project가 없으면 산출물 관련 MCP 툴은 에러를 반환한다 — agent-platform repo로 fallback하여 쓰지 않는다.
- Backend 기본 CLI는 Claude Code; 사용자 요청 시 `[AI: codex]` 또는 `[AI: gemini]`로 전환한다.
- Codex/Gemini는 standalone agent runner(`agent-platform-agent`)로도 실행할 수 있다.
- Reviewer는 지정된 AI backend 하나로 실행하고, `REVIEW.md` 형식은 backend에 종속되지 않는다.

## 구조
```text
agent-platform/
├── CLAUDE.md                 # Claude 자동 로드 공통 정책
├── AGENTS.md                 # Codex 자동 로드 thin guide
├── GEMINI.md                 # Gemini 자동 로드 thin guide
├── .agent-config.json        # 기본 CLI/model 정책
├── .claude/agents/           # 7개 Subagent 정의
├── .claude/commands/         # Slash commands
├── mcp-server/               # Python FastMCP server
├── standards/                # 코드/API/테스트/보안/커밋 표준
├── templates/                # 산출물 front-matter 템플릿
├── workflows/                # feature/hotfix gate 흐름
└── standards/reference/      # 상세 운영 레퍼런스
```

## 빠른 시작
```bash
brew install uv jq
npm install -g @anthropic-ai/claude-code
claude login
```

Claude/Gemini는 repo의 `.mcp.json`, `.gemini/settings.json`을 사용할 수 있다. Codex는 한 번만 등록한다.

```bash
codex mcp add agent-platform -- uv --directory ./mcp-server run agent-platform-mcp
```

Target project 쓰기 범위는 allowlist로만 결정한다. 로컬 전용 `.agent-platform.env` 파일이나 MCP 실행 환경에 허용 루트를 설정한다.

```bash
AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS="/path/to/projects:/path/to/another-project-root"
```

Claude Code 권한은 `.agent-platform.env` 기준으로 `.claude/settings.local.json`에 동기화된다. 파일은 SessionStart hook에서 자동 갱신되며, 수동 실행도 가능하다.

```bash
python3 scripts/sync_claude_settings.py
```

phase 진행 기록은 TASK.md 체크박스와 conventional commit이 공식 기록이다 (구 `claude_log.md`/`log_append` 체계는 제거됨). 관찰성은 Claude Code native OTel/transcript로 대체되었다 — `PROMPT/observability-otel-guide.md` 참조.

테스트:

```bash
uv --directory ./mcp-server run python -m unittest discover -s ../tests -v
uv --directory ./mcp-server run --dev python -m pytest -q ../tests
```

Claude 없이 standalone agent 실행:
```bash
uv --directory ./mcp-server run agent-platform-agent new-feature payment-cancel
uv --directory ./mcp-server run agent-platform-agent run planner payment-cancel --ai codex --requirements "결제 취소 API 구현"
uv --directory ./mcp-server run agent-platform-agent run backend payment-cancel --ai codex
uv --directory ./mcp-server run agent-platform-agent run backend payment-cancel --ai gemini
uv --directory ./mcp-server run agent-platform-agent run reviewer payment-cancel --ai codex
uv --directory ./mcp-server run agent-platform-agent run security payment-cancel --ai gemini
uv --directory ./mcp-server run agent-platform-agent gate-check payment-cancel
```

신규 target project:
```text
> /init-project my-service com.example.myservice
> /new-feature payment-cancel
> @planner PRD 작성
> @backend 구현
> @reviewer @security 교차 검증
> /handoff qa payment-cancel
> @qa 테스트
> @cicd PR 준비
```

## 기본 흐름
```text
planner
  -> PRD.md, TASK.md
backend
  -> code, API-SPEC.md, DECISIONS.md
reviewer + security
  -> REVIEW.md, SECURITY-AUDIT.md
qa
  -> TEST-PLAN.md, optional test code / BUG docs
cicd
  -> PR-BODY.md, RELEASE-NOTE.md, DEPLOY-CHECKLIST.md, PR
```

## Slash Commands
| Command | Purpose |
|---|---|
| `/init-project <name> <pkg> [opts]` | target project 생성 |
| `/new-feature <name>` | feature 산출물 scaffold |
| `/gate-check <name>` | front-matter/gate 검증 |
| `/handoff <next-agent> <feature>` | 다음 Agent로 handoff |
| `/retrospective <feature>` | 회고 초안 생성 |

## Reference
- 설치/로컬 설정: `standards/reference/setup.md`
- MCP tool 목록: `standards/reference/mcp-tools.md`
- Backend phase 상세: `standards/reference/backend-phase-flow.md`
- CICD/릴리스 정책: `standards/reference/cicd-release-policy.md`
- Feature flow: `workflows/feature-flow.md`
- Hotfix flow: `workflows/hotfix-flow.md`

## 산출물 예
```text
{TARGET_PROJECT}/docs/features/payment-cancel/
├── PRD.md
├── TASK.md
├── API-SPEC.md
├── DECISIONS.md
├── REVIEW.md
├── SECURITY-AUDIT.md
├── TEST-PLAN.md
├── PR-BODY.md
├── RELEASE-NOTE.md
├── DEPLOY-CHECKLIST.md
└── bugs/BUG-*.md
```

## License
Internal use. 팀 표준에 맞춰 수정·확장한다.
