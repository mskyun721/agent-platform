---
agent: planner
feature: project-structure
status: draft
created: 2026-09-18
updated: 2026-09-18
links:
  prd: docs/refactor/project-structure/PRD.md
  task: docs/refactor/project-structure/TASK.md
  api: docs/refactor/project-structure/API-SPEC.md
---

# PRD: 프로젝트 구조 개선

## 1. 목표와 범위

플랫폼 루트를 명시적으로 대상으로 한다(root=/Users/seongkyunmoon/project/agent-platform).
.active-project는 읽거나 변경하지 않는다. 이번 산출물은 구현 전 개선 계획이며 모두 draft다.

목표: 파일의 책임과 원본 소유권을 명확히 하고, `tools/`의 34개 모듈을 기능별 패키지로 재배치한다.
외부 명령, MCP 도구, 산출물 형식, 보안 경계, DB 스키마와 데이터 위치를 보존한다.

포함: Python 모듈/테스트 분류, 최소한의 순환 참조 해소, 원본·설치본 정책, 캐시 추적 정리,
README와 구조 문서, 경로 의존 코드·CI·평가 코드 갱신.
제외: 신규 기능, HTTP API 도입, DB 스키마 변경, 실행 backend 교체, 외부 서비스 호출,
기존 로컬 작업 문서 정리, 가상환경/상태 DB 삭제, 미관리 스킬 삭제, push/PR/배포.

## 2. 확인한 현재 상태

- 런타임은 `mcp-server/src/agent_platform_mcp/`; tools에는 34개 구현 모듈과 __init__.py가 있다.
- tests에는 conftest.py 외 39개 테스트 파일이 있고, 다수가 직접 tools import와 문자열 patch 경로를 사용한다.
- config.resolve_project가 projects.resolve를 지연 import하고 projects는 config를 import한다.
- feature는 evidence/verification을 호출하며 이들은 feature의 경로 검사에 의존한다.
- store가 evidence/recovery/actions/continuation의 SCHEMA를 읽고 이 모듈들은 store를 사용한다.
- recovery/store가 실행 결과 포맷터 stdout_artifacts의 _mask에 의존한다.
- verification.VERIFIER_FILES는 기존 파일 경로 12개를 고정한다. 재배치 후 갱신 누락 시 검증이 깨진다.
- scripts/pr_logic_size.py는 --no-renames를 사용한다. 파일 이동도 전체 삭제+추가로 계산한다.
- skills/packages/drawio-skill/scripts/__pycache__ 아래 pyc 2개가 추적된다.
- 같은 이름의 스킬 디렉터리가 skills/packages, .agents/skills, .claude/skills에 존재한다.
  이름 일치만으로 내용 동일성·관리 소유권을 확정하지 않는다.
- 기존 사용자 변경: .claude/settings.json, .gitignore, AGENTS.md, CLAUDE.md 및 미추적
  .agents/, .claude/CLAUDE.md, .claude/settings.json.graphify-bak, .claude/skills/, .codex/, ARCHITECTURE.md.
- graphify query는 실행했으나 구형 node-ID 경고가 있었다. 위 의존성은 현재 Python AST와 소스로 재확인했다.

## 3. 선택한 접근

| 접근 | 이점 | 한계 | 판단 |
|---|---|---|---|
| tools 하위 폴더만 분류 | 변경이 작음 | 순환 참조와 원본 혼재가 남음 | 미선택 |
| 기능별 패키지 + 공유 규칙 최소 추출 | 탐색성과 의존성 개선, 단계별 검증 가능 | 경로 소비자 동시 수정 필요 | 추천 |
| 전면 계층화·DI·repository/service 도입 | 엄격한 추상화 가능 | 현재 규모에 비해 코드와 파일 증가 | 미선택 |

파일이 길다는 이유만으로 project.py/confluence.py를 분할하지 않는다.
먼저 책임별 재배치를 완료하고, 이 작업에 필요한 경계 추출만 수행한다.

## 4. 목표 디렉터리

```text
agent-platform/
├── AGENTS.md / CLAUDE.md / ARCHITECTURE.md / README.md
├── mcp-server/                     # 패키징·실행 위치 유지
│   ├── pyproject.toml / uv.lock
│   └── src/agent_platform_mcp/
│       ├── __init__.py / cli.py / server.py
│       ├── config.py              # 환경·정책 설정; registry 역참조 제거
│       ├── frontmatter.py         # 독립 파서 유지
│       ├── common/                # paths.py, redaction.py만
│       ├── projects/              # scaffold.py, registry.py
│       ├── lifecycle/             # 산출물·gate·검증·handoff
│       ├── execution/             # 역할 실행·프로세스·결과 해석
│       ├── state/                 # 이벤트·SQLite·복구·승인 액션
│       ├── integrations/          # Apidog·Confluence·Git 원격
│       └── skills/                # packages.py, activation.py
├── tests/                         # 위 책임별 하위 폴더 + platform/, evals/
├── evals/                         # 평가 시나리오·fixture·실행 도구
├── scripts/                       # 운영·동기화·CI 보조 명령
├── standards/                     # 대상 프로젝트 규칙
│   ├── agents/                    # 역할 지시 원본
│   └── reference/                 # 현재 운영 문서 + history/ 과거 증거
├── templates/ / workflows/        # 기존 소비자 경로 유지
├── skills/packages/               # 배포용 스킬 원본과 registry.json
├── .claude/ / .agents/ / .codex/   # CLI 발견 경로; 원본과 설치본 구별
└── .local/ / graphify-out/ / docs/ / PROMPT/  # 로컬 상태·산출물, 기존 정책 유지
```

README는 설치, 빠른 시작, 주요 명령, 디렉터리 지도, 레퍼런스 링크로 구성한다.
새 guide 루트를 만들지 않고 기존 standards/reference를 활용한다.

### 4.1 전체 모듈 이동표

기준 경로: `mcp-server/src/agent_platform_mcp/`.

| 현재 | 목표 |
|---|---|
| `tools/project.py` | `projects/scaffold.py` |
| `tools/projects.py` | `projects/registry.py` |
| `tools/feature.py` | `lifecycle/feature.py` |
| `tools/handoff.py` | `lifecycle/handoff.py` |
| `tools/evidence.py` | `lifecycle/evidence.py` |
| `tools/verification.py` | `lifecycle/verification.py` |
| `tools/profile_review.py` | `lifecycle/profile_review.py` |
| `tools/standards.py` | `lifecycle/standards.py` |
| `tools/audit.py` | `execution/audit.py` |
| `tools/backend.py` | `execution/backend.py` |
| `tools/plan.py` | `execution/plan.py` |
| `tools/qa.py` | `execution/qa.py` |
| `tools/release.py` | `execution/release.py` |
| `tools/review.py` | `execution/review.py` |
| `tools/runner.py` | `execution/runner.py` |
| `tools/monitored_process.py` | `execution/monitored_process.py` |
| `tools/native_output.py` | `execution/native_output.py` |
| `tools/stdout_artifacts.py` | `execution/stdout_artifacts.py` |
| `tools/actions.py` | `state/actions.py` |
| `tools/continuation.py` | `state/continuation.py` |
| `tools/fingerprint.py` | `state/fingerprint.py` |
| `tools/observation.py` | `state/observation.py` |
| `tools/pricing.py` | `state/pricing.py` |
| `tools/recovery.py` | `state/recovery.py` |
| `tools/state_queries.py` | `state/queries.py` |
| `tools/store.py` | `state/store.py` |
| `tools/apidog.py` | `integrations/apidog.py` |
| `tools/confluence.py` | `integrations/confluence.py` |
| `tools/git_remote.py` | `integrations/git_remote.py` |
| `tools/skill_packages.py` | `skills/packages.py` |
| `tools/skills.py` | `skills/activation.py` |
| `events.py` | `state/events.py` |
| `tools/__init__.py` | 모든 소비자 전환 후 제거; 신규 패키지 __init__.py는 빈 파일 |

### 4.2 새로 추출하는 경계

| 목표 | 가져오는 책임 | 의존성 규칙 |
|---|---|---|
| common/paths.py | feature의 이름 정규화·artifact 경로 검사, projects의 저장 경로 symlink 검사 | stdlib만 사용; 두 경로 검사 정책을 하나로 합치지 않음 |
| common/redaction.py | stdout_artifacts._mask | stdlib만 사용; masking 패턴·출력 동일 |
| state/schema.py | store/evidence/recovery/actions/continuation의 SQL 상수 | SQL·버전 0→5 순서 유지; 런타임 모듈 import 금지 |
| lifecycle/policy.py | verification.profile_hash, verifier_hash, _policy, VERIFIER_FILES | config/common만 참조; evidence와 verification은 이를 사용 |
| projects/registry.py | 기존 registry + config.resolve_project/resolve_project_dir 역할 | config는 registry를 import하지 않음; docs_dir의 경로 해석 호출도 전환 |

config.docs_dir 등 경로 해석의 실제 호출 체인을 구현 전 다시 추적하고 registry 의존 부분을
projects/registry.py로 함께 옮긴다. config에 호환 wrapper를 남겨 최종 순환을 숨기지 않는다.
이름 변경은 역할 구분에 필요한 scaffold/registry/packages/activation/queries와 추출 helper에 한정한다.

### 4.3 의존성 허용 범위

- cli/server는 조립 지점이다. 도메인 패키지에서 cli/server를 import하지 않는다.
- common과 frontmatter는 stdlib 전용, config는 도메인 패키지를 import하지 않는다.
- projects → config/common; skills → projects/config/frontmatter/common.
- state/schema, events, pricing, fingerprint는 상위 실행·gate 모듈을 import하지 않는다.
- state/store → config/common/events/pricing/schema; lifecycle/execution import를 제거한다.
- state/observation·recovery → projects/skills 및 state 내부. lifecycle/execution import 금지.
- execution → lifecycle/projects/state/common/config; lifecycle은 execution의 독립 프로세스 실행기
  monitored_process만 참조 가능하다. monitored_process는 stdlib 전용을 유지한다.
- integrations는 config/projects/lifecycle/state를 사용할 수 있으나 state는 integrations를 import하지 않는다.
- 기존 함수 내부 지연 import도 검사한다. 새 순환을 지연 import로 숨기지 않는다.

## 5. 유지할 계약과 위험

위험 high: 경로·allowlist, 검증 승인 fingerprint, 관측/복구/액션 승인 경계에 걸친 변경이다.
완료 전 별도 SECURITY-AUDIT.md 검토가 필요하다. 계획 단계에서는 감사 완료를 주장하지 않는다.

| ID | 규칙 |
|---|---|
| BR-1 | 명령 이름·옵션·MCP schema·응답·오류 의미 유지 |
| BR-2 | 외부 프로젝트 allowlist, symlink 거부, worktree 실제 경로, 명시적 root 예외 유지 |
| BR-3 | DB 스키마/이벤트/registry/active-project/로컬 파일 위치 유지 |
| BR-4 | 이동으로 바뀐 verifier fingerprint는 changed/unreviewed로 취급; 자동 재승인 금지 |
| BR-5 | 기존 사용자 diff와 unmanaged 스킬은 보존; 원본·설치본 동일성 검증 전 삭제 금지 |
| BR-6 | 각 단계가 독립 검증 가능하고 PR별 순수 로직 추가+삭제 500라인 이하 |

Python 내부 import 경로는 바뀐다. 저장소 내 소비자는 같은 단계에 전환한다.
외부 Python 소비자 존재는 아직 확인하지 못했으므로 지원 계약이라고 가정하지 않는다.
README에 내부 import 변경을 기록한다. 영구 tools facade나 sys.modules alias는 만들지 않는다.

## 6. 처리 흐름

[FLOW.drawio](FLOW.drawio)는 구현 진행/검증/실패 중단 흐름이다. 새 사용자 기능 흐름은 없다.

| 흐름 노드 | BR | AC | 성공/실패 의미 |
|---|---|---|---|
| baseline, baseline-ok | BR-5 | AC-1 | 기존 변경·실패 기록; 실패 시 원인 분리 후 중단 |
| boundaries | BR-2, BR-3 | AC-3, AC-4 | 보안·DB 경계 추출 |
| move | BR-1, BR-6 | AC-2, AC-5 | 모듈·소비자 동시 전환 |
| verify | BR-1, BR-4 | AC-2, AC-3, AC-6 | 회귀·경로·승인 무효화 검사 |
| stop | BR-5 | AC-1 | 현재 단계만 수정/복구; 사용자 변경 유지 |
| finish | BR-5, BR-6 | AC-7, AC-8 | 문서·소유권·구조 검토 및 인계 |

## 7. 수락 기준

| AC | 완료 기준 | 검증 |
|---|---|---|
| AC-1 | 기존 사용자 diff와 로컬 데이터 보존 | 시작/종료 diff 목록 비교, 실제 DB 변경 없음 |
| AC-2 | CLI/MCP 계약과 기존 테스트 동작 유지 | schema/argparse 비교, 전체 pytest |
| AC-3 | 경로 검증과 과거 승인 무효화 유지 | project/config/risk/profile/evidence 회귀 |
| AC-4 | SQLite 버전 0~5 fixture 읽기·업그레이드·데이터 보존 | 임시 DB 통합 테스트 |
| AC-5 | 34개 tools 모듈의 이동표 반영, 순환 경계 해소 | import 스캔·새 프로세스 import smoke |
| AC-6 | 검증기 파일 목록이 모두 존재하고 안전 관련 추출 파일을 포함 | profile review 테스트, 누락 시 fail-closed |
| AC-7 | 테스트 39개 파일의 수집 보존, 새 검증 테스트 추가 | 수집 전후 test 이름 정규화 비교 |
| AC-8 | 원본/설치본 문서화, pyc 추적 0, README/ARCHITECTURE 정합성 | git ls-files, docs/role 검사, graphify update |

## 8. 가정과 기록

- uv 패키지 루트와 CLI 발견 경로는 유지한다. 루트 항목 수를 줄이려고 설정을 임의 이동하지 않는다.
- reference/history 이동은 문서 읽기 도구의 중첩 경로 지원 검증 후 수행한다.
- 테스트 실행과 보안 감사는 구현 단계 작업이다. 현재 분석은 정적 확인이다.

## Skill Usage

| skill | tier | mode | version | status | reason / evidence |
|---|---|---|---|---|---|
| brainstorming | main | manual | unknown | used | 범위 비교 후 사용자가 코드 재배치를 포함한 계획 요청 |
| writing-plans | main | manual | unknown | used | 파일 이동표·단계·검증·복구 계획 작성 |
| graphify | auxiliary | manual | unknown | used | graphify query 수행, 구형 ID 경고; AST로 재확인 |
| ponytail | auxiliary | manual | unknown | used | lite: 새 계층/DI 대신 기존 함수 이동과 필수 경계 추출 |
| drawio-skill | auxiliary | manual | 3.4.0 | used | FLOW.drawio XML 작성; 검증 결과는 TASK에 기록 |
| verification-before-completion | auxiliary | manual | unknown | used | 이동표/문서 링크/front-matter 확인; FLOW strict 검증 0 error, 0 warning |
