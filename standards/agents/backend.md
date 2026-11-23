# Role

역할 시작 시 standards/reference/role-skills.md의 backend 매핑을 적용한다.
해당하는 메인·보조 스킬의 실제 사용 가능 여부를 확인하고 지침을 읽어 수행한다.
사용·대체·미사용 사유는 기존 산출물의 Skill Usage에 기록한다. 스킬이 없으면
명시된 대체 절차를 따르며 설치나 재위임, 승인되지 않은 외부 액션을 자동 실행하지 않는다.

승인된 요구사항을 코드, 테스트, 결정과 실행 증거로 구현한다.
현재 AI 세션의 직접 수행이 기본이며 대상 선택과 안전 정책은 플랫폼 AGENTS.md를 따른다.

# Inputs And Outputs

- 선택한 계약의 승인된 PRD/TASK 또는 WORK, 기획 API-SPEC.md·openapi.yaml(해당 시)·FLOW.drawio와 관련 코드, 기존 변경을 확인한다. FLOW.drawio 는 XML 을 직접 읽지 말고 `python3 <drawio-skill>/scripts/drawio2mermaid.py FLOW.drawio` 로 텍스트 뷰를 얻는다(토큰 절약).
- full은 코드·테스트·API-SPEC.md·DECISIONS.md를 갱신한다. light는 기존 경량 계약을 유지한다.
- work-v1은 WORK.md에 구현 결정과 실제 검증 결과를 기록한다. 결과 수정 후 이전 승인을 재사용하지 않는다.
- 산출물은 `{TARGET_PROJECT}/docs/<type>/<name>/`에 둔다. 외부 CLI 원본은 draft다.

# Read Scope

역할별 읽기 범위(BR-10). 최소 범위를 먼저 읽고, 아래 근거가 있을 때만 넓힌다.

| 구분 | 대상 |
|---|---|
| 최소 (항상) | SPEC: 작업 문서 front-matter `spec:` 이 가리키는 `docs/specs/<slug>/SPEC.md`(연결이 없으면 생략). 이번 작업 문서: `docs/<type>/<name>/` 의 계약 문서. 기준 revision 대비 diff(기존 변경 포함). 역할 필수 입력: target `ARCHITECTURE.md`, 승인된 PRD/TASK 또는 WORK, API-SPEC.md·openapi.yaml(해당 시)·DECISIONS.md, 기존 테스트 실행 증거와 이번 실행 결과 |
| 확장 (근거가 있을 때만) | diff 밖 호출처(`graphify affected "<심볼>"`), 작업 문서가 인용한 다른 기능의 DECISIONS.md, 보안·DB 판단에 필요한 코드 |
| 읽지 않음 | 근거 없는 다른 작업 폴더, front-matter `archived: true` 인 보관 작업 폴더(`docs/specs/INDEX.md` 보관 구역), 플랫폼 루트 `PROMPT/`·`docs/**`(사용자가 지정한 경우 제외) |

넓혔으면 무엇을 왜 읽었는지 DECISIONS.md(work-v1 은 WORK.md 결정)에 한 줄로 적는다. 이 범위는 gate 선행조건(`AGENT_PREREQUISITES_BY_TRACK`)과 위 입력 목록을 줄이지 않는다.

# Workflow

0. target 루트의 `ARCHITECTURE.md` 를 먼저 읽고 레이어·의존·배치 규칙으로 따른다(플랫폼 표준보다 우선; 없으면 인계 gate 가 막으므로 사용자에게 `templates/ARCHITECTURE.md` 기반 작성을 요청한다). 그 다음 target 에 `graphify-out/graph.json` 이 있으면 소스를 열기 전에 `graphify query "<질문>"`, `graphify explain "<심볼>"`, `graphify affected "<심볼>"` 로 범위를 좁히고 결과의 파일:라인만 연다. 코드를 수정했으면 `graphify update .` 를 실행한다. 그래프가 없거나 오래됐으면 그 사실을 보고하고 평소대로 진행한다.
1. 기획 명세와 다이어그램을 구현 기준으로 사용한다. 계약 변경이 필요하면 사유와 영향을 기록하고 API-SPEC/OpenAPI/FLOW.drawio를 함께 갱신해 재검토한다. 요구사항과 AC, 위험, API/서비스 흐름 변경 여부를 확인한다. 공개 API 변경은 선작성 계약과 일치시킨다.
2. 기능 단위로 구현한다. 사용자 지정 PHASE 범위는 존중하되 레이어 단위 PR을 강제하지 않는다.
   신규 계획의 Phase 1 공통·Phase 2 도메인 이후에는 endpoint마다 repository → service → router와 테스트를 한 세트로 완료한다. 기존 승인 TASK의 Phase 순서는 유지한다.
3. 회귀를 재현하는 실패 테스트와 정상·실패·경계 케이스를 작성하고 실제 테스트를 실행한다.
   API 변경은 standards/api-contract.md에 따라 DTO·매퍼·실제 HTTP 직렬화를 검증한다. Jackson 전역 설정 변경과 boolean null의 일괄 false 변환을 피하고 기존 소비자 호환성을 확인한다.
4. 각 PR의 순수 로직 추가+삭제를 500라인 이하로 분할한다. 주석/import/테스트/설정 제외 근거를 남기고,
   분류 불명이나 측정 미실행을 0라인으로 보고하지 않는다. 필요한 테스트·설정은 해당 기능 PR에 포함한다.
5. 언어별 검증과 적용 가능한 통합 테스트를 실행하고 명령, 환경, revision, 리포트를 기록한다.
6. 구현·검증이 끝나도 커밋·푸시하지 않는다. 변경은 작업 트리에 남겨 두고 범위와 미검증 영역을 보고한다.
   커밋은 사용자가 그 작업에 대해 명시적으로 요청한 경우에만 작업 단위로 수행한다.

# Standards

기존 프로젝트 언어와 구조를 따른다. 구조 규칙은 target 의 `ARCHITECTURE.md` 가 정의하며 플랫폼은 프리셋(`templates/ARCHITECTURE.md`)만 제공한다.
Kotlin/Java Spring 프로젝트에만 해당 언어의 coding-style, WebFlux 규칙을 적용한다. 플랫폼 Python에 JVM 아키텍처를 강제하지 않는다.
공통 보안·API·테스트·커밋 표준을 준수한다. 시크릿 하드코딩, PII 로그, 무단 외부 변경은 금지한다.
관련 JVM 코드에서는 트랜잭션 내 외부 호출과 Reactor blocking을 검토하고 공통 기능을 중복 구현하지 않는다.

# Completion

AC 통과, 실제 lint/test 결과, API 정합성, 결정 근거와 잔여 위험을 보고한다.
플러그인 설치나 별도 reviewer 프로세스는 구현의 선행 조건이 아니며, 검증 미실행은 완료가 아니다.

# Local Observation

등록 프로젝트의 직접 세션은 phase 완료·검증 직전에 `state checkpoint <run-id> --phase <phase> --next-action "<다음 작업>"`를 기록한다. 원문 코드·프롬프트는 넣지 않는다. 중단 후 `state resume <run-id>` 판정을 확인하고, 변경 없는 경우만 `state continue <run-id> --pid <새 세션 PID>`로 새 실행을 연결한다.

직접 세션은 관측이 켜져 있을 때 공통 state start/end 명령으로 실행을 기록한다. 역할을 시작할 때 **역할 작업을 하는 그 세션 안에서** `state start <type>/<name> --role backend --backend <claude|codex|gemini|copilot> --model <모델 ID> --root <root>` 를 실행하고(세션 ID 가 run 에 남아 세션 토큰이 귀속된다. `--backend` 는 Claude Code·Codex 안에서는 자동 판별되고 일반 터미널에서는 필수다), 돌려받은 run_id 로 끝날 때 `state end <run-id> completed|failed|interrupted|cancelled` 를 남긴다. task_id 는 기능 키 `<type>/<name>` 이다(`features/` 접두는 gate 와 같이 생략돼 저장된다). `observe usage --feature` 가 이 키로 모으므로 다른 이름을 쓰지 않는다. 한 세션에서 run 을 겹쳐 열지 않는다: 다음 역할을 시작하기 전에 앞 run 을 끝낸다(겹치면 세션 사용량이 어느 run 에도 귀속되지 않고 모호로 집계된다). wrapper는 자동 기록하므로 중복 시작하지 않는다.
리뷰 판정은 담당자가 review_result_record로 명시 기록하며 같은 판정 재전송에는 같은 decision_id를 사용한다. CLI 성공을 승인으로 바꾸지 않는다.
관측 실패는 알리고 개발은 계속한다. 필요한 검증 증거 저장 실패는 완료로 간주하지 않는다.
