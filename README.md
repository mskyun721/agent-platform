# Agent Platform

Claude Code / Codex 로 대상 백엔드 프로젝트의 **기획 → 구현 → 리뷰 → 보안 → QA → 릴리스**를 조율하는 팀 공통 워크플로우 플랫폼. Python/FastMCP MCP 서버 + standalone CLI(`agent-platform-agent`) + 공통 역할 지침(`standards/agents/`)으로 구성된다. Kotlin/Java Spring WebFlux 규칙은 이 플랫폼이 지원하는 **대상 프로젝트**에 적용되고, 구조 규칙은 target 마다 `ARCHITECTURE.md` 로 정의한다. 플랫폼 자체는 Python 이다.

목적은 **토큰 대비 효율**, **단계별 요청·검수 제어**, **회사 정책·도메인 적용**,
**책임자가 확인할 수 있는 검토 근거**다. [설계 기준과 후속 우선순위](standards/reference/platform-purpose.md)를 따른다.

| 항목 | 현재 |
|---|---|
| 테스트 | `uv --directory ./mcp-server run --locked --dev python -m pytest -q ../tests` → 434 passed, 159 subtests passed (2026-09-25) |
| CI | GitHub Actions `Platform Tests` — `main` push·PR 에서 잠금 의존성으로 전체 테스트. 최근 3회 성공 |
| 외부 CLI | Claude Code / Codex (공통 CLI·관측·평가) |
| MCP 툴 | 41개 (`standards/reference/mcp-tools.md`) |
| 상태 문서 | `docs/refactor/agent-platform-evolution/STATUS.md` (로컬, gitignore) |

## 1. 구성

```text
agent-platform/
├── AGENTS.md                  # 공통 정책 단일 소스 (Codex 자동 로드, Claude 는 CLAUDE.md 가 import)
├── CLAUDE.md                  # Claude 전용 메모 + @AGENTS.md
├── .agent-config.json         # CLI·모델·검증 프로필·위험 규칙·관측 설정 (§13)
├── .mcp.json                  # Claude 프로젝트 스코프 MCP 등록
├── .claude/agents/            # Claude subagent adapter (본문은 standards/agents/ 에서 생성)
├── .claude/commands/          # /init-project /new-feature /gate-check /handoff /retrospective
├── .claude/settings.json      # hook 4개 (§12)
├── standards/agents/          # 역할 지침 원본 7개 (orchestrator planner backend reviewer security qa cicd)
├── standards/*.md             # 대상 프로젝트 코딩·API·테스트·보안·커밋 표준
├── standards/reference/       # 운영 레퍼런스 (mcp-tools, evidence-gates, run-recovery, skill-management …)
├── templates/                 # 산출물 템플릿 (PRD TASK WORK API-SPEC FLOW DECISIONS REVIEW …)
├── workflows/                 # feature-flow, hotfix-flow
├── mcp-server/                # FastMCP 서버 + CLI (uv, uv.lock 추적)
├── scripts/                   # sync_claude_settings, docs_stats, pr_logic_size, check_capabilities
├── evals/                     # 고정 평가 과제 + 자동 실행·판정·요약
├── skills/                    # 관리형 스킬 패키지 저장소 (선택)
└── .local/state.db            # 실행 기록 SQLite (gitignore)
```

## 2. 설치와 설정

### 요구사항

```bash
brew install uv jq                      # uv: MCP/CLI 런타임, jq: Claude hook
npm install -g @anthropic-ai/claude-code && claude login
codex login                             # Codex 를 쓸 때
```

### MCP 등록

- **Claude Code**: 플랫폼 루트에서 실행하면 `.mcp.json`(프로젝트 스코프)이 자동 적용된다. **대상 프로젝트 디렉터리에서** Claude 를 열어 쓰려면 user 스코프에 절대경로로 한 번 더 등록한다.
  ```bash
  claude mcp add agent-platform -s user -- uv --directory /ABS/PATH/agent-platform/mcp-server run agent-platform-mcp
  claude mcp list   # agent-platform: ✔ Connected
  ```
  두 스코프에 모두 있으면 Claude 가 "multiple scopes" 경고를 내지만 동작에는 문제 없다.
- **Codex**: user 레벨에 **절대경로**로 등록한다. 상대경로(`./mcp-server`)는 플랫폼 루트 밖에서 실패한다.
  ```bash
  codex mcp add agent-platform -- uv --directory /ABS/PATH/agent-platform/mcp-server run agent-platform-mcp
  codex mcp list    # Status 가 enabled 인지 확인 (disabled 면 ~/.codex/config.toml 의 enabled = true)
  ```

### 쓰기 허용 범위 (allowlist)

MCP/CLI 는 아래 루트 안의 프로젝트만 읽고 쓴다. 로컬 전용 `.agent-platform.env`(gitignore) 또는 프로세스 환경에 둔다. 플랫폼 자신의 경로는 항상 허용된다(하위 디렉터리 제외).

```bash
AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS="/path/to/projects:/path/to/another-root"
```

SessionStart hook 이 `scripts/sync_claude_settings.py` 를 실행해 (1) 이 값을 `.claude/settings.local.json` 권한으로, (2) `.agent-config.json` `claude_models` 를 `.claude/agents/*.md` 의 `model:` 로, (3) `standards/agents/*.md` 본문을 `.claude/agents/*.md` 로 동기화한다. 수동: `python3 scripts/sync_claude_settings.py` / 드리프트 검사만: `--check`.

### 대상 프로젝트 선택

| 방법 | 언제 |
|---|---|
| `.active-project` (절대경로 한 줄, `project_init` 이 기록) | 기본. `root` 를 생략하면 여기를 쓴다 |
| `--root /abs/path` 또는 MCP `root="/abs/path"` | 요청마다 명시. 환경·`.active-project` 는 바뀌지 않는다 |
| `--root <project_id>` | `project-register` 로 등록한 ID. worktree 는 같은 ID 를 공유하고 요청한 경로에서 실행된다 |
| `--root "$PWD"` (플랫폼 루트) | 플랫폼 자체를 개선할 때 |

```bash
agent-platform-agent project-register /abs/service --project-id service-a --verify-profile gradle
agent-platform-agent project-list
agent-platform-agent project-rebind service-a /abs/moved-service
agent-platform-agent project-unregister service-a         # 메타데이터만 삭제
```

등록은 선택이다. 등록하면 gate/handoff 의 **기본 검증 프로필**이 붙고, 스킬 활성화(§10)와 체크포인트(§9)가 가능해진다. 레지스트리는 `.agent-projects.json`(gitignore, macOS/Linux 쓰기).

> 아래 CLI 예시는 모두 플랫폼 루트에서 `uv --directory ./mcp-server run agent-platform-agent …` 뒤에 붙인다. 별칭을 권장한다: `alias apa='uv --directory /ABS/PATH/agent-platform/mcp-server run agent-platform-agent'`

## 3. 핵심 개념

**작업 계약(track)** — 게이트가 요구하는 문서 집합.

| track | 언제 | 문서 | 인계 전 승인 |
|---|---|---|---|
| `work` | 작은 작업. `WORK.md` 가 있으면 자동 | `WORK.md` 하나 (목표·범위·위험·검증·결정·결과) + 리뷰 시 `REVIEW.md` | WORK 1회 |
| `light` | `fix/`, `hotfix/` 이름 | `PRD.md` + `REVIEW.md` | PRD |
| `full` | 그 외 (`features/`, `refactor/` …) | `PRD TASK API-SPEC DECISIONS REVIEW SECURITY-AUDIT TEST-PLAN` + `FLOW.drawio` (+ `openapi.yaml`) | 단계별 |

**게이트 결과** — `gate-check` / `feature_gate_check` 는 네 상태를 따로 보고하고 `passed` 로 종합한다.

| 키 | 의미 |
|---|---|
| `artifact_status` | 문서 front-matter·필수 섹션·링크 형식 |
| `verification_status` | 검증 프로필 실행 결과 `passed / failed / not_run / error`. 요청했는데 못 돌리면 실패 |
| `policy_status` | 검증 정의(프로필+검증기 코드)가 검토된 것과 같은지 `unchanged / changed / unreviewed`. 보고용, `gate.policy_enforced` 로 강제 |
| `risk` | 선언 `risk` 와 실제 변경 경로 대조 `ok / conflict / undeclared / unverified / invalid` (§8) |
| `structure` | target 루트 `ARCHITECTURE.md` 존재 `present / missing`. backend·reviewer·security·qa 인계 선행조건 (§10c) |
| `evidence` (`--evidence`) | AC 별 검증 증거가 현재 코드와 연결돼 있는지 `complete / stale / incomplete` (§8) |
| `files[].kind` | `markdown`(front-matter 검사) / `drawio`(구조 검사, 승인 상태 없음) |

**인계 목적(purpose)** — `handoff` / `handoff_validate`.

| purpose | 기본 적용 | 요구 | 검증 프로필 실행 |
|---|---|---|---|
| `plan_review` | planner → reviewer/security | 계획 문서 형식 유효, rejected 아님 | 안 함 |
| `implementation_complete` | reviewer/security/qa/cicd 로 인계 | 소스 산출물 `approved` + 다음 역할 선행 문서 | **실행** (프로필 없으면 실패) |
| `rework` | reviewer/security/qa → backend | 반려 문서가 `rejected` | 안 함 |

**역할 지침** — 원본은 `standards/agents/<role>.md`. 같은 AI 로 역할을 수행할 땐 현재 세션이 원본을 읽고 그대로 한다(플러그인·MCP 불필요). 다른 AI 에게 맡길 때만 `run …`/`*_run` wrapper 를 쓴다. wrapper 도 같은 원본을 프롬프트에 넣고 `prompt_sources` 로 출처를 돌려준다.

**승격은 사람이** — 모든 산출물은 `status: draft` 로 생성된다. `approved`/`rejected` 는 담당 검토자가 front-matter 를 고쳐 승격한다. 테스트 통과·CLI 정상 종료·커밋은 승인이 아니다.

## 4. 사용 흐름 A — 작은 작업 (work 계약)

```bash
apa new-feature fix/token-expiry --contract work-v1 --root service-a
#  → docs/fix/token-expiry/WORK.md 생성 (risk: undecided → 판단 전엔 gate 실패)
```

1. `WORK.md` 의 1 목표 · 2 범위 · 3 위험(`risk: low|high`, high 면 `risk_reason`) · 4 검증(AC 표) 을 채우고 `status: approved`.
2. 인계 확인: `apa handoff planner backend fix/token-expiry --root service-a` (plan_review, 문서만).
3. 구현 — 현재 세션에 지시:
   ```text
   backend 역할로 fix/token-expiry 를 WORK.md 기준으로 구현해줘. root 는 service-a.
   ```
   구현 후 WORK.md 5 결정 · 6 결과 를 채운다.
4. 검증·인계:
   ```bash
   apa gate-check fix/token-expiry --root service-a --verify --risk-base origin/main
   apa handoff backend reviewer fix/token-expiry --root service-a --risk-base origin/main
   ```
   `--verify-profile` 을 생략하면 등록 프로젝트의 기본 프로필을 쓴다. `risk: high` 면 QA/릴리스 인계 전에 `SECURITY-AUDIT.md` 승인이 필요하다.
5. 리뷰 — 현재 세션에 `reviewer 역할로 fix/token-expiry 리뷰해줘. root 는 service-a.` → `REVIEW.md`. HIGH 가 있으면 `status: rejected` 로 두고 `apa handoff reviewer backend fix/token-expiry --root service-a` (rework).
6. 릴리스 준비 — `cicd 역할로 fix/token-expiry 릴리스 준비해줘.` → `PR-BODY.md` 등. push/PR 은 §9 의 외부 액션 절차를 따른다.

work 계약에서는 planner·cicd 를 별도로 호출할 필요가 없고 `plan_run`/`backend_run` 이 자동 호출되지 않는다.

## 5. 사용 흐름 B — 큰 기능 (PRD/TASK 계약)

```bash
apa new-feature payment-cancel --root service-a      # PRD.md, TASK.md
```

기획 — 현재 세션에:

```text
planner 역할로 payment-cancel 기획해줘. root 는 service-a.
요구사항: 결제 후 24시간 이내 전액 취소, 중복 취소는 기존 결과 반환.
```

| 산출물 | 내용 |
|---|---|
| `PRD.md` / `TASK.md` | 요구사항·BR·AC / phase 별 작업·검증 |
| `API-SPEC.md` | 메서드·경로·operationId·권한·요청/응답·오류·멱등성. API 변경이 없으면 "해당 없음" 사유 |
| `openapi.yaml` | API 변경 시 OpenAPI 3.1 계약 (front-matter 없는 기계 판독 파일) |

API 선작성은 [API 계약 정책](standards/api-contract.md)을 따른다. KT Cloud 응답 계약·BE 직렬화·Apidog 규약을 반영해 단건 직접 응답, 목록 봉투, null/배열/boolean, named schema, 권한 확장을 명시한다. 날짜 형식 등 원문 간 차이와 기존 API 전환 예외도 정책에 기록한다. 실제 HTTP 및 Apidog 왕복 검증은 별도 실행 증거가 필요하며, 정책 적용만으로 자동 통과하지 않는다.
| `FLOW.drawio` | **draw.io 다이어그램**(편집 가능, front-matter 없음)으로 정상·실패·분기. 노드 라벨에 BR/AC/operationId, 연결표는 PRD §6.0. 게이트가 drawio-skill `validate.py` 로 검사하며 full track 은 backend 인계 전 필수 |

흐름도는 drawio-skill(관리형 스킬, §10)로 그린다. draw.io 앱은 쓰지 않는다 — XML 작성·`validate.py` 검사·`build --from graph` 배치까지 앱 없이 되고, 보기는 diagrams.net 웹/VS Code 확장. 읽을 때는 `drawio2mermaid.py` 로 텍스트 뷰를 얻는다.

Codex 로 기획을 위임하려면 `apa run planner payment-cancel --root service-a --ai codex --requirements "…" --dry-run` 으로 대상·프롬프트를 확인하고 `--dry-run` 을 빼고 실행한다. 결과의 `missing_artifacts` 는 필수 파일 누락만 알린다(내용 검증 아님).

이후 역할 흐름은 `workflows/feature-flow.md`:

```text
planner → PRD TASK API-SPEC FLOW (openapi.yaml)
backend → code, API-SPEC 갱신, DECISIONS        phase 별 구현, 각 phase 후 reviewer
reviewer + security → REVIEW, SECURITY-AUDIT   병렬
qa → TEST-PLAN (+ 테스트 코드, BUG-*)
cicd → PR-BODY, RELEASE-NOTE, DEPLOY-CHECKLIST, draft PR
```

각 인계는 `apa handoff <from> <to> <feature> --root service-a [--verify-profile gradle] [--evidence]`. Claude Code 에서는 `/handoff <to> <feature>` 가 같은 MCP 툴을 호출한다.

## 6. 사용 흐름 C — 플랫폼 자체 개선

```bash
apa new-feature refactor/my-change --root "$PWD" --contract work-v1
apa gate-check refactor/my-change --root "$PWD" --verify --verify-profile platform
apa handoff backend reviewer refactor/my-change --root "$PWD" --verify-profile platform
```

산출물은 플랫폼의 `docs/<type>/<name>/` 에 생긴다(gitignore 대상 — 팀 공유는 `standards/reference/` 로). `.active-project` 는 바꾸지 않는다. 검증기 코드(`feature.py`, `verification.py` 등)를 고치면 `policy_status: changed` 가 보고된다.

## 7. Claude Code 에서

플랫폼 루트 또는 대상 프로젝트에서 Claude 를 열고:

```text
> /init-project my-service com.example.myservice      # 새 Spring 프로젝트 + .active-project
> /new-feature payment-cancel                          # 또는 fix/x (light), --contract work-v1
> planner 로 payment-cancel PRD/TASK 작성해줘
> backend 로 payment-cancel 구현해줘
> reviewer 와 security 로 교차 검증해줘
> /gate-check payment-cancel
> /handoff qa payment-cancel
```

`orchestrator` subagent 가 라우팅·phase 분할·인계 게이트를 조율한다. subagent 모델은 `.agent-config.json` `claude_models` 가 단일 출처다(reviewer/security = sonnet, backend = opus).

## 8. 검증 상세

### 검증 프로필

`.agent-config.json` `verify_profiles.<id>` = `{argv, cwd, timeout_sec, scope}`. argv 는 shell 없이 프로젝트 안 `cwd` 에서 실행된다. 프로필을 지정하지 않으면 `not_run` 으로 실패하고 빌드 마커(`gradlew`/`mvnw`/`pyproject.toml`)에 맞는 후보를 `suggested_profiles` 로 제안한다. 기본 제공: `platform`(플랫폼 pytest), `gradle`, `pytest`. 출력 원문은 저장·반환하지 않는다.

재시도: `retry.verification: {"max_attempts": 1, "max_minutes": 15}` 기본(재시도 없음). 최대 5회·60분.

### 위험 교차 검사

선언(`WORK.md`/`PRD.md` 의 `risk`)과 실제 변경 경로를 `risk_rules.paths`(fnmatch) 로 대조한다.

| status | 의미 | 게이트 |
|---|---|---|
| `ok` | 모순 없음 | 통과 |
| `conflict` | `low` 선언인데 위험 경로 변경 | **실패** |
| `undeclared` | legacy PRD/TASK 에 선언 없음 | 보고만 |
| `unverified` | git 조회 실패·잘못된 `--risk-base`·규칙 없음·프로젝트가 git 루트가 아님 | 선언된 항목은 **실패** |
| `invalid` | `low/high` 외 값, high 인데 사유 없음 | **실패** |

기본 범위는 미커밋(staged+unstaged+untracked). PR 검토에서는 `--risk-base origin/main` 으로 merge-base 이후 커밋까지 포함한다(자동 fetch 없음). 경로 패턴은 보조 증거다 — 인증·권한·데이터·공개 계약·파괴적 변경은 경로가 안 걸려도 `high` 로 선언한다.

### 증거 게이트 (`--evidence`)

프로필 `scope.acs` 에 AC ID 를 매핑하면 실행 결과가 AC 별 증거로 기록되고, 현재 코드 fingerprint 와 대조해 `complete / stale / incomplete / evidence_unavailable` 을 보고한다. 미해결 `### [HIGH]`(REVIEW) / `Critical|High`(SECURITY-AUDIT) 와 `approved_fingerprint` 가 낡은 승인도 잡는다. 기본은 보고 모드, `gate.evidence_enforced: true` 로 차단. 상세: `standards/reference/evidence-gates.md`.

### 검증 정의 검토

```bash
apa verify-profile approve gradle --reviewer "<이름>"
```

프로필 해시·플랫폼 HEAD·검증기 소스 해시·검토자를 기록한다(MCP 에는 없음, 사람 전용 절차). 이후 `policy_status` 가 `unchanged` 가 되고, 검증기 코드가 바뀌면 `changed` 로 돌아간다. `gate.policy_enforced: true` 면 완료 인계가 차단된다.

### PR 크기

```bash
python3 scripts/pr_logic_size.py --base main --head fix/token-expiry
```

merge-base 이후 커밋의 **순수 로직** 추가+삭제가 500 라인을 넘으면 실패. Python 은 AST/token 으로 import·주석·docstring 제외, 테스트·설정·문서는 경로로 제외, 다른 언어는 보수 집계 + `manual_review_required`. 외부 액션의 PR 생성(§9)도 같은 검사를 거친다.

## 9. 실행 기록 · 중단 복구 · 외부 액션

`.local/state.db`(SQLite) 에 wrapper 실행·검증·인계·리뷰 판정·usage 메타데이터가 자동 기록된다(dry-run 제외, 원문 프롬프트/소스/출력 미저장). `observability.enabled: false` 로 끌 수 있고 저장 실패는 `observability.stored: false` 로 표시될 뿐 작업을 막지 않는다. 아래 원문 수집을 명시적으로 켜면 별도 로컬 DB에 wrapper 입력·최종 응답을 보관한다.

### LLM 조회 화면

저장소 루트에서 실행한다. 외부 서비스·API 키·Docker 없이 로컬 브라우저에서 조회한다.

```bash
# 플랫폼 경로의 Claude·Codex 직접 세션 + 이후 wrapper 원문 수집
uv --directory mcp-server run agent-platform-agent observe capture on --root "$PWD"
# 조회 서버: 터미널에 출력되는 토큰 포함 URL로 접속
uv --directory mcp-server run agent-platform-agent observe serve --port 8765
```

화면에서 프로젝트·작업·역할을 검색하고 실행을 선택하면 입력 프롬프트, 최종 응답,
실행 시간, 입력/출력/캐시 읽기/캐시 쓰기 토큰, 상태와 이벤트를 확인할 수 있다.
최근 100건을 표시하며 목록과 선택한 대화는 5초마다 자동 갱신한다. Claude/Codex 이름으로도 검색할 수 있다. API는 `?limit=500`까지 지원한다.
모델·토큰·시간이 수집되지 않았으면 `—`로 표시한다. 시간은 wrapper 실행 전체 또는 직접 세션의 사용자 턴 단위이며
개별 LLM 요청 시간이나 순수 생성 시간이 아니다. 프로세스 완료는 문서 승인과 다르다.

- 원문은 기본 OFF. `--root`에 다른 등록 project_id 또는 허용 경로를 지정할 수 있다.
- `.local/llm-content.db`에 별도 저장(사용자 지정 state DB가 있으면 같은 디렉터리).
  파일 권한 0600, 보관 기간 7일, 필드별 최대 65,536자, 알려진 비밀 패턴 마스킹.
  임의 개인정보까지 완전한 제거를 보장하지 않으므로 필요한 프로젝트에만 켠다.
- 만료 원문은 내용 DB 접근 시 삭제하며 서버가 꺼진 동안의 백그라운드 삭제는 없다.
  state export/import에는 원문을 포함하지 않는다. 원문 DB와 그 백업은 별도 관리한다.
- 서버는 127.0.0.1에만 바인딩하고 무작위 접속 토큰을 요구한다. URL의 토큰은 브라우저
  fragment에서 sessionStorage로 이동하며 API는 Authorization header를 사용한다.
  서버 재시작 시 새 URL을 사용한다. UI는 읽기 전용이며 원문을 HTML로 실행하지 않는다.
- 조회 서버가 실행 중이고 플랫폼 루트의 capture가 켜져 있으면, **작업 경로가 이 agent-platform 루트와 정확히 일치하는 Claude·Codex 직접 세션**을 자동 수집한다. 다른 프로젝트는 제외한다. Claude 로그에 여러 작업 경로가 섞여 있어도 파일 전체를 버리지 않고 agent-platform 경로 구간의 턴만 수집한다.
  `~/.codex/sessions`와 `~/.claude/projects`의 JSONL을 5초마다 확인한다(`CODEX_HOME`/`CLAUDE_CONFIG_DIR` 지원). 최근 7일 내 변경된 로그 중 CLI별 최신 300개, 파일당 64MiB 이하를 읽는다. 최초 시작 시 해당 로그의 기존 대화도 가져온다.
  사용자 입력·텍스트 응답·턴 소요시간·기록에 존재하는 토큰만 보관한다. 시스템 지시, 내부 추론, 도구 결과는 수집 대상에서 제외한다. 실행 중이거나 로그에 없는 응답·시간·토큰은 비어 있을 수 있다.
  Claude는 API 메시지 ID별 최신 usage를 합산하고, Codex는 턴 누적 usage 스냅샷을 사용하여 중복 집계를 피한다. 네이티브 로그 형식이 바뀌면 파서 보완이 필요하다.
  수집 상태/오류는 `/api/runs`의 `collector`에 표시한다. 서버 종료 중에는 수집하지 않으며 다음 시작 때 다시 확인한다.
- 직접 세션은 기존 `state start/end`로 만든 run에 `observe record --run-id RUN_ID`를
  사용해 stdin으로 `{"prompt":"...","response":"..."}`를 명시 제출할 수 있다.
  해당 프로젝트의 capture가 켜져 있어야 하며 토큰을 추정하거나 자동 생성하지 않는다.
- 수집을 끄더라도 기존 원문은 만료까지 남는다. 즉시 삭제하려면 아래 purge를 실행한다.
  purge는 해당 내용 DB의 모든 프로젝트 원문과 직접 세션 투영을 삭제하고 wrapper 메타데이터와 수집 설정은 보존한다. 삭제/만료된 직접 세션 턴 ID는 재수집 방지를 위해 남긴다. CLI 자체 원본 로그는 삭제하지 않는다.

```bash
uv --directory mcp-server run agent-platform-agent observe capture off --root "$PWD"
uv --directory mcp-server run agent-platform-agent observe purge-content
```

역할별 상태·인계 기록이 필요한 직접 세션은 별도로 명시 등록할 수 있다:

```bash
apa state start fix/token-expiry --role backend --backend claude --root service-a   # → run_id
apa state heartbeat <run_id> --pid <세션의 실제 PID>
apa state checkpoint <run_id> --phase implementation --next-action "남은 테스트 실행"
apa state review-record fix/token-expiry --role reviewer --decision rejected --artifact docs/fix/token-expiry/REVIEW.md \
    --code-fingerprint <fp> --reviewer-id <이름> --decision-id <uuid4> --root service-a
apa state end <run_id> completed
apa state runs / review-status fix/token-expiry --project-id service-a / usage [--since …]
apa state export --out backup.json / import backup.json / prune --retention-days 180
```

반려 카운터는 역할별 연속 `rejected` 수이며 그 역할의 `approved` 만 초기화한다. `state review-status <task> --project-id <id> [--threshold 3]` 가 임계(기본 3회) 도달 시 `intervention_recommended` 로 사용자 개입을 권고한다.

**외부 관측(OpenTelemetry)** — CLI 세션 단위(프롬프트·API 요청·툴 호출·토큰·비용)는 플랫폼 DB 가 아니라 CLI 가 내보내는 OTel 로 본다. `scripts/otel/` 에 로컬 collector(`docker compose up -d`), Claude 용 `claude.env`, Codex 용 `codex-otel.toml` 이 있다. Claude 트레이싱을 켜면 Bash 자식 프로세스에 `TRACEPARENT` 가 전파되어 플랫폼 run 의 `run_started` payload 에 `trace_id`/`span_id` 가 기록된다(`state runs` 로 확인) → collector 에서 그 trace 를 열면 run 을 둘러싼 프롬프트·툴·비용이 보인다. 상세·한계: `standards/reference/observability-otel.md`.

**중단 복구** — `apa state resume <run_id>` 는 조회만 한다: `running`(살아 있는 PID 있음) / `done` / `no_checkpoint` / `resumable` / `diverged`(바뀐 경로 목록). `resumable` 이면 `apa state continue <run_id> --pid <새 PID>` 가 새 run_id 를 만든다. 자동 재개는 없다. 상세: `standards/reference/run-recovery.md`.

**외부 액션 (push / draft PR)** — 반드시 계획 → **사용자 확인** → 실행 3단계:

```bash
apa state action-plan <run_id> push k1 --target-json '{"remote":"origin","branch":"fix/token-expiry","head":"<full sha>"}'
apa state action-confirm <action_id> --confirmed-by "<이름>"
apa state action-execute <action_id>
apa state action-plan <run_id> pr k2 --target-json '{"repository":"owner/repo","branch":"fix/token-expiry","base":"main","head":"<full sha>","title":"fix: …"}'
apa state actions --run-id <run_id> / action-reconcile <action_id>
```

원격 상태를 먼저 조회해 중복이면 건너뛰고, 쓰기 결과가 불확실하면 재실행하지 않는다. `deploy`·`confluence_page` 는 기록만 되고 실행 adapter 는 없다.

## 10. 스킬 관리

관리형 스킬 패키지(`SKILL.md` + `skill.json`)를 플랫폼이 보관하고 프로젝트별로 native 디렉터리에 켜고 끈다.

```bash
apa skill add /abs/path/to/package          # skills/packages/<id> 로 복사 (스크립트 실행 없음)
apa skill list [--project-id service-a]
apa skill enable  <id> service-a            # .claude/skills/<id>, .agents/skills/<id> 에 복사 — 다음 세션부터
apa skill disable <id> service-a            # 관리 복사본만 제거. 사용자 수정본은 보존 + user_modified 보고
apa skill remove  <id>                      # 어디서도 enabled/의존 중이 아닐 때만
```

superpowers 등 기존 플러그인 스킬은 unmanaged 로 남고 건드리지 않는다. 스킬을 전부 꺼도 AGENTS.md 정책·allowlist 는 유지된다. 상세: `standards/reference/skill-management.md`.

## 10b. target 코드 그래프 (graphify)

플랫폼 CLI/MCP에서 기존 그래프의 무결성과 변경 영향 후보를 읽기 전용으로 조회할 수 있다.

```bash
uv --directory mcp-server run agent-platform-agent graph status --root /absolute/project
uv --directory mcp-server run agent-platform-agent graph impact src/app.py --root /absolute/project --depth 3 --limit 100
```

MCP는 `graph_status(root)`와 `graph_impact(paths, root, depth=3, limit=100)`이다.
root에는 등록 project_id도 가능하다. `paths`는 변경한 프로젝트 상대 파일 경로이며,
삭제된 파일도 입력할 수 있다. 방향 그래프는 호출/import 관계를 역방향으로,
무방향 그래프는 양쪽 이웃으로 탐색해 영향 파일과 테스트
후보를 추천한다. `via`를 따라 변경 파일까지 연결 이유를 확인할 수 있다.

`integrity`는 중복 ID·미선언 endpoint·사라진 소스 등을, `freshness`는 선택 snapshot의
소스 해시 일치 여부를 보고한다. 일반 Graphify 출력에 소스 해시가 없으면 최신성은
`unknown`이다. `current`도 기록된 소스 범위의 일치만 뜻하며 새 파일·동적 호출까지
포함했다는 보장은 아니다. 후보·잘린 결과·미매핑 경로는 검토용이며 기존 gate와 승인,
필수 테스트를 대신하지 않는다. 상세 schema·제한은
[그래프 조회 계약](standards/reference/mcp-tools.md#graph-inspection)을 참고한다.

플랫폼 자체의 코드 탐색에도 Graphify를 사용한다. Claude/Codex용 스킬은
`.claude/skills/graphify/`, `.agents/skills/graphify/`에 있으며, 저장된 hook 명령을
실행하려면 `graphify` CLI가 PATH에 있어야 한다. `.claude/settings.json`의
`hook-guard`와 `.codex/hooks.json`의 `hook-check` 설정을 함께 관리한다.
`graphify-out/`은 로컬 생성물이므로 Git에 포함하지 않는다.

신규 개발 계획(2026-09-16부터)은 Phase 1 공통·Phase 2 도메인을 선행하고,
이후 API endpoint별 repository·service·router·테스트를 한 세트로 진행한다.
기존 TASK는 변경하지 않는다. 상세: [개발 Phase 기준](standards/reference/backend-phase-flow.md).

역할별 메인·보조 스킬은 [역할 스킬 정책](standards/reference/role-skills.md)으로 선택한다.
기획은 brainstorming/writing-plans와 drawio, 개발은 TDD/디버깅과 graphify,
QA·릴리스는 완료 검증 절차를 사용한다. 현재 세션의 노출 여부를 확인하고 없으면
명시적으로 대체한다. 실제 사용·미사용 사유는 역할 산출물의 Skill Usage에 남긴다.
자동 설치나 글로벌 설정 변경은 하지 않으며 이 기록은 자동 호출 telemetry와 구분된다.

2026-09-15 설치 보완: `kcp-cm`에 Ponytail을 관리 패키지로 Claude/Codex 양쪽에
활성화하고, 기존 Claude 설치에서 graphify 및 역할 매핑에 필요한 Superpowers
스킬 8개를 Codex `.agents/skills`에 추가했다. 기존 Claude 플러그인은 유지한다.
Ponytail은 backend 보조·lite로 사용하며 테스트 축소 지침보다 플랫폼 정책이 우선한다.
복사 설치한 외부 스킬은 unmanaged이며 플랫폼 `skill remove` 대상이 아니다.

target 프로젝트에 [graphify](https://github.com/safishamsi/graphify) 를 적용하면 역할 실행이 소스를 통째로 읽는 대신 그래프를 먼저 질의한다. 플랫폼은 `graphify-out/graph.json` 존재를 wrapper 컨텍스트에 메타데이터로 알리고(본문 미주입), 역할 원본이 `graphify query/explain/affected` 를 먼저 쓰도록 지시한다.

```bash
uv tool install graphifyy                                   # 1회
cd <target> && graphify install --project --platform claude && graphify install --project --platform codex
graphify extract . --code-only && graphify cluster-only . --no-viz   # 로컬 AST, API 키 불필요
graphify hook install                                       # post-commit/post-checkout 자동 갱신
printf 'graphify-out/\n' >> .gitignore
```

target 에 남는 것: `CLAUDE.md`/`AGENTS.md` 의 `## graphify` 절, `.claude/settings.json` PreToolUse 훅(권고, `--strict` 로 차단 가능), `.claude/skills/graphify`, `.codex/hooks.json`, `.codex/skills/graphify`. 문서(md)까지 그래프에 넣으려면 IDE 세션에서 `/graphify .`. 절감 효과는 Codex wrapper usage(`state usage --project-id <id>`)로 적용 전후를 비교한다.

## 10c. target 구조 문서 (ARCHITECTURE.md)

프로젝트마다 패키지·레이어 구조가 달라 플랫폼은 헥사곤을 강제하지 않는다. target 루트의 `ARCHITECTURE.md` 가 그 프로젝트의 Layout 과 Rules(레이어 방향, 모듈 간 허용/금지, 모델 배치, 표준과 다른 점)를 정의하고, 모든 역할이 코드를 만지기 전에 이를 읽는다. 파일·클래스·의존 현황은 문서에 적지 않고 graphify 로 확인한다(§10b).

```bash
cp templates/ARCHITECTURE.md <target>/ARCHITECTURE.md   # 헥사곤 프리셋에서 시작, 실제 구조에 맞게 수정
agent-platform-agent gate-check <feature> --agent backend   # structure.status: missing 이면 인계 차단
```

`review_run` 의 `focus=structure` 는 이 문서의 규칙 준수를 리뷰한다(기존 `hexagonal` 대체). wrapper 컨텍스트에는 존재 여부만 메타데이터로 실리고 본문은 역할이 직접 읽는다.

## 11. 평가

`evals/tasks/` 의 고정 과제 5개(small-feature, seeded-bug, broken-test, api-add, skill-remove)를 임시 workspace 에서 실행하고 evaluator 가 행동·변이 검사로 판정한다.

```bash
uv --directory mcp-server run python ../evals/run_task.py auto --task api-add --ai codex --repeat 3 --max-minutes 5
uv --directory mcp-server run python ../evals/summarize.py
uv --directory mcp-server run python ../evals/summarize.py --regress --baseline evals/baseline.json
```

목적은 **회귀 탐지**다. 현재 기준(v4): 두 AI × 5과제 × 3회 = 30/30 통과. 표본이 작으므로 AI 간 우위를 주장하지 않는다. 절차·제한: `evals/README.md`.

## 12. 인터페이스 요약

**CLI** (`agent-platform-agent`)

| 명령 | 용도 |
|---|---|
| `new-feature <name> [--root] [--contract work-v1]` | 산출물 scaffold |
| `gate-check <name> [--root] [--agent] [--verify] [--verify-profile] [--risk-base] [--evidence]` | 게이트. 실패 시 exit 1 |
| `handoff <from> <to> <name> [--root] [--purpose] [--verify/--no-verify] [--verify-profile] [--risk-base] [--evidence]` | 인계 검증 |
| `list-artifacts <name> [--root]` | 문서 목록·status |
| `run <role> <name> --ai codex [--root] [--requirements] [--action] [--scope] [--focus] [--dry-run]` | Codex 로 역할 실행 |
| `project-register/list/rebind/unregister` | 프로젝트 레지스트리 |
| `verify-profile approve <id> --reviewer` | 검증 정의 검토 기록 |
| `state …` | 실행 기록·복구·외부 액션 (§9) |
| `skill …` | 스킬 관리 (§10) |

**MCP 툴** (39)

| 그룹 | 툴 |
|---|---|
| 플랫폼 | `feature_scaffold` `feature_list_artifacts` `feature_gate_check` `handoff_validate` `project_init` `standards_read` `standards_list` `hello` |
| 프로젝트 | `project_register` `project_list` `project_rebind` `project_unregister` |
| 역할 wrapper (cli: auto\|codex) | `plan_run` `backend_run` `review_run` `audit_run` `qa_run` `release_run` `investment_run` `quant_run` `investment_risk_run` |
| 실행 기록 | `run_start` `run_end` `run_heartbeat` `run_checkpoint` `run_resume` `runs_list` `review_result_record` `review_cycle_status` `usage_summary` |
| 스킬 | `skill_add` `skill_list` `skill_enable` `skill_disable` `skill_remove` |
| 연동 (선택, env 필요) | `confluence_fetch_page` `confluence_list_space` `confluence_create_page` `confluence_sync_feature` / `apidog_list_endpoints` `apidog_export_openapi` `apidog_fetch_endpoint_detail` |

**Slash commands**: `/init-project <name> <pkg> [opts]`, `/new-feature <name>`, `/gate-check <name>`, `/handoff <next-agent> <feature>`, `/retrospective <feature>`(선택, 어떤 흐름에도 강제되지 않음).

**Hooks** (`.claude/settings.json`): `PreToolUse`(Bash 파괴 명령 차단) · `PostToolUse`(Edit/Write — ktlint, `docs/**/*.md` front-matter 경고) · `UserPromptSubmit`(시크릿 경고) · `SessionStart`(권한·모델·역할 본문 동기화).

## 13. 설정 레퍼런스 — `.agent-config.json`

| 키 | 기본 | 설명 |
|---|---|---|
| `preferred_cli` | `codex` | wrapper `cli="auto"` 의 fallback |
| `cli_models` | `{}` | 외부 CLI 모델 핀 (`release_run(model=)` 등) |
| `claude_models` | reviewer/security sonnet, backend opus … | Claude subagent 모델. SessionStart 에 주입 |
| `verify_profiles` | platform, gradle, pytest | `{argv, cwd, timeout_sec, scope{acs}}` |
| `gate_verify_command` | `""` | legacy shell 문자열(shell-compat). 비우면 프로필만 |
| `risk_rules.paths` | auth/security/migration/Secret/api/v* | fnmatch 위험 경로 |
| `retry.verification` | `{max_attempts: 1, max_minutes: 15}` | 검증 재시도 예산 |
| `gate.evidence_enforced` / `gate.policy_enforced` | `false` | 보고 → 차단 전환 |
| `observability.enabled` | `true` | 자동 기록 on/off |
| `pricing` | 없음 → 비용 null | 모델별 단가 snapshot (`run-events.md` 참고) |
| `resume.stale_after_sec` | `600` | heartbeat 정지 판정 |

반려 개입 임계는 설정이 아니라 `state review-status --threshold`(기본 3) 로 조회 시 지정한다.

`AGENT_PLATFORM_STATE_DB` 환경변수로 state DB 경로를 바꿀 수 있다.

## 14. 알려진 제한

- 승인(`approved`)·프로필 검토·AC 매핑은 사람이 한다. 플랫폼은 fingerprint 를 제안할 뿐 자동 승격하지 않는다.
- `policy_status`/`reviewed_hash`/커밋은 독립 검토의 증명이 아니다. 같은 저장소에서 검증기와 구현을 같은 AI 가 고칠 수 있다.
- 검증기는 코드 sandbox 가 아니다. build script 는 현재 프로세스 권한으로 실행된다.
- state usage는 직접 세션의 토큰을 포함하지 않는다. 직접 세션의 로그 기반 토큰은 LLM 조회 화면에서 확인한다. Codex wrapper는 `--json`의 확인된 필드만 집계한다.
- 자동 재개·원격 관측 서비스 운영·Git 스킬 설치·분산 실행은 범위 밖. 로컬 LLM 조회 화면은 `observe serve`로 제공한다.
- work 계약의 위험 검사는 프로젝트가 **git 작업 트리 루트**여야 하고 `risk_rules.paths` 가 필요하다(없으면 `unverified` → 선언 항목 실패).
- 기본 gate 는 OpenAPI 문법·Mermaid 렌더링을 검증하지 않는다.

## 15. Reference

`standards/reference/` — `setup.md` `mcp-tools.md` `evidence-gates.md` `run-recovery.md` `run-events.md` `observability-otel.md` `skill-management.md` `backend-capabilities.md` `backend-phase-flow.md` `cicd-release-policy.md` `apidog-integration.md` `confluence-integration.md` `evolution-closeout.md` · `workflows/feature-flow.md` `hotfix-flow.md` · `evals/README.md`

## License

Internal use. 팀 표준에 맞춰 수정·확장한다.


## 투자 리서치 에이전트 (`investment`)

종목·시장·전략의 출처와 반대 근거, 백테스트의 시점·비용·체결 한계를 검토하고
`docs/<type>/<name>/INVESTMENT-REPORT.md`를 작성한다. 개발 제안은 planner에 전달한다.
[역할 지침](standards/agents/investment.md), [보고서 템플릿](templates/INVESTMENT-REPORT.md),
[투자 개발 기준](standards/reference/investment-development.md)을 함께 사용한다.

현재 세션에 바로 요청할 수 있다:

```text
investment 역할로 research/strategy-review를 검토해줘.
root는 /Users/seongkyunmoon/Documents/project/my-stock, 기준일은 2026-09-23.
현재 전략과 백테스트의 근거·반대 근거·시점 누출 가능성을 조사하고 개발 인수 기준을 작성해줘.
```

다른 CLI에 명시적으로 위임할 때만 아래 wrapper를 사용한다. `apa`는 앞서 설정한 CLI 별칭이다.
`--root`는 허용된 경로 또는 등록된 project_id이고 `my-stock` ID는 등록된 경우에 사용한다.

```bash
apa new-feature research/strategy-review --root my-stock
apa run investment research/strategy-review --root my-stock --as-of 2026-09-23 --requirements "전략 근거와 백테스트 시점·비용·체결 검토" --dry-run
# 명시적으로 실행하려면 위 명령에서 --dry-run을 제거한다.
```

기존 작업 폴더라면 new-feature를 반복하지 않는다. 기본 scaffold는 PRD/TASK를 생성하며,
투자 보고서는 investment 실행이 추가한다. 직접 세션은 보고서만 작성할 수도 있다.
MCP는 `investment_run(feature, requirements, as_of, root=...)`를 제공한다.
wrapper는 read-only sandbox로 분석하고 부모 프로세스가 보고서를 저장한다.
Claude adapter는 파일 조회·보고서 작성·웹 조회 도구를 사용하며 Bash와 주문 도구를 등록하지 않는다.

보고서는 항상 draft에서 시작한다. 형식 검사는 금융 주장의 진위를 검증하지 않으며
READY도 거래 승인이 아니다. 조회 도구·자료가 없으면 INSUFFICIENT/ERROR로 기록한다.
제품 코드 변경·브로커 주문·자동 실거래 전환은 이 역할의 범위에 포함되지 않는다.
기존 planner/backend/reviewer/security/qa 흐름에 투자 보고서를 필수로 강제하지 않는다.

### 전략 검증과 투자 위험 역할

| 역할 | 산출물 | 책임 |
|---|---|---|
| `investment` | `INVESTMENT-REPORT.md` | 투자 가설·출처·반대 근거 |
| `quant` | `QUANT-REPORT.md` | 전략 명세·통계·백테스트 타당성 |
| `investment-risk` | `INVESTMENT-RISK.md` | 노출·손실 시나리오·위험 통제 |

세 역할은 같은 target 작업 폴더를 사용하며 결과를 planner에 전달한다.
`quant`는 qa의 테스트 실행을, `investment-risk`는 security의 소프트웨어 보안 감사를 대체하지 않는다.
CLI는 `run quant` / `run investment-risk`, MCP는 `quant_run` / `investment_risk_run`이며
investment와 동일하게 `requirements`·`as_of`·`root`를 받는다.
[my-stock 실행 요청문과 연결 절차](standards/reference/my-stock-investment-workflow.md)를 참고한다.


### ECC 기반 추가 스킬

agent-platform 프로젝트에는 `skill-stocktake`, `search-first`, `security-scan`,
`continuous-learning-v2`, `eval-harness`, `iterative-retrieval` 6개가 관리 패키지로
추가돼 있다. 패키지 원본은 `skills/packages/`, Claude용은 `.claude/skills/`,
Codex용은 `.agents/skills/`에 배치한다. 글로벌 설정이나 다른 프로젝트는 변경하지 않는다.

Codex에서는 다음 턴부터 새 스킬을 확인할 수 있다. 기존 Claude 세션에서 보이지 않으면
새 세션을 시작한다. 예: `search-first로 도입 대안 비교해줘`,
`skill-stocktake로 프로젝트 스킬 점검해줘`, `security-scan으로 hook 설정 검토해줘`.

ECC 원본을 플랫폼 정책에 맞춘 수정본(`ecc-e482e57-platform.1`)으로,
각 패키지에 고정 커밋·원본 해시·MIT 라이선스·변경 범위를 기록한다.
continuous-learning-v2는 명시적 피드백의 학습 후보 작성 절차이며 자동 학습 daemon은 아니다.
security-scan은 수동 점검을 제공하고 AgentShield는 선택 도구로 별도 설치하지 않았다.
역할별 조건은 [Role Skill Policy](standards/reference/role-skills.md)를 따른다.

```bash
uv --directory mcp-server run agent-platform-agent skill list --project-id agent-platform
```


### 수집 진단과 명시적 피드백

```bash
uv --directory mcp-server run agent-platform-agent doctor --root "$PWD"
uv --directory mcp-server run agent-platform-agent observe status --root "$PWD"
# summary JSON을 stdin으로 전달 (대화 전체가 아닌 선택한 피드백)
uv --directory mcp-server run agent-platform-agent feedback add --root "$PWD" --source-kind manual --kind correction < feedback.json
uv --directory mcp-server run agent-platform-agent feedback list --root "$PWD"
uv --directory mcp-server run agent-platform-agent feedback show FEEDBACK_ID --root "$PWD"
uv --directory mcp-server run agent-platform-agent feedback purge --root "$PWD"
```

`doctor`는 hook 설정과 실제 실행을 구분하고 backend별 최근 기록 및 수집 heartbeat를
표시한다. `observed`는 최근 polling 증거이며 현재 세션 수집 완료를 보증하지 않는다.
피드백 본문은 별도 `.local/learning.db`에 30일 보관하며 state export에는 포함하지 않는다.
Claude에는 `/doctor`, `/feedback` 진입점이 있고 Codex에서도 같은 CLI를 사용할 수 있다.
규칙 자동 수정이나 학습 daemon은 실행하지 않는다. 업데이트 후 기존 조회 서버는 재시작한다.
Claude SessionStart는 agent adapter만 동기화하며 오류를 경고로 표시한다.
[계약·보관·한계](standards/reference/feedback-observation.md)를 참고한다.

### 피드백을 지침 개선으로 연결

`improvement propose/list/show/evaluate/review/apply/revert`로 선택한 피드백에서
개선 후보를 만들고, Claude/Codex 기존·후보 지침을 각각 3회 이상 평가한 뒤
명시적 검토를 거쳐 적용할 수 있다. 모든 명령에 `--root`가 필요하며 후보 JSON은
`trigger`, `action`, `target`, `replacement`를 받는다.

```bash
uv --directory mcp-server run agent-platform-agent improvement list --root "$PWD"
uv --directory mcp-server run agent-platform-agent improvement show CANDIDATE_ID --root "$PWD"
uv --directory mcp-server run agent-platform-agent improvement apply CANDIDATE_ID --root "$PWD" --dry-run
```

적용 대상은 이 플랫폼의 `standards/agents/*.md`, `standards/reference/*.md`로
제한한다. 평가 통과가 자동 승인은 아니며 원본·평가 기록 변경과 근거 소실은
적용을 차단한다. 되돌리기는 이후 사용자 수정이 없을 때만 가능하다.
Claude `/improve`와 양쪽 backend 공통 CLI의
[전체 절차·평가 한계·중단 복구](standards/reference/improvement-workflow.md)를 참고한다.
state DB schema 7 업데이트 후 기존 관측 서버를 재시작해야 한다.

### 토큰 사용량 점검과 맥락 절약

```bash
uv --directory mcp-server run agent-platform-agent observe efficiency --root "$PWD"
```

최근 전역 500개 기록 중 해당 프로젝트 표본을 backend·모델·수집 경로별로 요약한다.
입력·출력·캐시 토큰의 확인된 합계와 누락 건수, 실패/중단 기록 수, 그룹별 입력 사용량 상위
실행을 제공한다. 조회 화면의 **토큰 사용량과 점검할 실행**에서도 최근 표시 표본의
요약과 상위 실행을 확인할 수 있다. 검색 필터는 실행 목록에만 적용되며 요약은 로드된
표본 전체 기준이다. native/wrapper 중복 가능성과 backend별 토큰 정의 차이 때문에
전체 합계·캐시 적중률·절감률은 추정하지 않는다. 재시도 비용과 승인 완료 업무당
비용은 아직 업무 연결이 필요하며 이번 요약에 포함하지 않는다.

Claude `/efficiency`는 이 결과를 보고 기존 graphify/iterative-retrieval 등에서
필요한 맥락과 스킬만 선택하도록 안내한다. SessionStart의 startup 이벤트에만 짧은
안내를 추가하고 resume/compact에는 반복하지 않는다. 추가 LLM 호출은 없다.
[Claude 공식 hook 계약](https://code.claude.com/docs/en/hooks#sessionstart)을 따른
handler 테스트를 수행했으며 실제 native hook 호출 검증과 토큰 절감 효과 측정은 별도다.
Codex에서는 같은 `observe efficiency` CLI와 기존 스킬을 사용한다.
