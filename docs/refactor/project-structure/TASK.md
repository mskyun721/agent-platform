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

# TASK: 프로젝트 구조 개선 Implementation Plan

> 실행 담당: 승인된 범위를 executing-plans로 단계별 수행한다. 자동 subagent 위임은 하지 않는다.
> 이번 요청은 계획 작성까지다. 체크박스는 구현 진행 상황이며 아직 완료된 단계가 없다.

**Goal:** 외부 동작을 유지하면서 Python 코드와 테스트를 책임별로 재배치하고 원본/생성물 구분을 명확히 한다.

**Architecture:** 기능별 패키지로 이동하되 common에는 경로 검사와 마스킹만 추출한다.
SQLite schema와 검증 정책을 실행 코드로부터 분리해 주요 양방향 참조를 해소한다.

**Tech Stack:** Python 3.11+, FastMCP, uv, pytest, SQLite, 기존 표준 라이브러리.

## 실행 규칙

- 모든 명령은 플랫폼 repo 루트 기준. root는 이 checkout을 명시하며 .active-project를 변경하지 않는다.
- PRD의 이동표가 파일 배치 기준이다. HTTP 기능 추가가 없어 endpoint별 Phase는 해당 없다.
- 각 하위 작업은 import·문자열 patch·경로 fixture·소비자 변경과 관련 테스트를 함께 포함한다.
- 기존 실패를 고친 것으로 보고하거나 이 작업과 무관한 사용자 diff를 커밋에 포함하지 않는다.
- Phase별 커밋 해시는 실행 후 기록한다. 현재는 전 Phase `commit: not_created`다.
- PR 경계는 아래 하위 작업 기준이며 변경량 검사 결과 500라인을 초과하면 더 나눈다.
  import/주석/테스트/설정 제외 규칙을 유지한다. 이동량과 실제 로직 변경량을 별도 보고한다.
- 완성 상태에는 tools 호환 facade가 없다. 중간 커밋은 아직 이동하지 않은 tools 모듈을 허용한다.

## Phase 0 — 기준선과 계약 고정

**대상:** 기존 git diff, tests/, mcp-server/pyproject.toml, cli.py, server.py.
**산출물:** 이 폴더 안 baseline.txt, contracts-before.json (구현 시 생성; 원문/시크릿 없음).

- [ ] `git status --short`와 관련 diff로 사용자 변경 범위를 기록한다. stash/reset/clean을 사용하지 않는다.
- [ ] 현재 환경에서 아래 기준선 명령을 실행하고 실제 통과 수·수집 수·실패를 기록한다.

```bash
uv --directory mcp-server run --locked --dev python -m pytest ../tests --collect-only -q
uv --directory mcp-server run --locked --dev python -m pytest ../tests -q
python3 scripts/sync_claude_settings.py --agents-only --check
uv --directory mcp-server run --locked --dev agent-platform-agent --help
```

- [ ] MCP 도구의 이름/inputSchema와 argparse 명령/옵션/기본값을 현재 설치 API로 정규화해 저장한다.
  description 변경과 기능 schema 변경을 구분한다. 원격 AI/Confluence/Apidog를 호출하지 않는다.
- [ ] tests/test_structure_ref.py와 tests/test_cli_wrappers.py에서 기존 경로·계약 회귀 범위를 확인한다.
  새 `tests/test_public_contracts.py`에 fresh process import, MCP stdio initialize/list_tools,
  CLI help 및 실패 exit code 검증을 넣는다. 정상 실행에는 subprocess timeout을 둔다.
- [ ] 실패가 있으면 기존 실패인지 먼저 분류한다. 기준선 불명확 상태에서 대량 이동하지 않는다.

**완료:** baseline과 공개 계약 비교 기준 확보. **commit:** not_created.

## Phase 1 — 변경량 검사와 추적 파일 정돈

### 1A. 이동을 인식하는 변경량 검사

**수정:** scripts/pr_logic_size.py, tests/test_pr_logic_size.py.

- [ ] 임시 Git 저장소 fixture로 순수 rename=0, rename+값 변경=2, copy=신규 로직 전체,
  rename 미검출=보수적 전체 계산, secret 경로 rename=본문 미열람을 검증하는 실패 테스트를 추가한다.
- [ ] Git name-status -z rename 쌍을 파싱하고 `compare(new_path, old_content, new_content)`로 계산한다.
  old/new 양쪽 경로에 protected-file 검사를 먼저 적용한다. 코드→문서/테스트 이동은 예전 코드가
  제외되지 않게 양쪽 분류를 기록하고 수동 검토 대상으로 만든다.
- [ ] 순수 이동량은 별도 필드에 보고한다. 기존 report의 logic_lines/within_limit 의미를 유지한다.
  rename 탐지 실패를 임의로 0 처리하거나 확장자 변경으로 제한을 우회하지 않는다.
- [ ] `uv --directory mcp-server run --locked --dev python -m pytest ../tests/test_pr_logic_size.py -q`
  실행 후 전체 테스트를 실행한다. 기대: 기존 테스트와 신규 rename/보호 경계 케이스 통과.

### 1B. 캐시와 스킬 소유권

**수정:** .gitignore, skills/registry.json(해시 영향 있을 때), README.md.
**추적 해제 대상:** skills/packages/drawio-skill/scripts/__pycache__/autolayout.cpython-314.pyc,
diagram_ir.cpython-314.pyc.

- [ ] .gitignore의 기존 사용자 diff를 보존하며 `__pycache__/`, `*.py[cod]`를 공통 규칙으로 정돈한다.
  .local, 등록 프로젝트, 환경 파일 보호를 유지한다. JVM ignore 전체 삭제는 자동 수행하지 않는다.
- [ ] 패키지 fingerprint가 pyc를 포함하는지 확인한다. 포함하면 단순 ignore만으로 해결되지 않으므로
  packages.fingerprint에서 __pycache__와 pyc/pyo를 제외하는 규칙과 테스트를 먼저 추가한다.
  `.py` 변경에는 hash가 변하고 pyc 생성에는 변하지 않는지 검증한다.
- [ ] 두 pyc는 내용 확인 없이 Git 추적만 해제한다. registry의 패키지 hash는 정상 관리 명령을 통해
  갱신한다. 기존 managed 설치의 stale 상태를 숨기거나 unmanaged 디렉터리를 덮어쓰지 않는다.
- [ ] .agents/.claude/.codex의 관리 marker·파일 목록·내용 차이를 보호 파일 제외 규칙 아래 비교한다.
  배포 원본은 skills/packages, 설치본은 CLI별 경로로 문서화한다. graphify 등 외부 설치는 그대로 둔다.
- [ ] 백업 파일은 현재 diff와 사용 여부를 확인해 정리 후보로 기록한다. 이름만 보고 삭제하지 않는다.
- [ ] `test_skill_packages.py`, `test_skill_activation.py` 실행. 추적 pyc 0, 스킬 source hash와
  설치 상태가 설명 가능한지 확인한다.

**PR:** 1A와 1B 분리. **commit:** not_created.

## Phase 2 — 공통 경계와 저장 계약 분리

**생성:** common/__init__.py, common/paths.py, common/redaction.py,
state/__init__.py, state/schema.py, lifecycle/__init__.py, lifecycle/policy.py.
모두 mcp-server/src/agent_platform_mcp 아래 경로다.

### 2A. 이름·경로 검사

- [ ] tools/feature.py의 FEATURE_NAME_RE, _ensure_safe_name, canonical_feature, _safe_path와
  tools/projects.py의 _safe_storage를 common/paths.py로 이동한다. 함수의 에러 의미·symlink 검사를 보존한다.
- [ ] 호출자(roles/runner/evidence/observation/store/verification/skill_packages/scripts/docs_stats)를
  새 모듈로 전환한다. 테스트 patch는 lookup이 실제 발생하는 모듈을 가리키게 한다.
- [ ] test_feature_tools, test_project_registry, test_skill_packages, test_risk, test_wrapper_context 실행.
  artifact 탈출, 심볼릭 링크, 명시적 platform root 허용, 외부 allowlist 거부를 재검증한다.

### 2B. 마스킹

- [ ] tools/stdout_artifacts.py의 _mask만 common/redaction.py로 이동한다.
  stdout_artifacts/recovery/store가 이를 직접 참조한다. 정규식과 반환값은 변경하지 않는다.
- [ ] test_stdout_artifacts, test_store, test_recovery 실행. 유효하지 않은 보고서 원문이 저장되지 않는지 확인한다.

### 2C. SQL 상수

- [ ] 각 SCHEMA를 state/schema.py에 RUN_SCHEMA/EVIDENCE_SCHEMA/RECOVERY_SCHEMA/
  ACTION_SCHEMA/CONTINUATION_SCHEMA 이름으로 옮긴다. 한 schema씩 독립 PR로 나눌 수 있다.
- [ ] store의 버전 조건과 트랜잭션 순서는 유지하고 상위 기능 모듈 import를 없앤다.
  schema 번호 추가, SQL 수정, 기존 데이터 재작성은 수행하지 않는다.
- [ ] `tests/test_schema_compatibility.py`에 버전 0~5 임시 SQLite fixture를 만들고 open 후
  user_version=5, 기존 레코드 보존, 중복 open 멱등성을 검증한다.
- [ ] test_store, test_evidence, test_recovery, test_actions, test_state_queries와 새 schema 테스트 실행.

### 2D. 검증 정책

- [ ] tools/verification.py의 profile_hash/verifier_hash/_policy/VERIFIER_FILES를 lifecycle/policy.py로 추출한다.
  evidence/profile_review는 policy만 참조하고 policy는 실행 모듈을 import하지 않는다.
- [ ] VERIFIER_FILES에 common의 새 안전 검사·마스킹, state/schema.py, lifecycle/policy.py를 포함한다.
  추출된 파일이 fingerprint 범위 밖으로 빠지지 않게 한다.
- [ ] test_profile_review, test_evidence, test_p0 실행. 과거 reviewed_verifier_hash가 유효해지지 않고
  소스 누락·symlink가 실패로 처리되는지 확인한다.

**PR:** 2A~2D 분리, SQL 추출은 schema별 추가 분할. **commit:** not_created.

## Phase 3 — 기능별 패키지 재배치

**기준:** PRD §4.1 전체 이동표. 별도 entrypoint 이동 없음.

모든 배치에서 아래 순서를 반복한다.

1. 현재 import/patch 문자열/VERIFIER_FILES/fixture 경로를 `rg`로 확인한다.
2. 대상 모듈을 이동하고 소비자 import를 갱신한다. 기능 로직 변경은 별도 커밋이다.
3. 해당 모듈이 VERIFIER_FILES 대상이면 새 경로로 바꾸고 fixture도 갱신한다.
4. 대상 테스트 → 전체 pytest → 새 프로세스 CLI/MCP import를 확인한다.
5. 이전 fingerprint가 변경으로 감지되는지 확인하고 이동량/로직 변경량을 기록한다.

| 배치 | 이동·수정 범위 | 집중 검증 |
|---|---|---|
| 3A projects | project→scaffold, projects→registry; config의 registry 의존 해석 함수와 호출자 전환 | test_config, test_project_tools, test_project_registry, test_docs_stats |
| 3B skills | skill_packages→packages, skills→activation; evals/skill_smoke.py, skill_judge.py | test_skill_packages, test_skill_activation |
| 3C state 기본 | events, pricing, fingerprint, store | test_events, test_store, test_fingerprint, test_schema_compatibility |
| 3D state 실행 기록 | observation, recovery, continuation, actions, state_queries→queries | test_observation, test_recovery, test_actions, test_state_queries, test_trace_context |
| 3E execution | 6개 역할 wrapper, runner, monitored_process, native_output, stdout_artifacts | test_agent_runner, test_cli_wrappers, test_native_output, test_monitored_process, test_stdout_artifacts, test_wrapper_context, test_curated_context, test_role_prompts |
| 3F lifecycle | feature, handoff, evidence, verification, profile_review, standards | test_feature_tools, test_evidence, test_profile_review, test_work_contract, test_work_lifecycle, test_risk, test_verification_retry, test_drawio_gate, test_p0 |
| 3G integrations | apidog, confluence, git_remote | test_confluence, test_actions, MCP schema 비교 |

### 3A 해석 경계 상세

config의 resolve_project/resolve_project_dir 및 docs_dir에서 registry.resolve를 호출하는 경로를
projects/registry.py로 이관한다. 단순 환경·allowlist·기본 docs 루트는 config에 유지한다.
기존 호출 서명/오류 의미를 유지하되 내부 import 경로는 전환한다. config→projects import는 최종 0건.

### 모든 배치의 소비자 목록

- mcp-server/src/agent_platform_mcp/cli.py, server.py 및 다른 runtime 모듈.
- tests의 import와 `patch("agent_platform_mcp.tools..."...)` 문자열.
- scripts/docs_stats.py.
- evals/auto.py, evals/direct_observation_smoke.py, evals/skill_smoke.py, evals/skill_judge.py.
- test_profile_review.py의 verifier 경로 fixture, verification/policy의 고정 파일 목록.
- README.md, mcp-server/README.md, ARCHITECTURE.md의 코드 경로.

예를 들어 다음 import 전환을 적용한다(전면 텍스트 치환은 금지).

```python
# before
from agent_platform_mcp.tools import projects, skill_packages, skills
# after
from agent_platform_mcp.projects import registry as projects
from agent_platform_mcp.skills import packages as skill_packages, activation as skills
```

모듈 alias를 유지하면 로직 diff를 줄일 수 있다. 문자열 patch는 alias가 아니라 실제
정의/lookup 경로로 별도 갱신한다. tools/__init__.py의 기존 편의 export 소비자도 확인한다.

**PR:** 3A~3G 각각 독립, 크면 모듈 단위로 나눔. **commit:** not_created.

## Phase 4 — 테스트 구조와 아키텍처 회귀

**수정:** tests/ 전체 경로, tests/conftest.py, 경로 기반 테스트, .github/workflows/ci.yml(필요할 때).

- [ ] 테스트가 `Path(__file__).parents[1]`로 repo를 찾는 코드를 먼저 공통화한다.
  pytest fixture를 이용하거나 테스트 import 시에는 AGENTS.md와 mcp-server/pyproject.toml을
  함께 가진 상위 경로를 탐색한다. 디렉터리 깊이 상수를 2로 늘리는 임시 수정은 하지 않는다.
- [ ] 아래 표대로 파일을 이동한다. conftest.py는 tests 루트에 둔다.
- [ ] 기존 test nodeid에서 디렉터리 부분을 정규화해 (파일명, 클래스, 테스트명) 집합을 비교한다.
  수집 개수만 같다는 이유로 동등하다고 판단하지 않는다. 신규 테스트는 별도로 설명한다.
- [ ] `tests/platform/test_architecture.py`에서 AST로 함수 내부 import까지 검사한다.
  common의 stdlib 경계, config의 도메인 역참조, state/store의 상위 참조,
  도메인의 cli/server 역참조, tools import 잔존을 실패로 처리한다.
- [ ] 전체 테스트 및 공개 계약 비교가 통과한 후 빈 tools 디렉터리를 제거한다.

### 기존 테스트 이동표

| 이동 대상 폴더 | 파일명(test_ 및 .py 생략) |
|---|---|
| `tests/projects/` | config, project_registry, project_tools |
| `tests/skills/` | skill_packages, skill_activation |
| `tests/state/` | events, store, fingerprint, observation, recovery, actions, state_queries, trace_context |
| `tests/execution/` | agent_runner, cli_wrappers, native_output, monitored_process, stdout_artifacts, wrapper_context, curated_context, role_prompts |
| `tests/lifecycle/` | feature_tools, evidence, profile_review, work_contract, work_lifecycle, risk, verification_retry, drawio_gate, p0 |
| `tests/integrations/` | confluence |
| `tests/evals/` | evals_auto, evals_runner |
| `tests/platform/` | capabilities, claude_settings_sync, docs_stats, pr_logic_size, role_sources, structure_ref |

새 test_schema_compatibility.py는 tests/state, test_public_contracts.py는 tests/platform으로 이동한다.

**완료:** 기존 테스트 39개 파일 모두 위치가 정해지고 수집/동작 유지. **commit:** not_created.

## Phase 5 — 문서와 원본 위치 정리

**수정:** README.md, ARCHITECTURE.md, mcp-server/README.md, standards/reference/,
AGENTS.md/CLAUDE.md(링크 변경 시), scripts/sync_claude_settings.py의 소비 문서 경로(해당 시).

- [ ] README의 고급 검증·관측·복구 설명을 기존 evidence-gates/run-events/run-recovery/
  observability-otel 문서와 대조해 중복을 줄인다. 설치·작은 작업·큰 작업·self-root 사용 예시는 유지한다.
- [ ] reference/history로 옮길 문서를 아래 3개로 제한한다.
  `evolution-closeout.md`, `p2-execution-evidence.md`, `p5-evaluation-evidence.md`.
  각 문서를 읽어 현재 규범 부분은 기존 운영 문서로 먼저 옮긴다.
- [ ] lifecycle/standards.py의 read/list_available가 중첩 경로를 지원하는지 확인한다.
  지원하지 않으면 traversal 차단과 함께 recursive list/read 테스트를 추가하고 최소 수정한다.
  과거 문서 경로는 기존 소비자가 있을 때 명시적 3개 alias로 호환하며 무제한 경로 허용은 하지 않는다.
- [ ] 문서 링크·역할 prompt_sources 참조를 전환하고 새 구조를 ARCHITECTURE.md에 반영한다.
  untracked ARCHITECTURE.md의 기존 내용을 덮어쓰지 않는다.
- [ ] standards/agents 원본을 수정했다면 동기화 스크립트로 adapter를 생성하고 본문 일치를 검증한다.
  CLI별 설치 경로와 로컬 산출물의 위치는 유지한다.
- [ ] tests/platform/test_structure_ref.py와 test_role_sources.py, execution/test_role_prompts.py 실행.

**PR:** 문서 정리와 standards 도구 동작 변경은 분리. **commit:** not_created.

## Phase 6 — 통합 검증과 인계

- [ ] 아래 명령을 실행하고 실제 출력과 commit을 DECISIONS.md에 기록한다.

```bash
uv --directory mcp-server run --locked --dev python -m pytest ../tests --collect-only -q
uv --directory mcp-server run --locked --dev python -m pytest ../tests -q
python3 scripts/sync_claude_settings.py --agents-only --check
uv --directory mcp-server run --locked --dev agent-platform-agent --help
git diff --check
graphify update .
```

- [ ] graphify 갱신은 코드 변경 완료 후 실행한다. docs/PROMPT/보호 파일은 입력에서 제외하고
  실패하면 원인과 직접 import/AST 검증의 대체 결과를 기록한다. 계획만 작성한 지금은 갱신하지 않는다.
- [ ] 변경량 검사는 커밋된 각 구현 PR의 base/head로 scripts/pr_logic_size.py를 실행한다.
  단일 이동은 0이어도 수정 로직이 500라인을 넘는 배치는 더 분할한다.
- [ ] 이동 전후 MCP schema/argparse 결과 비교, 새 프로세스 import, pyc 추적 0을 확인한다.
- [ ] verifier 승인 만료/allowlist/symlink/마스킹/외부 액션 확인 경계에 대한 SECURITY-AUDIT.md 작성·검토.
  DB 통합 테스트는 실제 임시 SQLite, 외부 AI/HTTP는 테스트 대역 사용 사실을 구분해 보고한다.
- [ ] 기존 사용자 diff와 새 변경을 구분하고 .active-project/실제 .local DB가 변경되지 않았는지 확인한다.
- [ ] 문서 상태를 자동 approved로 올리지 않는다. push/PR/배포는 별도 사용자 요청 범위에서만 수행한다.

**완료:** PRD AC-1~8의 증거, 보안 검토, 잔여 위험 기록. **commit:** not_created.

## 실패·복구 전략

- 각 단계는 테스트가 통과하는 상태에서 끝낸다. 실패 시 다음 패키지로 넘어가지 않는다.
- import 실패: 해당 이동과 소비자 전환만 수정/되돌린다. 전체 git reset/clean 금지.
- DB 호환 실패: 임시 fixture로 재현한다. 실제 .local/state.db를 수정해 맞추지 않는다.
- 승인 fingerprint 변화: 예상 동작이며 과거 승인을 복원하지 않는다. 실제 승인자는 구현 검토 후 재승인한다.
- 스킬 설치본 차이: source/managed/unmanaged를 다시 분류하고 자동 덮어쓰기를 중단한다.
- 공개 계약 차이: 내부 재배치 PR에서 계약 변경을 분리하고 보존하도록 수정한다.

## 계획 작성 시 검증 기록

- 런타임 tests: not_run — 사용자 요청은 계획 작성이며 구현 변경 없음.
- 기준선 테스트/공개 계약 snapshot: Phase 0에서 수행.
- 문서 이동표: 작성 시 실제 tools 34개와 tests 39개 파일의 집합 일치 확인.
- FLOW.drawio: `python3 .agents/skills/drawio-skill/scripts/validate.py --strict docs/refactor/project-structure/FLOW.drawio` → 0 error(s), 0 warning(s).
- Markdown 3개 front-matter(status: draft), 내부 문서 링크, tools 34개 이동표를 정적 검증했다.
- 구현 파일/기존 사용자 diff 변경 없음. 새 문서는 프로젝트 정책에 따라 ignored docs 아래 보관된다. 커밋하지 않았다.

## Skill Usage

스킬 선택·사용 근거는 [PRD.md](PRD.md)의 Skill Usage를 따른다.
이 문서는 실행 계획이며 테스트 명령을 적었다는 이유로 passed로 간주하지 않는다.
