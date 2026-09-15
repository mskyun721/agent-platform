---
agent: planner
feature: <feature-name>
status: draft
created: YYYY-MM-DD
updated: YYYY-MM-DD
links:
  prd: docs/<type>/<feature-name>/PRD.md
---

# API-SPEC: <기능명>

> REST API 상세 명세. `standards/api-contract.md` 규약 준수.
> 기획 단계에서 작성하고 개발 단계에서 구현과 일치하도록 갱신한다. API 변경이 없으면 해당 없음 사유를 기록하고 예시 엔드포인트는 제거한다.
> 기계 판독 계약: [openapi.yaml](openapi.yaml) (API 변경 시). 서비스 흐름: [FLOW.drawio](FLOW.drawio).
> 아래 예시는 실제 업무의 요청·응답·오류로 교체한다.

## 공통
- Base URL (dev): `https://api-dev.company.com`
- 인증: `Authorization: Bearer <JWT>`
- Content-Type: `application/json; charset=UTF-8`
- 공통 에러 포맷: `ErrorResponse` (`error.code`, `error.message`)
- 도메인 표기법: camelCase (기존 도메인 규칙에 맞춰 확정)
- 시각: `YYYY-MM-DD HH:mm:ss`; 타임존: <합의된 타임존>
- 스코프: <PROJECT / ORGANIZATION / MGMT / 해당 없음 및 사유>
- 계약 예외·기존 소비자 전환: <없음 또는 영향과 합의 내용>

---

## Endpoint 1: <한 줄 설명>

### 기본 정보
| 항목 | 값 |
|---|---|
| operationId | `withdrawUser` |
| Method | `POST` |
| Path | `/v1/users/me/withdrawal` |
| 권한 | 로그인 유저 (본인만) |
| x-permission | <service.resource.action 또는 none + 사유> |
| x-permission-space | <PROJECT / ORGANIZATION / MGMT; 해당 시> |
| Apidog | folder: <도메인>, status: designing, maintainer: <실제 담당자> |
| 멱등성 | 예 (`Idempotency-Key` 헤더 또는 동일 유저 중복 요청 동일 결과) |
| Rate Limit | 10 req/min per user |

### Request
#### Headers
| Name | Required | 설명 |
|---|---|---|
| Authorization | Y | `Bearer <JWT>` |
| Idempotency-Key | N | UUID (동일 키 재요청 시 이전 결과 반환) |
| X-Request-Id | N | 분산 추적용 |
| X-Project-Id / X-Org-Id | 해당 시 Y | 필요한 스코프 헤더만 남긴다. 누락 400, 인가 실패 403 |

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
  "status": "WITHDRAWN",
  "withdrawnAt": "2026-04-13 10:00:00",
  "scheduledDeleteAt": "2026-07-12 10:00:00"
}
```

응답 필드의 키는 required로 선언하고 null 허용을 별도로 정의한다. 배열은 빈 값도 `[]`, boolean은 true/false, 없는 스칼라는 null이다.
목록 API는 `{items,totalCount}` 또는 `{items,totalCount,page,size}`(0-base)를 사용한다. 204 응답에는 본문이 없다.

#### 에러
| HTTP | code | 조건 |
|---|---|---|
| 400 | `ACCOUNT.ERRORS.USER.VALIDATION_FAILED` | 요청 body 또는 필수 스코프 검증 실패 |
| 401 | `ACCOUNT.ERRORS.USER.INVALID_PASSWORD` | 비밀번호 불일치 |
| 401 | `ACCOUNT.ERRORS.USER.UNAUTHORIZED` | 토큰 없음/만료 |
| 403 | `ACCOUNT.ERRORS.USER.FORBIDDEN` | 권한 부족 |
| 409 | `ACCOUNT.ERRORS.USER.ACTIVE_ORDER_EXISTS` | 진행 중 주문 존재 |
| 409 | `ACCOUNT.ERRORS.USER.ALREADY_WITHDRAWN` | 이미 탈퇴됨 |
| 503 | `ACCOUNT.ERRORS.USER.ORDER_SERVICE_UNAVAILABLE` | 외부 연동 실패 |

에러 응답 예시:
```json
{
  "error": {
    "code": "ACCOUNT.ERRORS.USER.ACTIVE_ORDER_EXISTS",
    "message": "진행 중인 주문이 있어 탈퇴할 수 없습니다."
  }
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
- [ ] named schema/$ref, 도메인 우선 이름, ErrorCode enum과 x-apidog-enum 작성
- [ ] required와 null 구분, 날짜 pattern/타임존, ID string, 필드 description/example/제약 명시
- [ ] 권한·인증·스코프 헤더 및 Apidog folder/status/maintainer 확정
- [ ] 목록의 필터/검색/정렬 지원·제외 필드, 배열 style/explode, page/size 범위 명시
- [ ] Create/Update 분리, PATCH 생략/null/중첩 수정 의미 명시 (해당 시)
- [ ] 실제 HTTP 응답의 null/빈 배열/false/오류/204 및 Apidog round-trip 검증 결과 기록
- [ ] 모든 엔드포인트 Request/Response 예시 포함
- [ ] 모든 에러 케이스 나열
- [ ] 이벤트 스펙(있는 경우) 작성
- [ ] OpenAPI YAML 파일과 일치 여부 확인
- [ ] status: `draft` → `approved`
