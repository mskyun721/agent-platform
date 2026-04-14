---
agent: planner
feature: <feature-name>
status: draft
created: YYYY-MM-DD
updated: YYYY-MM-DD
links:
  task: docs/features/<feature-name>/TASK.md
  api: docs/features/<feature-name>/API-SPEC.md
---

# PRD: <기능명> (Backend Spec)

> 백엔드 서버 기능 명세서. Backend Agent가 별도 해석 없이 구현에 착수할 수 있는 수준으로 작성한다.
> UI/UX, 사용자 여정 등 프론트 관점은 본 문서에서 다루지 않는다.

## 1. 개요
- **한 줄 요약**: 이 서비스/엔드포인트가 제공하는 기능
- **문제/배경**: 왜 추가/변경하는가
- **Consumer**: 이 API/기능을 호출하는 대상 (내부 서비스, 앱, 외부 파트너 등)

## 2. 범위
### In-Scope
- 구현할 엔드포인트/배치/이벤트 핸들러 목록
- 변경될 도메인/테이블

### Out-of-Scope
- 명시적으로 제외 (예: 관리자 화면, 통계 집계 등)

## 3. API 요약
상세는 `API-SPEC.md`. 여기는 목록만.

| 메서드 | 경로 | 목적 | 권한 | 멱등성 |
|---|---|---|---|---|
| POST | `/v1/xxx` | ... | 로그인 유저 | 예 (Idempotency-Key) |
| GET | `/v1/xxx/{id}` | ... | 로그인 유저 | - |

## 4. 도메인 모델
### 엔티티 변경
```
User (변경)
├── status: UserStatus (ACTIVE | WITHDRAWN 추가)
├── withdrawnAt: Instant? (신규)
└── scheduledDeleteAt: Instant? (신규)

WithdrawalLog (신규)
├── id: UUID (PK)
├── userId: Long (FK, index)
├── reason: String?
├── requestedAt: Instant
└── processedAt: Instant?
```

### 상태 전이 (State Machine)
```
ACTIVE ──(withdrawal request)──> WITHDRAWAL_PENDING
WITHDRAWAL_PENDING ──(process)──> WITHDRAWN
WITHDRAWN ──(90 days)──> HARD_DELETED
```

### DB 마이그레이션
- Flyway: `V20260413_01__add_withdrawal_columns.sql`
- 기존 데이터: `status=ACTIVE` 백필
- Index: `idx_user_status`, `idx_user_scheduled_delete_at`

## 5. 비즈니스 규칙 (Business Rules)
| ID | 규칙 |
|---|---|
| BR-1 | 진행 중 주문(status IN ['PAID','SHIPPING']) 존재 시 탈퇴 불가 |
| BR-2 | 탈퇴 처리 시 이메일/전화/이름 마스킹 필수 |
| BR-3 | 탈퇴 후 90일간 동일 이메일 재가입 불가 |
| BR-4 | 동일 유저 중복 요청은 첫 요청 결과 반환 (멱등) |

## 6. 처리 흐름 (Flow)
### 6.1 동기 처리
```
Controller
  → UseCase(WithdrawUser)
    → OrderPort.hasActiveOrders(userId)      // 외부 확인
    → UserRepository.findById(userId)
    → User.requestWithdrawal()               // 도메인 로직
    → UserRepository.save(user)
    → WithdrawalLogRepository.save(log)
    → DomainEventPublisher.publish(UserWithdrawn)
  → 200 OK
```

### 6.2 비동기/이벤트
| 이벤트 | Producer | Consumer | 동작 |
|---|---|---|---|
| `UserWithdrawn` | 본 기능 | Auth Service | 전체 세션 무효화 |
| `UserWithdrawn` | 본 기능 | Notification | 탈퇴 완료 메일 |

### 6.3 배치/스케줄
- **Job**: `HardDeleteUserBatch`
- **주기**: 매일 03:00
- **조건**: `status=WITHDRAWN AND scheduledDeleteAt <= now()`
- **처리**: 유저 + 관련 PII hard delete

## 7. 트랜잭션 & 동시성
- **Transaction 경계**: UseCase 단위 (`@Transactional`)
- **격리 수준**: READ_COMMITTED (기본)
- **락**: 탈퇴 처리 시 User 행 비관적 락(`SELECT ... FOR UPDATE`)
- **멱등성**: `Idempotency-Key` 헤더 또는 동일 유저 WITHDRAWN 상태 재요청 시 기존 결과 반환

## 8. 외부 의존성 (Ports)
| Port | 대상 | 호출 방식 | 실패 대응 |
|---|---|---|---|
| `OrderPort` | Order Service | HTTP (WebClient) | Circuit breaker, fallback=거부 |
| `AuthPort` | Auth Service | HTTP | 이벤트로 비동기 처리 (실패해도 탈퇴는 성공) |

## 9. 에러 케이스
| Code | HTTP | 조건 | 메시지 |
|---|---|---|---|
| `ACTIVE_ORDER_EXISTS` | 409 | BR-1 위반 | "진행 중인 주문이 있어 탈퇴할 수 없습니다" |
| `INVALID_PASSWORD` | 401 | 비밀번호 불일치 | "비밀번호가 올바르지 않습니다" |
| `ALREADY_WITHDRAWN` | 409 | 이미 WITHDRAWN | "이미 탈퇴 처리된 계정입니다" |
| `ORDER_SERVICE_UNAVAILABLE` | 503 | 외부 연동 실패 | "잠시 후 다시 시도해주세요" |

## 10. 비기능 요구사항 (NFR)
| 항목 | 기준 |
|---|---|
| 성능 | P95 < 500ms, P99 < 1s |
| TPS | 피크 100 TPS 처리 |
| 가용성 | 99.9% |
| 데이터 일관성 | 탈퇴 처리 실패 시 전체 롤백 (Saga 불필요) |
| 보안 | `standards/security-baseline.md` 준수, PII 로깅 금지 |

## 11. 관측성 (Observability)
### 로그
- 레벨: INFO (성공), WARN (비즈니스 거부), ERROR (시스템 장애)
- 필수 필드: `userId(마스킹)`, `requestId`, `result`
- PII 원문 로그 절대 금지

### 메트릭 (Micrometer)
- `withdrawal.request.count` (counter, tags: result)
- `withdrawal.duration` (timer)
- `withdrawal.active_order_rejected.count`

### 추적
- 분산 추적 ID (`X-Request-Id`) 전파
- 외부 호출 span 기록

### 알람
- 실패율 > 5% (5분) → Slack
- P95 > 1s (5분) → Slack

## 12. 수락 기준 (Acceptance Criteria)
| ID | 조건 | 검증 방법 |
|---|---|---|
| AC-1 | 정상 탈퇴 요청 시 200 + 상태 WITHDRAWN | Integration Test |
| AC-2 | 진행 중 주문 존재 시 409 + 코드 `ACTIVE_ORDER_EXISTS` | Integration Test |
| AC-3 | 중복 요청 시 기존 결과 반환 (멱등) | Integration Test |
| AC-4 | `UserWithdrawn` 이벤트 발행 확인 | Integration Test |
| AC-5 | 개인정보 필드 마스킹 적용 | Unit Test |
| AC-6 | P95 응답 < 500ms (100 TPS 부하) | Load Test |

## 13. Assumption (합의 필요)
- 진행 중 주문 정의: `PAID`, `SHIPPING` 상태로 한정 (기획 확인 필요)
- hard delete 스케줄: 매일 03:00 KST
- 재가입 제한 키: 이메일 (전화번호는 별도 작업)

## 14. 참고 자료
- 관련 티켓:
- 기존 관련 코드: `com.company.user.*`
- 외부 API 문서:

## Quality Gate (Planner → Backend Handoff 전 체크리스트)
- [ ] API 엔드포인트 목록 확정 (메서드/경로/권한/멱등성)
- [ ] 도메인 모델 변경사항과 마이그레이션 명시
- [ ] 모든 Business Rule에 ID 부여
- [ ] 처리 흐름(Flow) 명시
- [ ] 외부 의존성 Port 및 실패 대응 명시
- [ ] 에러 코드 목록 작성
- [ ] NFR 정량 기준 명시
- [ ] 모든 AC에 검증 방법 명시
- [ ] Assumption 항목 유관 부서 합의 완료
- [ ] status: `draft` → `approved`
