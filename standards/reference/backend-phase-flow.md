# Backend Phase Flow

## Feature Slices

기능별로 구현·테스트·검토 가능한 PR을 먼저 나눈다. 순수 로직 추가+삭제 500라인 이하이며
주석/import/테스트/설정은 산정에서 제외하되 관련 테스트·설정은 같은 기능 PR에 포함한다.
아래 순서는 2026-09-16 이후 새로 작성하는 계획에 적용한다. 기존 TASK와 승인된
Phase 1·2를 포함한 실행 순서는 소급 변경하지 않는다. 별도 Agent 호출·단계별 모델은 강제하지 않는다.

| Phase | Scope | Review trigger |
|---|---|---|
| 기획 (개발 전) | 서비스 흐름·API 계약·AC·endpoint 의존성 | 구현 전 기획 검토 |
| Phase 1 | 공통 작업·기반 설정·공통 계약 | 필요한 선행 작업 검증 |
| Phase 2 | 도메인 모델·업무 규칙·단위 테스트 | 도메인 검증 |
| Phase 3 이후 | endpoint별 repository → service → router + 단위·DB·HTTP 테스트 | endpoint 기능 세트 검토 |
| 최종 검증 | endpoint 간 업무 흐름·문서·실행 증거 | 완료 리뷰·위험별 보안·QA |

endpoint 단위는 HTTP Method + Path다. Phase 3 이후 레이어 전체를 순서대로 구현하지
않고 endpoint 한 개의 기능 세트를 완료한 후 다음으로 진행한다. endpoint별 service를
Phase 2에서 모두 만들지 않는다. 공통 repository/service는 재사용하고 대상 구조에 없는
레이어를 억지로 추가하지 않는다. API 없는 작업은 독립 검증 가능한 기능 단위로 나눈다.
PR 로직이 500라인을 넘으면 독립 검증 가능한 하위 기능으로 분할하고 의존성을 기록한다.

## Models

현재 세션에서 직접 수행하는 것이 기본이다. 모델과 호출 방식은 CLI adapter 설정에 두며
공통 역할 원본 `standards/agents/backend.md`에서 특정 모델이나 도구를 강제하지 않는다.
