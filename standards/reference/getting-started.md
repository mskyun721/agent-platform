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

- `--roots`: 플랫폼이 읽고 써도 되는 **상위 폴더**. 여러 개는 `:` 로 잇는다. 이 밖의 경로는 모두 거부된다.
- `--target`: 작업할 프로젝트. 로컬 경로, 또는 git 주소(`https://…`, `git@…`)를 주면 첫 번째 `--roots` 폴더 안에 clone 한다. 여러 번 줄 수 있고 첫 번째가 기본 대상이 된다.

끝에 "doctor 통과"가 나오면 완료다. 스크립트는 `.env` 생성, 의존성 설치, Claude/Gemini/Copilot 설정 생성,
스킬 설치(`.claude/skills`, `.agents/skills`), 대상 프로젝트 등록을 한다. 다시 실행해도 기존 `.env` 와 파일을 덮어쓰지 않는다.

Codex 를 쓰면 MCP 등록을 한 번 더 한다(스크립트 마지막에 절대경로가 채워진 명령이 출력된다).

```bash
codex mcp add agent-platform -- uv --directory /절대경로/agent-platform/mcp-server run agent-platform-mcp
```

Confluence·Apidog 연동을 쓸 사람만 `.env` 에 토큰을 추가한다. 키 이름은 `.env.example` 에 있다.

## 3. 대상 프로젝트 관리

```bash
alias apa='uv --directory /절대경로/agent-platform/mcp-server run agent-platform-agent'

apa project-list                                   # 현재 목록과 기본 대상
apa project-add ~/Projects/another-service         # 로컬 프로젝트 추가
apa project-add https://github.com/org/svc.git     # 원격 저장소: clone 후 추가
apa project-use another-service                    # 기본 대상 전환
```

- 목록은 `.active-project` 파일이다. 한 줄에 경로 하나, **첫 줄이 기본 대상**이다. 직접 편집해도 된다.
- 기본이 아닌 프로젝트는 요청할 때 이름을 말하면 된다: "kcp-backup 프로젝트에서 …", CLI 는 `--root kcp-backup`.
- 새 Spring 프로젝트를 만들 때는 AI 세션에서 `/init-project <이름> <패키지>`.
- 대상 프로젝트에는 구조 규칙 문서가 필요하다: `cp templates/ARCHITECTURE.md <대상>/ARCHITECTURE.md` 후 실제 구조에 맞게 고친다.

## 4. 첫 작업

플랫폼 폴더에서 AI CLI 를 연다(`claude`, `codex`, `gemini`, `copilot`). 설정은 자동으로 읽힌다.

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

## 5. 업데이트

```bash
git pull && ./scripts/setup.sh
```

새로 추가된 스킬과 바뀐 호스트 설정이 반영된다. 기존 설정은 유지된다.

## 6. 자주 겪는 문제

| 증상 | 원인과 해결 |
|---|---|
| `outside the allowed MCP roots` | 대상이 허용 범위 밖이다. `.env` 의 `AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS` 에 상위 폴더를 추가하고 `./scripts/setup.sh` 재실행 |
| `AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS is not set` | `.env` 가 없거나 값이 비었다. `cp .env.example .env` 후 수정 |
| `No active target project` | 대상 목록이 비었다. `apa project-add <경로>` |
| 스킬이 안 보인다 | `./scripts/setup.sh` 실행 후 **새 세션**을 연다. 상태 확인: `apa skill list --project-id agent-platform` |
| Codex 에서 MCP 툴이 없다 | `codex mcp list` 에서 enabled 인지, 등록 경로가 절대경로인지 확인 |
| 대상 프로젝트 폴더에서 Claude 를 열면 MCP 가 없다 | user 스코프로 한 번 더 등록: `claude mcp add agent-platform -s user -- uv --directory /절대경로/agent-platform/mcp-server run agent-platform-mcp` |
| `.agent-platform.env is deprecated` 경고 | 예전 이름의 환경 파일이 남아 있다. 값을 `.env` 로 옮기고 삭제 |
| 무엇이 잘못됐는지 모르겠다 | `apa doctor --root .` 가 도구·설정 파일·수집 상태를 보여준다 |

## 7. 파일이 어디에 있는지

| 파일 | 누구 것 | 내용 |
|---|---|---|
| `.env` | 개인 (git 제외) | 허용 범위, 연동 토큰 |
| `.active-project`, `.agent-projects.json` | 개인 (git 제외) | 대상 프로젝트 목록, 등록 ID |
| `.agent-config.json` | 팀 공통 (git) | 역할별 AI·모델, 검증 명령, 위험 경로 |
| `standards/agents/` | 팀 공통 (git) | 역할 지침 원본. `.claude/agents` 등은 여기서 생성된다 |
| `skills/packages/` | 팀 공통 (git) | 스킬 원본. `.claude/skills`, `.agents/skills` 는 여기서 생성된다 |
