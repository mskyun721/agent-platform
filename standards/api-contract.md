# API Contract Standard

## 기본 원칙
- REST 원칙 준수 (리소스 중심)
- 모든 API는 OpenAPI 3.1 스펙으로 문서화
- Controller는 `coRouter` DSL 사용 (WebFlux)

## URL 설계
- 리소스는 복수형: `/users`, `/orders`
- 액션보다 HTTP 메서드로 의미 표현
- 계층 구조: `/users/{userId}/orders/{orderId}`
- 케밥 케이스: `/payment-methods`
- 버전: URL 경로 prefix `/v1/...`

## HTTP 메서드
| 메서드 | 용도 | 응답 |
|---|---|---|
| GET | 조회 | 200, 404 |
| POST | 생성 | 201 + Location 헤더 |
| PUT | 전체 업데이트 | 200, 204 |
| PATCH | 부분 업데이트 | 200, 204 |
| DELETE | 삭제 | 204 |

## 응답 포맷
### 성공
```json
{
  "data": { ... },
  "meta": { "timestamp": "2026-04-13T10:00:00Z" }
}
```

### 페이지네이션
```json
{
  "data": [ ... ],
  "meta": {
    "page": 1,
    "size": 20,
    "total": 153
  }
}
```

### 에러 (RFC 7807 Problem Details)
```json
{
  "type": "https://api.company.com/errors/user-not-found",
  "title": "User not found",
  "status": 404,
  "detail": "User with id=123 does not exist",
  "instance": "/v1/users/123",
  "code": "USER_NOT_FOUND"
}
```

## 상태 코드
- 2xx: 성공
- 4xx: 클라이언트 오류 (400 잘못된 요청, 401 인증, 403 권한, 404 없음, 409 충돌, 422 검증 실패)
- 5xx: 서버 오류 (500 내부, 502/503/504 외부 의존성)

## 입력 검증
- DTO에 `@field:NotNull`, `@field:Size` 등 Bean Validation
- `@Valid` 또는 `.awaitBody<T>()` + validator
- 검증 실패 시 422 + detail에 field error 목록

## 인증/인가
- Bearer 토큰(JWT) `Authorization: Bearer <token>`
- 공개 API는 명시적으로 `@PermitAll` 표기
- 권한 체크는 `@PreAuthorize` 또는 Security DSL

## OpenAPI 문서
- `/v3/api-docs`, `/swagger-ui.html` 노출 (운영은 내부망 한정)
- 각 엔드포인트는 `@Operation`, 파라미터는 `@Parameter` 명시
- 응답 예시는 `@ExampleObject` 포함

## Breaking Change 규칙
- 필드 삭제/이름 변경은 Breaking
- 신규 필드 추가는 Non-breaking (nullable 기본)
- Breaking 발생 시 `/v2` 신규 버전
