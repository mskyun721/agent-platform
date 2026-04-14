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

> PRD를 구현 가능한 작업 단위로 분해한 문서. Backend Agent가 Phase 단위로 진행하며 체크박스를 업데이트한다.

## Phase 구성 원칙
- 각 Phase는 **빌드/테스트 가능한 단위**
- Phase 완료 시 PR 또는 commit 단위로 분리 가능
- 순서는 의존성 기준 (상향식: Domain → Application → Adapter)

## Phase 1: 도메인 & 스키마
- [ ] T1-1. Flyway 마이그레이션 작성 (`V<ver>__<name>.sql`)
- [ ] T1-2. 도메인 모델 추가/수정 (`domain/`)
- [ ] T1-3. 도메인 예외 sealed class 정의
- [ ] T1-4. 도메인 단위 테스트 (상태 전이, 비즈니스 규칙)
- **완료 기준**: `./gradlew test --tests "domain.*"` 통과

## Phase 2: Application Layer
- [ ] T2-1. UseCase 인터페이스 정의 (`application/port/in/`)
- [ ] T2-2. Repository Port 정의 (`application/port/out/`)
- [ ] T2-3. UseCase 구현 (`application/service/`)
- [ ] T2-4. UseCase 단위 테스트 (MockK로 Port mock)
- **완료 기준**: 모든 Business Rule 테스트 통과

## Phase 3: Adapter (Inbound)
- [ ] T3-1. Controller/coRouter 작성 (`adapter/in/web/`)
- [ ] T3-2. Request/Response DTO 정의 + Bean Validation
- [ ] T3-3. Exception Handler 매핑 (`@RestControllerAdvice`)
- [ ] T3-4. WebTestClient 통합 테스트
- **완료 기준**: 모든 Acceptance Criteria (AC) 통과

## Phase 4: Adapter (Outbound)
- [ ] T4-1. Repository 구현 (`adapter/out/persistence/`)
- [ ] T4-2. 외부 API 클라이언트 (`adapter/out/client/`)
- [ ] T4-3. Circuit breaker / Retry 설정
- [ ] T4-4. Testcontainers 기반 통합 테스트
- **완료 기준**: 외부 의존성 포함 플로우 end-to-end 통과

## Phase 5: 이벤트/배치
- [ ] T5-1. Domain Event 발행 지점 추가
- [ ] T5-2. Event Listener 구현 (필요 시)
- [ ] T5-3. 배치 Job 구현 (필요 시)
- [ ] T5-4. 이벤트/배치 통합 테스트

## Phase 6: 관측성
- [ ] T6-1. 로그 추가 (INFO/WARN/ERROR)
- [ ] T6-2. 메트릭 등록 (Micrometer)
- [ ] T6-3. 분산 추적 span 확인
- [ ] T6-4. 알람 룰 등록

## Phase 7: 문서화 & 마무리
- [ ] T7-1. `API-SPEC.md` 최종화
- [ ] T7-2. `DECISIONS.md` 작성 (아키텍처 결정 기록)
- [ ] T7-3. OpenAPI 문서 업데이트
- [ ] T7-4. README / 운영 가이드 업데이트

## 의존성 & 블로커
| ID | 블로커 | 해결 상태 |
|---|---|---|
| - | 외부 API 스펙 확정 대기 | [ ] 해결 |

## Phase 완료 시 절차
1. 해당 Phase 체크박스 업데이트
2. `./gradlew ktlintCheck detekt test` 통과 확인
3. Commit (타입: `feat:`, `test:` 등) + 메시지에 Phase 번호 기재
4. 다음 Phase로 진행

## Quality Gate (전체 완료 기준)
- [ ] 전 Phase 체크박스 완료
- [ ] 모든 AC(PRD의 Acceptance Criteria) 통과
- [ ] 커버리지 기준 충족 (`standards/test-policy.md`)
- [ ] status: `draft` → `approved`
