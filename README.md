# Agent Platform

Codex/Claude 실행 backend와 MCP 서버로 대상 백엔드 프로젝트의 기획 → 개발 → 리뷰 → 보안 → QA → 릴리스 흐름을 조율하는 팀 공통 워크플로우 플랫폼.

이 repository의 MCP 서버는 Python/FastMCP로 구현되어 있다. Kotlin/Java Spring WebFlux와 Hexagonal Architecture 규칙은 이 플랫폼이 생성·지원하는 target project에 적용된다.

## 핵심 정책
- 산출물은 `{TARGET_PROJECT}/docs/<type>/<name>/` 에 저장한다 (`<type>`: features/fix/refactor 등).
- `TARGET_PROJECT` 는 `agent-platform/.active-project` 에 기록된 절대 경로다.
- 활성 target project가 없으면 산출물 관련 MCP 툴은 에러를 반환한다 — agent-platform repo로 fallback하여 쓰지 않는다.
- 플랫폼 자체 개선은 feature/gate/handoff의 `root` 또는 CLI `--root`로 플랫폼 루트를 명시한다. `.active-project`는 변경하지 않으며 외부 프로젝트 allowlist는 유지된다.
- Backend 기본 CLI는 Claude Code; 사용자 요청 시 `[AI: codex]`로 전환한다.
- Codex는 standalone agent runner(`agent-platform-agent`)로도 실행할 수 있다.
- Reviewer는 지정된 AI backend 하나로 실행하고, `REVIEW.md` 형식은 backend에 종속되지 않는다.

## 구조
```text
agent-platform/
├── AGENTS.md                 # 공통 정책 단일 소스 (Codex 자동 로드)
├── CLAUDE.md                 # Claude 자동 로드, @AGENTS.md import + Claude 전용
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

Claude는 repo의 `.mcp.json`을 사용한다. Codex는 한 번만 등록한다.

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

작업 진행은 WORK.md 또는 TASK.md와 commit에 기록한다. 실행 관측은 ignored `.local/state.db`에 메타데이터로 저장한다. 체크포인트·재개·사용량의 범위는 [관측 계약](standards/reference/run-events.md)과 [중단 복구](standards/reference/run-recovery.md)를 따른다.

## Hooks
`.claude/settings.json`에 정의된 4개 hook (Stop hook 없음 — phase 기록은 TASK.md/commit이 담당):
- `PreToolUse` (Bash): 파괴적 명령 차단 (`rm -rf /`, `DROP DATABASE` 등)
- `PostToolUse` (Edit\|Write): 파일 단위 ktlint 실행 + `docs/**/*.md` front-matter 누락 경고
- `UserPromptSubmit`: 프롬프트 내 시크릿으로 보이는 값 경고 (non-blocking)
- `SessionStart`: `scripts/sync_claude_settings.py` 로 Claude 권한 동기화

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
uv --directory ./mcp-server run agent-platform-agent run reviewer payment-cancel --ai codex
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

## 개선된 Agent 사용 순서

아래 CLI 예시는 플랫폼 루트에서 `uv --directory mcp-server run agent-platform-agent` 뒤에 붙여 실행한다.

| 단계 | 사용법 | 확인할 결과 |
|---|---|---|
| 대상 등록 | `project-register /absolute/project --verify-profile pytest` | 발급된 project ID. 프로젝트에 맞는 검증 프로필 선택 |
| 작은 작업 시작 | `new-feature fix/example --contract work-v1 --root <project-id>` | WORK.md에 목표·범위·AC·low/high 위험 기록 |
| 큰 기능 시작 | `new-feature example --root <project-id>` | PRD.md/TASK.md 계약으로 기획 후 구현 |
| 구현 | 현재 세션에 `fix/example WORK.md 기준으로 구현해줘. 대상 root는 <project-id>` | 코드·검증·결정·결과 기록 |
| 검토 | 현재 세션에 `reviewer로 fix/example 리뷰해줘. root는 <project-id>` | REVIEW.md. high 위험은 security 검토도 수행 |
| 검증 | `gate-check fix/example --root <project-id> --verify --verify-profile pytest --evidence` | 테스트 결과, AC 증거, 승인 유효성, 인계 가능 여부 |
| 릴리스 준비 | 현재 세션에 `cicd로 fix/example 릴리스 준비해줘. root는 <project-id>` | PR-BODY.md·RELEASE-NOTE.md·DEPLOY-CHECKLIST.md |

기획은 아래처럼 요청한다:

```text
planner로 payment-cancel 기획해줘. 대상 root는 <project-id>.
요구사항: 결제 후 24시간 이내 전액 취소, 중복 취소는 기존 결과 반환.
```

기획 단계에서 다음 산출물을 `docs/features/payment-cancel/`에 작성한다.

| 파일 | 내용 |
|---|---|
| PRD.md / TASK.md | 요구사항·수락 조건 / 구현·검증 작업 계획 |
| API-SPEC.md | 메서드·경로·operationId·권한·요청/응답 예시·오류·멱등성 |
| openapi.yaml | API 변경 시 작성하는 OpenAPI 3.1 계약 |
| FLOW.md | Mermaid flowchart로 표현한 정상·실패·조건 분기와 BR/AC 매핑 |

필요하면 FLOW.md에 외부 연동 sequenceDiagram과 상태 전이 stateDiagram-v2도 추가한다.
Mermaid 지원 Markdown 뷰어에서 다이어그램을 볼 수 있다. API 변경이 없으면 API-SPEC.md에
해당 없음 사유를 적고 openapi.yaml은 생략한다. 개발은 승인된 명세·흐름도를 기준으로 수행한다.
WORK 계약으로 기획을 요청하면 PRD/TASK 대신 WORK.md를 사용하고 API/흐름도 파일을 연결한다.
CLI planner의 기본 `all`과 `prd` 동작도 명세·흐름도를 포함하며 `task`는 TASK만 갱신한다.
wrapper의 `missing_artifacts`는 필수 Markdown 파일 누락을 알린다. 파일 존재만으로
내용의 완성이나 승인을 보장하지 않으며, 기본 gate는 OpenAPI 문법·Mermaid 렌더링을 자동 검증하지 않는다.

같은 AI의 역할 작업은 현재 세션에서 `standards/agents/<role>.md`를 읽고 수행한다.
WORK 계약에서는 별도 planner나 역할 wrapper를 자동 호출하지 않는다. PRD/TASK 계약에서
별도 CLI 실행이 필요하면 `run reviewer example --root <project-id> --ai codex --dry-run`으로
대상을 먼저 확인하고 `--dry-run`을 제거해 실행한다. 다른 backend는 `--ai claude`로 선택한다.
원본 산출물은 draft이며 담당 검토 후 approved/rejected로 갱신한다. 테스트 성공은 문서 승인이 아니다.
플랫폼 자체 작업은 `--root "$PWD"`를 명시하고 `.active-project`를 유지한다.

직접 세션의 실행 관측과 중단 복구:

```text
state start fix/example --role backend --backend codex --root <project-id>
state checkpoint <run-id> --phase implementation --next-action "남은 테스트 실행"
state heartbeat <run-id> --pid <실제 세션 PID>
state resume <run-id>
state continue <run-id> --pid <새 세션 PID>
state end <새 run-id> completed
```

`resume`은 조회만 한다. `resumable`일 때 `continue`가 새 run ID를 만들며 이후 기록은 그 ID를 쓴다.
`diverged`이면 코드 변경을 검토하고 다시 검증한다. `running`이면 기존 프로세스를 확인한다.
부모가 `waiting`이면 자식도 대기 사유를 상속하며 `state end ... completed`로 해제되지 않는다.
반복 반려는 사용자 개입 후 담당 역할의 재검토 판정을 기록한다. 대기 해제는 실제 개입을 확인한 뒤
`state transition <run-id> running --reason "개입 결과 요약"`으로 명시한다. 이전 PID가 살아 있으면 거부된다.

push와 PR은 각각 계획하고 **실제 사용자 확인 후** 실행한다:

```text
state action-plan <run-id> push <고유키> --target-json '{"remote":"origin","branch":"fix/example","head":"<전체 커밋 SHA>"}'
state actions --run-id <run-id>
state action-confirm <action-id> --confirmed-by <확인자>
state action-execute <action-id>
state action-plan <run-id> pr <별도 고유키> --target-json '{"repository":"owner/repo","branch":"fix/example","base":"main","head":"<전체 커밋 SHA>","title":"fix: example"}'
```

PR도 별도로 `action-confirm`과 `action-execute`를 거친다. 계획 시 원격 head가 지정 SHA와
일치해야 하며 원격 base SHA를 `base_head`로 저장한다. 실행은 두 SHA를 재확인하고 그 커밋으로
500라인 검사를 수행한다. 필요한 base/head 및 merge-base Git 객체가 로컬에 없으면 먼저 해당
저장소에서 fetch해야 한다. 이전 형식의 PR 계획은 새 고유키로 다시 계획·확인한다.
생성 직전 재확인과 생성 후 SHA 검증을 수행하며, 동시 원격 변경은 `uncertain`으로 남을 수 있다.
`state action-reconcile <action-id>`로 조회하고 수동 확인한다. 불확실한 액션을 새 키로 재실행하지 않는다.
push 중복 조회·reconcile·실제 쓰기는 모두 확인한 단일 push URL을 사용한다.

자세한 제한은 [중단 복구와 외부 액션](standards/reference/run-recovery.md),
[증거 gate](standards/reference/evidence-gates.md), [역할별 흐름](standards/reference/backend-phase-flow.md)을 참고한다.

## 기본 흐름

### P0 검증과 인계

```bash
uv --directory ./mcp-server run --locked --dev python -m pytest -q ../tests
uv --directory ./mcp-server run agent-platform-agent gate-check refactor/agent-platform-evolution --root "$PWD" --verify --verify-profile platform
uv --directory ./mcp-server run agent-platform-agent list-artifacts refactor/agent-platform-evolution --root "$PWD"
```

게이트는 빈 산출물 집합을 실패 처리한다. `features/pay`와 `pay`는 같은 항목이며,
`refactor/pay` 문서의 과거 `feature: pay`는 경고로 호환한다. 중첩 경로는 마지막 이름만으로 대체하지 않는다.
문서 링크의 `docs/` prefix는 프로젝트 기준, 나머지는 문서 기준이며 절대경로·docs 밖 탈출·symlink를 거부한다.

`.agent-config.json`의 `verify_profiles`에서 명시적으로 프로필을 선택한다. argv·프로젝트 내부 cwd·양수 timeout을 검증하고 shell 없이 실행한다.
build marker는 후보만 제안한다. 기존 `gate_verify_command` 문자열은 `shell-compat`로 유지한다.
검증을 요청했지만 명령이 없으면 `not_run`, 실행 오류/timeout이면 `error`로 gate가 실패한다.
CLI `gate-check`와 `handoff`는 실패 시 종료 코드 1을 반환한다.

결과는 `artifact_status`, `verification_status`, `policy_status`를 구분한다. 정책 변경은 P0에서 보고만 하며
테스트 실행을 막지 않는다. `reviewed_hash`나 로컬 commit은 독립적인 사람 검토를 증명하지 않는다.
출력 원문은 민감정보 노출을 피하기 위해 반환하지 않으며 기존 `verify_output_tail`은 빈 문자열이다.

`handoff`/`handoff_validate`의 `purpose`는 다음과 같다.

| 목적 | 요구 조건 | 기본 코드 검증 |
|---|---|---|
| `plan_review` | planner 문서 존재·형식 유효, rejected 아님 | 실행하지 않음 |
| `implementation_complete` | 소스 승인·다음 역할 선행 산출물 | reviewer/security/qa/cicd 인계 시 실행 |
| `rework` | reviewer/security/qa의 rejected 산출물을 backend로 전달 | 실행하지 않음 |

생략 시 planner→reviewer/security는 계획 검토, reviewer/security/qa→backend는 수정 인계로 판단한다.
그 외에는 완료 인계다. `--verify`/`--no-verify`로 실행 여부를 명시할 수 있다.
P0의 정책 보고 및 `--no-verify` 경로는 릴리스 승인 증거를 대신하지 않는다.

읽기 전용 통계: `uv --directory mcp-server run python ../scripts/docs_stats.py --root /allowed/project`.
관측 대상 문서의 읽기 권한을 확인한 뒤 실행한다. 통계 명령은 빌드나 테스트를 실행하지 않는다.
평가 fixture의 준비·판정·기록은 [evals/README.md](evals/README.md)를 따른다.
CI는 추적되는 `mcp-server/uv.lock`으로 설치하고 같은 테스트 명령을 사용한다.

### 역할 흐름
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
| `/gate-check <name>` | front-matter/gate 검증 (`fix/`\|`hotfix/`는 PRD+REVIEW 경량 트랙; `verify` 옵션으로 `.agent-config.json`의 `gate_verify_command` 실행 결과를 게이트에 반영) |
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
# 단일 작업 기록 (P1, 선택 기능)

작은 작업은 기존 PRD/TASK 대신 `WORK.md` 한 개로 시작할 수 있다.

```bash
agent-platform-agent new-feature fix/small-change --contract work-v1 --root /absolute/project
agent-platform-agent gate-check fix/small-change --agent backend --root /absolute/project
```

MCP는 `feature_scaffold(name="fix/small-change", root="/absolute/project", contract="work-v1")`를 사용한다.
옵션을 생략하면 기존 PRD/TASK 생성 동작을 유지한다. `.active-project`는 변경하지 않는다.
WORK에는 목표·범위·위험·검증·결정·결과를 기록하며 최초 위험도는 `undecided`라 gate가 실패한다.
판단 후 `low`/`high`로 지정하고, high에는 `risk_reason`을 작성한다.
승인된 WORK로 backend에 인계하고, 검토 시 REVIEW.md를 추가한다.
high 작업은 QA/릴리스 인계 전에 승인된 SECURITY-AUDIT.md가 필요하다.
구현 완료 검토의 실제 검증 요구는 유지된다. 문서 형식 통과만으로 작업 완료를 뜻하지 않는다.

현재는 명시적 선택 및 직접 세션용이다. 역할 wrapper는 기존 문서 계약을 유지한다.
코드 변경 후 승인 무효화(P5), 500라인 자동 검사는 아직 미구현이다.

## 위험 교차 검사 (P1)

`tests/test_work_lifecycle.py`는 임시 Git 프로젝트에서 CLI scaffold, draft 인계 제한,
실제 unittest 실패, 반려, 코드 수정, 재검증·완료 인계를 실행한다.
테스트 fixture의 승인은 시뮬레이션이며 실제 AI 세션이나 사람 검토 완료를 뜻하지 않는다.

게이트는 선언된 `risk`와 실제 변경 경로를 대조해 결과의 `risk` 키로 보고한다.
- 대상 경로: `.agent-config.json` `risk_rules.paths` (fnmatch, 기본: `**/auth/**`, `**/security/**`, `**/migration/**`, `**/*Secret*`, `**/api/v*/**`)
- 기본 변경 경로: staged + unstaged + untracked 파일 (`scope: pending-only`). 첫 커밋 전 staged 파일도 포함한다.
- PR 검토에서는 `--risk-base <기준 브랜치 또는 커밋>`을 지정한다. HEAD와 기준 revision의 merge-base부터 커밋된 변경과 미커밋 변경을 합친다 (`scope: branch-and-pending`). 자동 fetch는 하지 않는다.
- `conflict` — `risk: low` 인데 대상 경로가 걸림 → **게이트 실패**
- `ok` — 지정 범위의 경로와 선언에 모순이 없음. 업무 로직의 안전성 승인이나 전체 PR 검증을 뜻하지 않는다.
- `undeclared` — legacy PRD/TASK 계약처럼 선언이 없음 → 보고만, 자동 강등·차단 없음
- 단, 명시적으로 요청한 `--risk-base` 검사가 실패하면 legacy도 차단한다.
- `unverified` — Git 조회 실패/timeout, 잘못된 기준 revision, 규칙 누락/오류 → **선언된 위험의 gate와 handoff 차단**. 프로젝트는 Git 작업 트리 루트여야 한다.
- `invalid` — 위험 선언이 low/high가 아니거나 high의 사유가 없음 → **게이트 실패**.

```bash
agent-platform-agent gate-check fix/small-change --root /absolute/project --risk-base origin/main --verify --verify-profile pytest
```

MCP의 `feature_gate_check`와 `handoff_validate`에도 `risk_base="origin/main"`을 전달한다.
기준 revision을 지정하지 않으면 커밋된 변경은 검사하지 않는다. 완료 검토 시 실제 PR 기준을 명시한다.
경로 패턴은 보조 증거다. 인증·권한·데이터·공개 계약·파괴적 변경은 경로 미일치라도 high로 선언한다.
legacy PRD에 high를 선언한 경우도 QA/cicd 인계 전 보안 검토가 필요하다.

## 프로젝트 ID와 Worktree (P2)

```bash
agent-platform-agent project-register /absolute/project --verify-profile pytest
agent-platform-agent project-list
agent-platform-agent gate-check fix/small-change --root project-<발급된ID> --verify
agent-platform-agent project-rebind project-<발급된ID> /absolute/moved-project
agent-platform-agent project-unregister project-<발급된ID>
```

기본 ID는 UUID 기반이며 `--project-id service-a`로 명시할 수도 있다. basename으로 자동 병합하지 않는다.
등록·재연결·실행 때 allowlist를 검사하며 `.active-project`와 전역 환경은 변경하지 않는다.
기존 `--root /absolute/path`도 계속 지원한다. 등록된 프로젝트는 gate의 기본 검증 프로필을 제공하고
명시한 `--verify-profile`이 우선한다. 프로필 실행은 여전히 `--verify` 또는 인계의 검증 요청이 있어야 한다.

실제 Git common directory가 같은 worktree는 같은 ID를 사용하되, `--root <worktree 경로>`에서 실행한다.
복제 저장소는 자동 연결하지 않는다. 이동한 프로젝트는 `project-rebind`로 새 경로를 명시한다.
등록 해제는 메타데이터만 삭제하고 코드·산출물·worktree는 보존한다.
`.agent-projects.json`은 ignored 로컬 상태다. 원자적 교체와 POSIX 파일 잠금으로 동시 등록을 보호한다.
쓰기 기능의 지원 범위는 macOS/Linux이며 다른 OS는 읽기 경로만 제공한다.
신규 MCP 도구는 `project_register`, `project_list`, `project_rebind`, `project_unregister`다.
ID/root 연결은 scaffold/list/gate/handoff와 역할 wrapper 6종에 적용된다.
`agent-platform-agent run reviewer <feature> --root <project_id 또는 경로> --dry-run`으로 대상과 프롬프트를 확인한다.
MCP의 plan_run/backend_run/review_run/audit_run/qa_run/release_run도 root를 받는다.
실행 시작에 context를 한 번 해석하여 프롬프트·cwd·산출물 후처리에 동일하게 사용한다.

## 모델 지정

Wrapper 프롬프트는 공통 정책의 Core Policy/Security Baseline/Constraints 절과 현재 작업 문서의 제목·상태를 포함한다.
리뷰·보안 wrapper는 필수 제목/헤딩과 CLI 종료 코드를 검증한다. 잘못된 출력은 `artifact_invalid: true`인
`draft` 안내 문서로 대체하며, gate-check는 승인 상태와 무관하게 이를 차단한다. 정상 출력도 자체 승인하지 않는다.
이 두 wrapper는 오류 stdout과 stderr 원문을 저장·반환하지 않으며 별도 raw 보관 옵션은 제공하지 않는다.
정상 보고서는 CLI 배너와 알려진 비밀값 패턴을 마스킹한다. `masked_lines`는 변경/제거한 줄 수이며,
패턴 마스킹이 모든 비밀값 제거를 보장하지는 않으므로 담당자의 검수는 계속 필요하다.
문서 본문이나 다른 작업 문서를 자동 주입하지 않는다. `prompt_sources`에서 출처를 확인할 수 있다.
현재 문서는 최대 40개, 제목은 240자이며, 내부 `runner.context_block`의 명시적 결정 경로는 최대 3개다.
관련 결정의 자동 검색은 하지 않으며 wrapper의 기본 추가 참조 목록은 비어 있다.

로컬 스킬 패키지는 `agent-platform-agent skill add|list|enable|disable|remove`로 관리한다.
`skill enable <id> <project-id>`는 등록된 프로젝트의 Claude `.claude/skills`, Codex `.agents/skills`에 복사한다.
`skill disable`은 관리 복사본만 제거하며 사용자 수정본은 보존하고 미완료로 보고한다. 적용은 다음 세션 기준이다.
설치 스크립트를 실행하지 않으며 의존 중이거나 수정된 패키지를 덮어쓰거나 제거하지 않는다.
패키지 형식과 소유권은 [스킬 관리](standards/reference/skill-management.md)를 따른다.

P2 이벤트 계약은 `agent_platform_mcp.events`와 [run-events](standards/reference/run-events.md)에 정의돼 있다.
P4 저장소 구현은 `.local/state.db` SQLite를 사용한다. `AGENT_PLATFORM_STATE_DB`로 별도 `.db` 경로를 지정할 수 있다.
동일 이벤트/판정 ID 재전송을 중복 집계하지 않으며, 다른 내용으로 ID를 재사용하면 거부한다.
역할 wrapper의 실제 실행·종료, 검증, 인계는 메타데이터를 자동 기록하며 dry-run은 기록하지 않는다.
`.agent-config.json`의 `observability.enabled: false`로 자동 수집을 끌 수 있다. 저장 실패는 `observability.stored: false`로 표시하고 개발 실행은 계속한다.
직접 세션에서는 `agent-platform-agent state start <task> --role backend --backend codex --root <project-id>`와
`state end <run-id> completed`를 사용한다. `state runs`, `state review-status <task> --project-id <id>`로 조회한다.
중단 복구는 `state checkpoint <run-id> --phase implementation --next-action "run tests"`로 기록하고
`state resume <run-id>`로 확인한다. 등록된 원래 workspace의 코드 변경·프로세스를 검사하며 실제 재개나 외부 액션을 실행하지 않는다.
직접 세션의 실제 실행 PID는 `state heartbeat <run-id> --pid <pid>`로 갱신한다. CLI 명령 자체의 짧은 PID를 기록하지 않는다.
같은 상태의 중복 전이는 기존 PID·heartbeat를 보존하며 실행 소유권을 초기화하지 않는다.
검증 정책의 승인 해시는 실행기·관측·프로젝트 식별·문서 파서 코드도 포함하므로, 해당 코드 변경 후 이전 승인을 재사용하지 않는다.
판정과 제한은 [중단 복구](standards/reference/run-recovery.md)를 따른다. 자동 실행은 기본 off이며 현재는 수동 체크포인트 경로만 제공한다.
`state continue <run-id> --pid <new-session-pid>`는 변경 없는 체크포인트를 새 실행 ID에 연결한다. 이전 실행 기록은 보존하고 중복 claim은 새 실행을 만들지 않는다.
Codex wrapper는 실제 자식 PID를 heartbeat로 기록하고 timeout/중단 시 자식 프로세스 그룹을 정리한다.
검증 재시도는 `retry.verification: {"max_attempts": 1, "max_minutes": 15}`가 기본이다.
명시한 최대 5회·60분 이내에서만 재실행하며 각 시도의 검증 기록을 남긴다. 예산 소진 시 `waiting`으로 전환한다.
외부 액션 원장은 명시적 확인과 idempotency key를 요구한다. 원격 조회 후 중복을 건너뛰며, 쓰기 결과가 불확실하면 재실행하지 않는다.
`state actions`, `state action-plan`, `state action-confirm`, `state action-execute`를 사용한다. CLI 실행 adapter는 일반 push와 draft PR만 지원한다.
push 대상 변경을 감지하고 PR은 명시한 owner/repository와 순수 로직 크기 검사를 거친다. 외부 액션의 실제 실행은 사용자 확인 후에만 가능하다.
리뷰 판정은 `state review-record --help` 또는 `review_result_record` MCP로 별도 기록한다. 등록 프로젝트와 재전송에 동일한 decision_id가 필요하다.
CLI 종료는 승인/반려가 아니다. reviewer/security/qa 반려는 역할별로 누적되며 그 역할의 승인만 초기화한다.
미수집 토큰은 null이다. Codex wrapper는 `--json`의 확인된 turn.completed 필드만 수집한다.
input/cache-read/cache-write/output을 구분하며 reasoning 토큰을 output에 별도로 더하지 않는다. 직접 세션과 미지원/모호한 출력은 usage unavailable이다.
`state usage`는 알려진 필드 합계와 누락 수를 별도로 표시한다. `state export --out <new.json>`,
`state import <export.json>`, `state prune --retention-days 180`으로 이동·정리한다. 내보내기는 기존 파일을 덮어쓰지 않는다.
진행 중 실행과 리뷰 이력에 연결된 실행은 prune에서 보존한다. 자동 삭제는 하지 않는다.
가격은 수동 설정이며 실행 시작의 snapshot을 보존한다. 미설정 가격/캐시 의미/사용량은 비용 null로 표시한다.
설정 예시는 [관측 계약](standards/reference/run-events.md)의 가격 절을 따른다.

증거 검증은 `gate-check <task> --root <id> --verify --verify-profile <profile> --evidence`로 요청한다.
프로필 `scope.acs`에 해당 WORK/PRD의 AC ID를 명시해야 한다. 스위트 성공을 모든 AC 성공으로 자동 확장하지 않는다.
결과는 `complete/stale/incomplete/evidence_unavailable`로 구분한다. 기본 보고 모드이며,
`gate.evidence_enforced: true`이면 누락·오래된 증거·미해결 HIGH/Critical·오래된 승인을 차단한다.
현재 코드 fingerprint와 연결할 수 없는 증거는 완료 근거로 쓰지 않는다. [증거 gate](standards/reference/evidence-gates.md) 참조.
실제 AI 평가는 `uv --directory mcp-server run python ../evals/run_task.py auto --task seeded-bug --ai codex --repeat 3 --max-minutes 5`로 실행한다.
항상 전용 임시 fixture를 사용하며 `evals/summarize.py`로 표본 수·실패 원인·사용량 누락을 조회한다. [평가 절차](evals/README.md) 참조.
실제 30회 평가에서는 28회 통과했다. Claude API 추가 2회 실패를 포함한 [기준 결과](standards/reference/p5-evaluation-evidence.md)를 보존한다.
후속 v4 평가에서는 두 AI의 5개 과제 각 3회, **30/30 통과**했다. 새 기준과 원격 CI 근거는 [검증 마무리](standards/reference/evolution-closeout.md)에 정리했다.
평가기 v4는 모듈·별칭 호출과 pytest 예외 테스트도 변이 검사하며 원문 대신 실패 단계만 기록한다. assert 구문의 존재 대신 잘못된 구현을 실제 거부하는지 판정한다. 이전 평가와 과제 해시를 섞지 않는다.
개선 브랜치 push에서도 GitHub CI가 잠금 의존성 기반 전체 테스트를 실행한다.
PR 크기는 `python3 scripts/pr_logic_size.py --base <target-branch> --head <feature-branch>`로 검사한다.
merge-base 이후 커밋의 추가·삭제 로직 합계가 500라인을 넘으면 실패한다. 미커밋 변경은 포함하지 않는다.
Python은 AST/token 기준으로 import·주석·docstring을 제외하고 테스트·설정·문서는 경로 기준으로 제외한다.
다른 언어는 비어 있지 않은 줄을 보수적으로 집계하며 `manual_review_required`로 표시한다. 기능 단위 PR 분리는 담당자가 확인한다.
담당자는 `verify-profile approve <id> --reviewer <identity>`로 프로필과 검증기 코드의 검토 근거를 기록한다.
테스트 성공과 `handoff_allowed`는 별개다. 검토되지 않았거나 바뀐 검증 정책은 완료 인계를 보류하며,
`gate.policy_enforced: true`이면 gate의 passed도 false로 바뀐다. 이 작업에서 실제 프로필을 자동 승인하지는 않았다.

CLI 지원 범위와 실제 확인 근거는 [backend-capabilities](standards/reference/backend-capabilities.md)를 따른다.
P2의 실제 Claude/Codex 독립 실행 결과와 검증 범위는 [실행 증거](standards/reference/p2-execution-evidence.md)에 기록했다.
`python3 scripts/check_capabilities.py`로 모델 호출 없이 버전·도움말을 확인한다.
Codex wrapper는 설치된 CLI와 호환되는 `--sandbox workspace-write`를 사용하며 승인 우회 옵션은 추가하지 않는다.

역할별 공통 지침은 `standards/agents/<role>.md`가 원본이다. 직접 세션은 해당 원본을 읽고,
Claude adapter 본문은 아래 명령으로 생성한다. `.claude/agents/*.md` 본문을 직접 고치지 않는다.
역할 wrapper 6종도 동일 원본을 프롬프트에 포함하며 dry-run의 `prompt_sources`로 출처를 확인한다.
원본 누락·빈 파일·symlink는 실행 전에 거부한다. 역할 공유가 CLI 권한이나 출력 전송 계약을 바꾸지는 않는다.
두 AI의 독립 실행은 P2/P5 fixture로 확인했다. WORK wrapper 출력 전환은 제공하지 않으며 작은 WORK 작업은 직접 세션 경로를 사용한다.

```bash
python3 scripts/sync_claude_settings.py --agents-only
python3 scripts/sync_claude_settings.py --check
```

이 두 모드는 환경·권한 파일을 읽거나 변경하지 않는다. `--check`는 본문 차이가 있으면 exit 1이며
소유자 검토나 실제 AI 실행을 대신하지 않는다. 모델·도구 권한은 adapter front-matter에 남긴다.

Claude subagent 모델은 `.agent-config.json` `claude_models` 가 단일 출처다. SessionStart hook 의
`scripts/sync_claude_settings.py` 가 `.claude/agents/<role>.md` 의 `model:` 줄에 주입한다.
reviewer/security 는 품질 게이트이므로 `sonnet` 이 기본이다.

## P1 전환 안내 — 유지·변경·폐기

| 항목 | 상태 |
|---|---|
| `[AI: gemini]`, `cli="gemini"`, `--ai gemini`, `GEMINI.md`, `.gemini/` | **폐기** — 외부 CLI 는 codex 만 (사용자 결정 2026-09-13) |
| PRD/TASK 7문서 체인(full), `fix/`·`hotfix/` light | 유지 |
| `WORK.md` (`contract: work-v1`, track `work`) | 신규 — 작은 작업 기본 |
| `risk` 선언 + `risk_rules` 교차 검사 | 신규 |
| `handoff_validate(purpose=...)` plan_review / implementation_complete / rework | P0 신규, 유지 |
| `/retrospective`, worktree 격리 | 유지하되 어떤 흐름에도 강제하지 않음 |
| 모델 지정 | `.claude/agents/*.md` 직접 편집 → `.agent-config.json` `claude_models` |
| 과거 문서 일괄 보정 | 도구 없음. 필요 시 별도 작업 |
