# Role Skill Policy

역할 시작 시 아래 매핑으로 메인(작업 절차)과 보조(특정 작업 도구)를 선택한다.
설치는 실제 사용이 아니며, 메인은 무조건 모든 단계를 실행하라는 뜻이 아니다.
사용자 요청 범위, 승인된 계약, 플랫폼 정책과 실행 환경 권한이 스킬보다 우선한다.

## 역할 매핑

| 역할 | 메인 | 보조와 적용 조건 |
|---|---|---|
| orchestrator | 공통 역할 라우팅 (내장 지침) | 인계 완료 확인에 verification-before-completion |
| planner | 요구사항이 불명확하면 brainstorming, 계획 작성에는 writing-plans | 흐름도 작성은 drawio-skill; 기존 코드 분석은 graphify |
| backend | 기능 구현은 test-driven-development, 버그/실패 재현은 systematic-debugging | 승인 계획 실행은 executing-plans; 영향 분석은 graphify; 흐름 수정은 drawio-skill; 리뷰 대응은 receiving-code-review; 완료 전 verification-before-completion |
| reviewer | standards/agents/reviewer.md의 직접 코드 리뷰 절차 | graphify 영향 분석, verification-before-completion으로 증거 확인; 리뷰 피드백 검토 시 receiving-code-review |
| security | standards/security-baseline.md의 보안 감사 (전용 스킬 미설치) | graphify 신뢰 경계 탐색; verification-before-completion으로 검증 증거 확인 |
| qa | verification-before-completion | 실패 분석은 systematic-debugging; graphify 회귀 범위; standards/api-contract.md와 standards/test-policy.md로 실제 통합 검증 |
| cicd | verification-before-completion | 릴리스 준비에 finishing-a-development-branch의 점검 절차만 사용 |

Superpowers 이름은 설치된 6.3.0에서 확인한 실제 디렉터리 이름이다. 호출 namespace는
현재 backend가 공개한 이름을 사용한다(예: superpowers:brainstorming).
requesting-code-review는 리뷰어 자체의 스킬이 아니라 별도 리뷰 요청 절차이므로
reviewer의 메인으로 쓰지 않는다. 보안/API 전용 스킬이 설치됐다고 보고하지 않는다.

## 선택과 실행

1. 역할과 작업 유형을 확정하고 매핑의 조건에 해당하는 스킬만 선택한다. 단순 질문,
   문서 수정, 승인된 계획의 일부 실행에 전체 brainstorming/TDD 흐름을 강제하지 않는다.
2. 현재 세션의 사용 가능 스킬 목록과 대상 프로젝트의 설치 경로를 확인한다.
   플랫폼 관리 스킬은 skill list --project-id 결과를 참고하되 외부 플러그인까지
   포괄한다고 간주하지 않는다. 캐시 존재만으로 활성/호출 가능을 확정하지 않는다.
3. 네이티브 스킬 호출 기능이 있으면 그것을 사용한다. 없으면 접근 가능한 해당
   SKILL.md를 직접 읽고 필요한 절차를 수행하되 manual 모드로 기록한다.
   특정 사용자 홈·캐시 버전을 실행 경로로 하드코딩하지 않는다.
4. 스킬을 사용할 때마다 목적을 짧게 알린다. 설명만 읽거나 설치만 확인하고 used로
   기록하지 않는다. 실행 시 해당 SKILL.md와 필요한 참조만 읽어 컨텍스트를 제한한다.
5. 사용할 수 없으면 unavailable과 이유를 남기고 역할 내장 절차로 fallback한다.
   사용자 지정 필수 스킬이거나 대체 불가능한 산출물 검증 도구라면 blocked로 알리고
   설치/활성화 승인을 요청한다. 대체 실행을 원래 스킬의 성공으로 보고하지 않는다.
6. 작업 완료 시 아래 기록을 기존 역할 산출물(또는 stdout 산출물)에 남긴다.
   플랫폼 스킬을 전부 끈 경우에도 공통 정책과 필수 테스트는 유지한다.

## 도구별 조건

- ponytail: backend 구현·리팩토링의 보조 스킬이다. 기본 lite로 사용하며 기존
  코드/표준 라이브러리 재사용, 불필요한 추상화 억제에 적용한다. 승인된 요구사항,
  필수 단위/통합 테스트, 보안·예외 처리·API 계약·실행 증거는 줄이지 않는다.
  스킬의 한 개 self-check 권장이나 출력 길이 제한이 플랫폼 테스트/산출물 계약을
  대체하지 않는다. 무조건 삭제하거나 한 줄로 압축하지 않으며 역할 밖으로 활성
  상태를 지속시키지 않는다. 실제 단순화 결정과 검증 결과를 Skill Usage에 기록한다.

- drawio-skill: 흐름 생성·수정 시 메인 산출물 도구로 사용한다. Claude/Codex의
  프로젝트 스킬 또는 플랫폼 관리 패키지를 확인한다. 실제 validate 결과를 남긴다.
- graphify: 기존 코드 탐색 시 CLI와 graphify-out/graph.json을 모두 확인한다.
  스킬 미노출이어도 CLI 직접 사용은 가능하며 manual로 기록한다. 그래프가 없거나
  오래됐으면 rg/직접 코드 확인으로 대체하고 결과를 사실로 재확인한다.
  그래프 생성·갱신은 대상 경로 쓰기 권한과 요청 범위를 확인한 후 실행한다.
- Superpowers: brainstorming과 writing-plans는 기존 PRD/TASK/WORK/API-SPEC/FLOW
  계약을 사용한다. 별도의 docs/superpowers 산출물 체계를 만들지 않는다.
  executing-plans는 승인된 범위만 실행하며 기능별 순수 로직 500라인 제한을 지킨다.
  worktree 생성, dispatching-parallel-agents, subagent-driven-development,
  requesting-code-review의 위임은 별도 사용자 지시 없이 자동 실행하지 않는다.
  finishing-a-development-branch가 제안해도 push/PR/merge/deploy/브랜치 삭제는
  승인 범위를 넘어 수행하지 않는다. wrapper 안에서는 재위임하지 않는다.
- 보조 스킬 실패로 필수 검증을 생략하지 않는다. Apidog은 선택 실행 도구이며
  단위/실제 DB 통합 테스트를 대체하지 않는다.

## 사용 기록

기존 역할 산출물에 `## Skill Usage` 표를 추가한다. planning-only/dry-run에서는
selected만 기록하고 실행 증거가 없는 used/succeeded를 만들지 않는다.

| skill | tier | mode | version | status | reason / evidence |
|---|---|---|---|---|---|
| <실제 이름> | main / auxiliary | native / manual / fallback | <확인값 또는 unknown> | selected / used / skipped / unavailable / failed | <선택·미사용 이유 또는 수행 단계·명령·결과> |

메인 후보와 작업에 해당하는 보조 후보를 기록한다. 해당 없는 모든 스킬 목록을
나열하지 않는다. used는 절차를 실제 수행했다는 뜻이며 테스트 성공이나 사람 승인이
아니다. 시크릿·원문 프롬프트·코드를 기록하지 않는다. 이 표는 에이전트의 실행 보고이며
자동 수집 telemetry가 아니다. active_versions의 expected 해시도 observed usage로
승격하지 않는다. 관측 DB에는 별도 수집기가 없는 한 실제 스킬 호출 기록을 주장하지 않는다.


## ECC 추가 스킬 (프로젝트 관리 패키지)

6개 패키지는 ECC `e482e579415fde18357cafce70f177ae19fd7f03`을 참고한
`ecc-e482e57-platform.1` 수정본이다. 원본 source/hash와 MIT 고지는 각 패키지의
skill.json/LICENSE에 보존한다. 원본 runtime 스크립트를 설치한 것은 아니다.

| 스킬 | 역할 / 사용 조건 | 현재 제공 범위 |
|---|---|---|
| search-first | planner/backend: 새 의존성·통합·공통 도구 도입 전 | repo/공식 문서/패키지/MCP 대안 비교; 단순 수정마다 강제하지 않음 |
| skill-stocktake | orchestrator/reviewer: 요청된 스킬 정리·품질 점검 | 중복·노후·충돌 점검 및 유지/수정/병합 제안; 자동 삭제 없음 |
| security-scan | security: agent 설정·hook·MCP 신뢰 경계 검토 | 수동 정적 검사 가능; AgentShield 선택 사용, 자동 설치 없음 |
| continuous-learning-v2 | orchestrator/reviewer: 명시적 학습·회고 요청 | 선택한 피드백으로 draft 후보 작성·근거·검증 계획; background observer 없음 |
| eval-harness | qa/planner: 지침·스킬 변경 전후 효과 평가 | 기존 evals runner와 연결한 grader/회귀 설계; 실제 AI 실행은 요청 범위 내 수행 |
| iterative-retrieval | 모든 역할: 맥락 부족·과도한 검색 결과 | graphify 우선, 최대 3회 기본 탐색/검토/질의 보완; 자동 위임 없음 |

기존 메인 스킬을 교체하지 않는 조건부 보조 스킬이다. 공통 정책·산출물 경로·승인
범위는 그대로 적용한다. 미구현 feedback/improvement CLI를 사용 가능하다고 보고하지
않는다. 학습 후보는 현재 작업 문서에 기록하며 검토 전 규칙으로 적용하지 않는다.
스킬 설치/활성화 해시는 로딩·사용·성공 증거와 다르다. 현재 세션에서 노출되지 않으면
다음 턴/새 세션에서 확인하거나 해당 SKILL.md를 읽은 manual 모드로 명시한다.
