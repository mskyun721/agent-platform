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

> PRD를 구현 가능한 작업 단위로 분해한 문서. Orchestrator가 Phase 단위로 Backend를 호출하고 각 Phase 완료 후 reviewer를 실행한다.

## Phase 구성 원칙
- 각 Phase는 **독립적으로 테스트 가능한 아키텍처 단위**
- Phase 완료 시 commit 필수 — `commit:` 필드에 해시 기록 전까지 완료 처리 불가
- 순서: Domain → Application → Adapters → Quality

---

## Phase 1: Domain `[model: sonnet]`
> 순수 도메인 모델. 인프라 의존 없이 검증 가능한 범위.

- [ ] T1-1. Flyway 마이그레이션 작성 (`V<ver>__<name>.sql`)
- [ ] T1-2. 도메인 모델 추가/수정 (`domain/`) — Entity, Value Object, Domain Event
- [ ] T1-3. 도메인 예외 sealed class 정의
- [ ] T1-4. 도메인 단위 테스트 (상태 전이, 비즈니스 규칙)
- **완료 기준**: `./gradlew test --tests "*.domain.*"` 통과 (인프라 없이)
- **commit**: _(Phase 완료 후 커밋 해시 기록)_
- **review**: reviewer agent HIGH 0건 확인 후 Phase 2 진행

---

## Phase 2: Application `[model: sonnet]`
> 비즈니스 로직. Port 인터페이스와 UseCase 구현.

- [ ] T2-1. UseCase 인터페이스 정의 (`application/port/in/`)
- [ ] T2-2. Repository Port 정의 (`application/port/out/`)
- [ ] T2-3. UseCase 구현 (`application/service/`)
- [ ] T2-4. UseCase 단위 테스트 (MockK/Mockito로 Port mock)
- **완료 기준**: 모든 비즈니스 규칙 테스트 통과 (mock 기반)
- **commit**: _(Phase 완료 후 커밋 해시 기록)_
- **review**: reviewer agent HIGH 0건 확인 후 Phase 3 진행

---

## Phase 3: Adapters & Integration `[model: opus]`
> 인프라 바인딩. Inbound/Outbound adapter 구현 및 end-to-end 통합 테스트.

- [ ] T3-1. Controller/coRouter 작성 (`adapter/in/web/`)
- [ ] T3-2. Request/Response DTO 정의 + Bean Validation
- [ ] T3-3. Exception Handler 매핑 (`@RestControllerAdvice`)
- [ ] T3-4. WebTestClient 통합 테스트
- [ ] T3-5. Repository 구현 (`adapter/out/persistence/`)
- [ ] T3-6. 외부 API 클라이언트 (`adapter/out/client/`) _(해당 시)_
- [ ] T3-7. Circuit breaker / Retry 설정 _(해당 시)_
- [ ] T3-8. Domain Event 발행 + Listener 구현 _(해당 시)_
- [ ] T3-9. Testcontainers 기반 통합 테스트 (end-to-end)
- **완료 기준**: 외부 의존성 포함 전체 플로우 end-to-end 통과
- **commit**: _(Phase 완료 후 커밋 해시 기록)_
- **review**: reviewer agent HIGH 0건 확인 후 Phase 4 진행

---

## Phase 4: Quality & Documentation `[model: haiku]`
> 관측성, 문서화, 배포 준비.

- [ ] T4-1. 로그 추가 (INFO/WARN/ERROR 기준 준수)
- [ ] T4-2. 메트릭 등록 (Micrometer)
- [ ] T4-3. 분산 추적 span 확인
- [ ] T4-4. `API-SPEC.md` 최종화 (구현과 일치)
- [ ] T4-5. `DECISIONS.md` 작성 (아키텍처 결정 기록)
- [ ] T4-6. OpenAPI 문서 업데이트 _(해당 시)_
- **완료 기준**: API-SPEC이 실제 구현과 일치하고 `approved` 승격 가능
- **commit**: _(Phase 완료 후 커밋 해시 기록)_
- **review**: reviewer agent HIGH 0건 확인 → Security handoff

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
