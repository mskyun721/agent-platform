# 시작 가이드

agent-platform 을 처음 받아서 쓰는 사람을 위한 안내다. 명령은 모두 플랫폼 폴더에서 실행한다.
세부 옵션과 내부 동작은 [README](../../README.md)와 [setup.md](setup.md)에 있다.

## 1. 준비물

| 도구 | 필요 | 설치 |
|---|---|---|
| `git`, `python3` | 필수 | OS 기본 |
| `uv` | 필수 (MCP 서버·CLI 실행) | `brew install uv` |
| AI CLI 하나 이상 | 필수 | Claude Code `npm install -g @anthropic-ai/claude-code` 후 `claude login` / Codex `codex login` / Gemini CLI / Copilot CLI |
| `graphify` | 권장 (코드 그래프) | `uv tool install graphifyy` |
| `whodb` | 선택 (dba 역할의 DB 실측) | `npm i -g @clidey/whodb` |

## 2. 설치 (한 번)

```bash
git clone <저장소 주소> agent-platform && cd agent-platform
./scripts/setup.sh --roots ~/Projects --target ~/Projects/my-service
```

- `--roots`: workspace, 즉 플랫폼이 읽고 써도 되는 **상위 폴더**. 여러 개는 `:` 로 잇는다. 이 밖의 경로는 (따로 등록하지 않는 한) 거부된다.
- `--target`: 작업할 프로젝트. 로컬 경로, 또는 git 주소(`https://…`, `git@…`)를 주면 첫 번째 workspace 안에 clone 한다. 여러 번 줄 수 있고 첫 번째가 기본 대상이 된다.
- 두 값 모두 플랫폼 루트의 `.agent-projects.json` 한 파일에 기록된다(자동 생성, git 제외). `.env` 에는 비밀값만 둔다.

끝에 "doctor 통과"가 나오면 완료다. 스크립트는 `.env` 생성, 의존성 설치, Claude/Gemini/Copilot 설정 생성,
스킬 설치(`.claude/skills`, `.agents/skills`), workspace·대상 프로젝트 등록, 예전 설정 이전(`project-migrate`)까지 한다. 다시 실행해도 기존 `.env` 와 파일을 덮어쓰지 않는다.

예전 방식(`.env` 의 `AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS`, `.active-project`)으로 설치했다면 `apa project-migrate --dry-run` 으로 확인한 뒤 `apa project-migrate` 를 실행하고, 안내대로 `.env` 의 그 줄을 직접 지운다. `.agent-platform.env` 가 남아 있으면 값을 `.env` 로 합치고 삭제한다.

Codex 를 쓰면 MCP 등록을 한 번 더 한다(스크립트 마지막에 절대경로가 채워진 명령이 출력된다).

```bash
codex mcp add agent-platform -- uv --directory /절대경로/agent-platform/mcp-server run agent-platform-mcp
```

Confluence·Apidog·Notion 연동을 쓸 사람만 `.env` 에 토큰을 추가한다. 키 이름은 `.env.example` 에 있다.
산출물 게시 대상은 프로젝트마다 `project-publish-set <id> --target none|confluence|notion` 으로 고르고 `publish <feature>` 로 올린다(기본 none, `standards/reference/notion-integration.md`).

## 3. 대상 프로젝트 관리

```bash
alias apa='uv --directory /절대경로/agent-platform/mcp-server run agent-platform-agent'

apa project-list                                   # 등록 목록, 기본 대상(default), workspace
apa project-add ~/Projects/another-service         # 로컬 프로젝트 등록 (ID = 폴더명)
apa project-add https://github.com/org/svc.git     # 원격 저장소: 첫 workspace 에 clone 후 등록
apa project-use another-service                    # 기본 대상 전환 (등록 ID 또는 폴더명)
apa project-workspace add ~/Work                   # 프로젝트를 둘 상위 폴더 추가
```

- 목록은 `.agent-projects.json` 의 `projects`, 기본 대상은 `default` 다. 직접 편집하지 말고 위 명령을 쓴다.
- workspace 추가와 workspace 밖 경로 등록은 사람이 CLI 로만 한다. AI(MCP)는 범위를 넓힐 수 없다.
- 기본이 아닌 프로젝트는 요청할 때 이름을 말하면 된다: "kcp-backup 프로젝트에서 …", CLI 는 `--root kcp-backup`.
- 새 Spring 프로젝트를 만들 때는 AI 세션에서 `/init-project <이름> <패키지>`.
- 대상 프로젝트에는 구조 규칙 문서가 필요하다: `cp templates/ARCHITECTURE.md <대상>/ARCHITECTURE.md` 후 실제 구조에 맞게 고친다.

## 4. 첫 작업

플랫폼 폴더에서 AI CLI 를 연다(`claude`, `codex`, `gemini`, `copilot`). 설정은 자동으로 읽힌다.

어느 계약을 쓸지 모르면 **work-v1 을 먼저** 고른다. 단일 기능이고 API·스키마 변경이 없거나 경미하면 `WORK.md` 하나로 충분하고,
신규 API 여러 개·신규 테이블·외부 연동·PR 여러 개 중 하나라도 해당하면 full 이다. "이거 만들어줘" 라고만 해도 세션이 이 기준으로
판단해 보여 주고 확인을 받는다.

작은 수정:

```text
/new-feature fix/token-expiry --contract work-v1
backend 역할로 fix/token-expiry 를 WORK.md 기준으로 구현해줘
reviewer 역할로 fix/token-expiry 리뷰해줘
```

큰 기능:

```text
/new-feature payment-cancel
planner 로 payment-cancel PRD/TASK 작성해줘. 요구사항: …
backend 로 payment-cancel 구현해줘
reviewer 와 security 로 교차 검증해줘
/gate-check payment-cancel
/handoff qa payment-cancel
```

산출물은 대상 프로젝트의 `docs/<type>/<name>/` 에 `status: draft` 로 생긴다. `approved` 로 바꾸는 것은 사람이 한다.
PR 생성·push·배포는 항상 사용자 확인 후에만 실행된다.

### 기능 SPEC

작업 문서는 변경 한 건의 기록이고, 기능의 현재 상태는 `docs/specs/<slug>/SPEC.md` 하나에 모은다.

- planner(work-v1 에서는 세션)가 `spec list` 를 보고 작업 front-matter `spec: <slug>` 와 "소속 기능" 검토 요청 행을 제안한다. 신규 기능이면 확정 후 `apa spec new <slug> --title "<제목>"`.
- 각 역할은 SPEC·이번 작업 문서·diff·필수 입력만 먼저 읽는다(역할 지침 `# Read Scope`). 보관한 작업 폴더는 읽지 않는다.
- cicd 가 PR 때 SPEC 2~5절을 고치고 draft 로 되돌린 뒤 `apa spec history-add <slug> --work <type>/<name> --summary "…" --pr <URL>`, `apa spec index` 를 같은 PR 에 넣는다.
- 머지 후 게시 대상이 있으면 `apa publish --spec <slug>` 를 제안한다(실행은 확인 후). 끝난 작업은 `apa feature-archive <type>/<name>` 으로 보관한다.
- 기존 프로젝트의 첫 SPEC 은 `apa spec bootstrap` 이 모아 주는 출처(승인 문서·API·migration)로 planner 가 쓴다. SPEC 연결을 backend 인계 조건으로 만들려면 사용자가 `apa project-spec-set <id> --required true` 를 실행한다.

### 토큰 측정

```bash
apa observe capture on --root "$PWD"                                     # 수집 켜기 (원문 7일 보관, 확인 필요)
apa observe usage --root my-service --feature features/payment-cancel   # 기능 하나의 역할별 토큰·재작업·품질
apa observe usage --root my-service --by type                            # 작업 유형별 평균·중앙값
```

역할을 직접 수행하는 세션은 그 세션 안에서 기능 키로 `state start <type>/<name> --role <role> …` / `state end` 를 남긴다(역할 지침이 안내한다).
`.agent-config.json` 의 `token_budget` 을 두면 gate·handoff 결과에 예산 경고(`usage`)가 붙는다. 경고일 뿐 통과 여부는 바뀌지 않는다(README §9a).

## 5. 업데이트

```bash
git pull && ./scripts/setup.sh
```

새로 추가된 스킬과 바뀐 호스트 설정이 반영된다. 기존 설정은 유지된다.

업데이트 뒤에는 MCP 서버와 `observe serve` 를 다시 시작한다. 실행 기록 DB(`.local/state.db`)의 버전이 올라가면 예전 코드로 돌던 프로세스는
기록이 조용히 실패한다(`stored: false`). 예전 버전으로 되돌리는 방법은 README §9 "업그레이드·되돌리기" 에 있다.

## 6. 자주 겪는 문제

| 증상 | 원인과 해결 |
|---|---|
| `outside the allowed MCP roots` / `outside the workspaces` | 대상이 허용 범위 밖이다. `apa project-workspace add <상위 폴더>` 또는 `apa project-add <경로>` 후 `python3 scripts/sync_claude_settings.py` |
| `No workspace is configured` | workspace 가 없다. `apa project-workspace add <상위 폴더>` |
| `No active target project` | 기본 대상이 없다. `apa project-add <경로> --default` 또는 `apa project-use <ID>` |
| `.active-project is deprecated` / `AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS is deprecated` 경고 | 예전 설정이 남아 있다. `apa project-migrate` 후 `.env` 의 그 줄을 지운다 |
| 스킬이 안 보인다 | `./scripts/setup.sh` 실행 후 **새 세션**을 연다. 상태 확인: `apa skill list --project-id agent-platform` |
| Codex 에서 MCP 툴이 없다 | `codex mcp list` 에서 enabled 인지, 등록 경로가 절대경로인지 확인 |
| 대상 프로젝트 폴더에서 Claude 를 열면 MCP 가 없다 | user 스코프로 한 번 더 등록: `claude mcp add agent-platform -s user -- uv --directory /절대경로/agent-platform/mcp-server run agent-platform-mcp` |
| `.agent-platform.env is deprecated` 경고 | 예전 이름의 환경 파일이 남아 있다. 값을 `.env` 로 옮기고 삭제 |
| 무엇이 잘못됐는지 모르겠다 | `apa doctor --root .` 가 도구·설정 파일·수집 상태를 보여준다 |

## 7. 파일이 어디에 있는지

| 파일 | 누구 것 | 내용 |
|---|---|---|
| `.env` | 개인 (git 제외) | 연동 토큰 (비밀값만) |
| `.agent-projects.json` | 개인 (git 제외) | 대상 프로젝트 목록·기본 대상·workspace (자동 생성) |
| `.agent-projects.lock` | 자동 (git 제외) | 레지스트리 쓰기 잠금 파일 |
| `.agent-config.json` | 팀 공통 (git) | 역할별 AI·모델, 검증 명령, 위험 경로 |
| `standards/agents/` | 팀 공통 (git) | 역할 지침 원본. `.claude/agents` 등은 여기서 생성된다 |
| `skills/packages/` | 팀 공통 (git) | 스킬 원본. `.claude/skills`, `.agents/skills` 는 여기서 생성된다 |
