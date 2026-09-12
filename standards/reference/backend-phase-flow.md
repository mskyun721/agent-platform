# Backend Phase Flow

## Feature Slices

기능별로 구현·테스트·검토 가능한 PR을 먼저 나눈다. 순수 로직 추가+삭제 500라인 이하이며
주석/import/테스트/설정은 산정에서 제외하되 관련 테스트·설정은 같은 기능 PR에 포함한다.
아래 단계는 한 기능 내부의 작업 순서다. 레이어별 PR, 별도 Agent 호출, 단계별 모델을 강제하지 않는다.

| Phase | Scope | Review trigger |
|---|---|---|
| Plan | Service flow, API contract, acceptance cases | plan review before implementation |
| Domain / Application | Applicable domain rules and use cases, unit tests | review the complete feature slice |
| Adapters / Integration | Actual persistence and API tests, negative cases | evidence required for the slice |
| Documentation | WORK or API-SPEC/DECISIONS, verification results | completion review; security based on risk |

## Models

현재 세션에서 직접 수행하는 것이 기본이다. 모델과 호출 방식은 CLI adapter 설정에 두며
공통 역할 원본 `standards/agents/backend.md`에서 특정 모델이나 도구를 강제하지 않는다.
