---
agent: backend
feature: <feature-name>
status: draft
created: YYYY-MM-DD
updated: YYYY-MM-DD
links:
  prd: docs/features/<feature-name>/PRD.md
---

# API-SPEC: <기능명>

> REST API 상세 명세. `standards/api-contract.md` 규약 준수.
> OpenAPI 3.1 작성은 `src/main/resources/openapi/` 참조. 본 문서는 **팀 공통 리뷰용 요약**.

## 공통
- Base URL (dev): `https://api-dev.company.com`
- 인증: `Authorization: Bearer <JWT>`
- Content-Type: `application/json; charset=UTF-8`
- 공통 에러 포맷: RFC 7807 Problem Details

---

## Endpoint 1: <한 줄 설명>

### 기본 정보
| 항목 | 값 |
|---|---|
| Method | `POST` |
| Path | `/v1/users/me/withdrawal` |
| 권한 | 로그인 유저 (본인만) |
| 멱등성 | 예 (`Idempotency-Key` 헤더 또는 동일 유저 중복 요청 동일 결과) |
| Rate Limit | 10 req/min per user |

### Request
#### Headers
| Name | Required | 설명 |
|---|---|---|
| Authorization | Y | `Bearer <JWT>` |
| Idempotency-Key | N | UUID (동일 키 재요청 시 이전 결과 반환) |
| X-Request-Id | N | 분산 추적용 |

#### Path Parameters
없음

#### Query Parameters
없음

#### Body
```json
{
  "password": "string (required, 8-64 chars)",
  "reason": "string (optional, max 500 chars)",
  "reasonCode": "PRICE | QUALITY | ETC (optional)"
}
```

| Field | Type | Required | 제약 | 설명 |
|---|---|---|---|---|
| password | string | Y | 8-64자 | 재확인용 |
| reason | string | N | ≤500자 | 자유 텍스트 |
| reasonCode | enum | N | - | 사전 정의 사유 코드 |

### Response
#### 200 OK
```json
{
  "data": {
    "status": "WITHDRAWN",
    "withdrawnAt": "2026-04-13T10:00:00Z",
    "scheduledDeleteAt": "2026-07-12T10:00:00Z"
  },
  "meta": { "timestamp": "2026-04-13T10:00:00Z" }
}
```

#### 에러
| HTTP | code | 조건 |
|---|---|---|
| 400 | `VALIDATION_FAILED` | 요청 body 검증 실패 |
| 401 | `INVALID_PASSWORD` | 비밀번호 불일치 |
| 401 | `UNAUTHORIZED` | 토큰 없음/만료 |
| 409 | `ACTIVE_ORDER_EXISTS` | 진행 중 주문 존재 |
| 409 | `ALREADY_WITHDRAWN` | 이미 탈퇴됨 |
| 503 | `ORDER_SERVICE_UNAVAILABLE` | 외부 연동 실패 |

에러 응답 예시:
```json
{
  "type": "https://api.company.com/errors/active-order-exists",
  "title": "Active order exists",
  "status": 409,
  "detail": "진행 중인 주문이 있어 탈퇴할 수 없습니다",
  "instance": "/v1/users/me/withdrawal",
  "code": "ACTIVE_ORDER_EXISTS"
}
```

### curl 예시
```bash
curl -X POST https://api-dev.company.com/v1/users/me/withdrawal \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{"password":"xxxxx","reasonCode":"ETC","reason":"..."}'
```

---

## Endpoint 2: <탈퇴 상태 조회>
(동일 포맷으로 계속)

---

## 이벤트 스펙
### `UserWithdrawn`
- **Topic/Channel**: `user.withdrawal.v1`
- **Producer**: User Service
- **Consumer**: Auth Service, Notification Service
- **Payload**
  ```json
  {
    "eventId": "uuid",
    "occurredAt": "2026-04-13T10:00:00Z",
    "userId": 12345,
    "scheduledDeleteAt": "2026-07-12T10:00:00Z"
  }
  ```
- **Schema Version**: v1
- **Ordering**: per-user FIFO (partition key: userId)

---

## Backward Compatibility
- 신규 필드 추가는 non-breaking
- 기존 필드 삭제/이름 변경은 `/v2` 분리 필요
- enum 값 추가는 Consumer 대응 확인 후

## Quality Gate
- [ ] 모든 엔드포인트 Request/Response 예시 포함
- [ ] 모든 에러 케이스 나열
- [ ] 이벤트 스펙(있는 경우) 작성
- [ ] OpenAPI YAML 파일과 일치 여부 확인
- [ ] status: `draft` → `approved`
