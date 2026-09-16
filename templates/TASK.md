---
agent: planner
feature: <feature-name>
status: draft
created: YYYY-MM-DD
updated: YYYY-MM-DD
links:
  prd: docs/features/<feature-name>/PRD.md
---

# TASK: <기능명>

> PRD를 구현 가능한 작업 단위로 분해한 문서.

## Phase 구성 원칙
- 적용 범위: 2026-09-16 이후 새로 작성하는 계획. 기존 TASK의 Phase와 순서는 소급 변경하지 않는다.
- Phase 1: 공통 작업·기반 설정·공통 계약. 필요한 선행 작업만 수행한다.
- Phase 2: 도메인 모델·업무 규칙·단위 테스트. endpoint별 서비스 구현을 모두 선행하지 않는다.
- Phase 3 이후: **HTTP Method + Path별 기능 단위**. 각 endpoint의 repository → service → router 및 정상·실패·경계 테스트를 한 세트로 완료한다.
- repository 전체 → service 전체 → router 전체처럼 레이어별 Phase를 만들지 않는다. 기존 공통 코드는 재사용하며 불필요한 레이어를 새로 만들지 않는다.
- endpoint 간 의존성에 따라 순서를 정하고 마지막에 연결된 업무 흐름의 통합 검증을 수행한다.
- PR은 endpoint 기능 단위를 기본으로 순수 로직 추가+삭제 500라인 이하로 나눈다. 초과 시 독립 검증 가능한 하위 기능으로 분할하고 관련 테스트·설정은 함께 포함한다.
- Phase 완료 시 commit 필수 — `commit:` 필드에 해시 기록 전까지 완료 처리 불가

## Phase N: <METHOD /path - 기능명>
- 선행 Phase: <공통·도메인 및 의존 endpoint>
- 관련 AC / operationId: <계약 참조>
- PR: <기능 범위 및 로직 변경량>
- [ ] repository: 저장·조회 및 실제 DB 통합 테스트 (해당 없음이면 사유)
- [ ] service: 업무 흐름 및 정상·실패·경계 단위 테스트
- [ ] router: 요청·응답·인증·권한 연결 및 실제 HTTP 테스트
- [ ] API-SPEC/OpenAPI/FLOW 정합성 확인 및 실행 결과 기록
- commit: <완료 커밋 해시>

---

## 의존성 & 블로커
| ID | 블로커 | 해결 상태 |
|---|---|---|
| - | 외부 API 스펙 확정 대기 | [ ] 해결 |

## Quality Gate (전체 완료 기준)
- [ ] 전 Phase 체크박스 완료
- [ ] 전 Phase `commit:` 해시 기록 완료
- [ ] 모든 AC(PRD의 Acceptance Criteria) 통과
- [ ] 커버리지 기준 충족 (`standards/test-policy.md`)
- [ ] API-SPEC, DECISIONS `status: approved`
