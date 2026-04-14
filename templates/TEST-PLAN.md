---
agent: qa
feature: <feature-name>
status: draft
created: YYYY-MM-DD
updated: YYYY-MM-DD
links:
  prd: docs/features/<feature-name>/PRD.md
  api: docs/features/<feature-name>/API-SPEC.md
---

# TEST-PLAN: <기능명>

> PRD의 Acceptance Criteria(AC)와 API-SPEC의 에러 케이스를 기반으로 테스트 시나리오 설계.
> `standards/test-policy.md` 준수.

## 1. 테스트 범위
### In-Scope
- (예) `/v1/users/me/withdrawal` POST/GET
- (예) 도메인 규칙 BR-1 ~ BR-4
- (예) `UserWithdrawn` 이벤트 발행
- (예) `HardDeleteUserBatch`

### Out-of-Scope
- 외부 서비스(Auth, Notification) 내부 로직
- 인프라 레벨 장애 시뮬레이션 (별도 카오스 테스트)

## 2. 테스트 레벨별 매트릭스
| AC ID | Unit | Integration | E2E | Load |
|---|:-:|:-:|:-:|:-:|
| AC-1 (정상 탈퇴) | ✓ | ✓ | ✓ | - |
| AC-2 (진행 중 주문 거부) | ✓ | ✓ | - | - |
| AC-3 (멱등성) | - | ✓ | - | - |
| AC-4 (이벤트 발행) | - | ✓ | - | - |
| AC-5 (마스킹) | ✓ | - | - | - |
| AC-6 (성능) | - | - | - | ✓ |

## 3. 시나리오 상세
### TC-1: 정상 탈퇴 플로우 (AC-1)
- **Given**: ACTIVE 상태 유저, 진행 중 주문 없음
- **When**: `POST /v1/users/me/withdrawal` 유효한 body
- **Then**:
  - HTTP 200
  - DB: `status=WITHDRAWN`, `withdrawnAt` 설정됨
  - DB: `WithdrawalLog` 1건 생성
  - Event: `UserWithdrawn` 발행됨
  - PII 필드 마스킹 확인
- **Level**: Integration

### TC-2: 진행 중 주문 존재 (AC-2)
- **Given**: ACTIVE 유저, Order Service가 `hasActiveOrders=true` 반환
- **When**: 탈퇴 요청
- **Then**:
  - HTTP 409, code=`ACTIVE_ORDER_EXISTS`
  - DB 변경 없음
  - Event 발행 없음
- **Level**: Integration

### TC-3: 멱등성 보장 (AC-3)
- **Given**: 동일 `Idempotency-Key`로 2회 요청
- **When**: 두 번째 요청
- **Then**: 첫 응답과 동일 결과, DB 중복 기록 없음
- **Level**: Integration

### TC-4: 외부 서비스 장애 (에러)
- **Given**: Order Service timeout
- **When**: 탈퇴 요청
- **Then**:
  - Circuit breaker 동작 확인
  - HTTP 503, code=`ORDER_SERVICE_UNAVAILABLE`
  - Retry 메트릭 증가
- **Level**: Integration (MockWebServer timeout 주입)

### TC-5: 동시 요청 (동시성)
- **Given**: 동일 유저로 동시 10개 요청
- **When**: 병렬 실행
- **Then**:
  - 1개만 성공, 나머지 `ALREADY_WITHDRAWN` 또는 기존 결과 반환
  - DB 상태 정합성 유지
- **Level**: Integration (coroutine parallel)

### TC-6: 배치 hard delete (AC-1 연장)
- **Given**: `scheduledDeleteAt <= now()` 인 WITHDRAWN 유저 존재
- **When**: `HardDeleteUserBatch` 실행
- **Then**: 해당 유저 + PII 완전 삭제, audit log는 보존
- **Level**: Integration

## 4. 비기능 테스트
### 부하 테스트 (AC-6)
- **도구**: k6 또는 Gatling
- **시나리오**: 100 TPS, 5분 지속
- **합격 기준**: P95 < 500ms, 오류율 < 0.1%

### 보안 테스트
- [ ] 타 유저 ID로 접근 시 403/404 (IDOR 방지)
- [ ] SQL Injection 시도 입력값 안전 처리
- [ ] 민감정보 로그 미출력 (grep 검증)

## 5. 회귀 테스트 대상
- 기존 로그인 플로우
- 기존 주문 조회 (탈퇴 유저 처리)
- 기존 회원가입 (재가입 제한 BR-3)

## 6. 테스트 데이터
- Testcontainers PostgreSQL 사용
- Seed 데이터: `src/test/resources/fixtures/users.sql`
- 외부 API mock: MockWebServer + 응답 스텁

## 7. 실행 방법
```bash
# 전체
./gradlew test

# 본 기능만
./gradlew test --tests "com.company.user.withdrawal.*"

# 부하 테스트
k6 run tests/load/withdrawal.js
```

## 8. 결함 발견 시 대응
- 결함은 `BUG-REPORT.md` 템플릿으로 기록
- 심각도(P0~P3)별 핸들링:
  - P0: 배포 중단, 즉시 수정
  - P1: 배포 전 수정
  - P2: 다음 스프린트
  - P3: 백로그

## Quality Gate (QA → CICD Handoff 전 체크리스트)
- [ ] 모든 AC에 대응 TC 존재
- [ ] 모든 에러 케이스 TC 존재
- [ ] 커버리지 기준 충족 (`standards/test-policy.md`)
- [ ] 회귀 테스트 전부 통과
- [ ] P0/P1 결함 없음
- [ ] 부하 테스트 기준 충족
- [ ] status: `draft` → `approved`
