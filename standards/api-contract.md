# API Contract Standard

## 기준과 적용 범위
- 기준 원문 (확인: 2026-09-15): [응답 계약](https://console-dev.gcloud.kt.com/front/policies/conventions/api/1-response-contract/), [BE 직렬화 지침](https://console-dev.gcloud.kt.com/front/policies/conventions/api/2-be-serialization-recipe/), [Apidog 명세 규약](https://console-dev.gcloud.kt.com/front/policies/conventions/api/3-apidog-spec/).
- 지원 대상 서비스의 신규·수정 API에 적용한다. 플랫폼 MCP 도구의 반환 dict를 HTTP 응답 DTO로 일괄 변경하지 않는다.
- 기존 소비자가 있는 API는 호환성 영향과 전환 계획을 API-SPEC/DECISIONS에 기록하고 합의 후 변경한다.
- 원문 간 차이: 날짜는 응답 계약의 `YYYY-MM-DD HH:mm:ss`를 기본으로 삼고 타임존을 명세한다. Apidog 문서의 ISO 8601 예시는 이를 덮어쓰지 않는다. 기존 ISO 8601 계약 유지 시 예외를 기록한다.
- 스키마 이름은 Apidog의 도메인 우선 명명 절을 적용한다 (`ContactCreateRequest`). 본문의 `CreateContactRequest` 예시와 혼용하지 않는다.

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
| PUT | 전체 업데이트 | 200 + 수정된 단건 |
| PATCH | 부분 업데이트 | 200 + 수정된 단건 |
| DELETE | 삭제 | 204 |

## 응답 포맷
### 성공: 단건은 객체 자체, 목록만 고정 봉투
- 단건에 `data`, `result`, 리소스명 래퍼를 추가하지 않는다.
- 비페이지 목록은 `items`, `totalCount`; 페이지 목록은 추가로 `page`, `size`를 제공한다. `page`는 0-base다.
- `items`는 항상 배열이며 빈 결과도 `[]`다. Spring Page/PageImpl/Slice를 그대로 직렬화하지 않는다.
- 비페이지 totalCount는 전체 반환 개수, 페이지 totalCount는 필터 적용 후 전체 일치 개수다.
```json
{
  "id": "resource-1",
  "description": null,
  "enabled": false,
  "contacts": [],
  "state": { "updatedAt": null }
}
```

### 필드와 직렬화
- 요청 body·query·응답은 도메인 단위로 camelCase 또는 snake_case를 일관되게 사용한다. 고정 봉투 키는 위 계약을 유지한다.
- 응답의 선언된 키는 생략하지 않는다. 없는 스칼라는 null이며 빈 문자열/0으로 대체하지 않는다. 실제 빈 문자열/0과 부재는 구별한다.
- 구조적 객체/Map은 항상 존재한다. 고정 객체의 내부 필드에도 규칙을 재귀 적용하고 빈 Map은 `{}`로 반환한다. 선택적 하위 리소스 관계는 객체 전체 null을 허용한다.
- boolean은 true/false만 허용한다. 미정 등 제3 상태는 enum으로 모델링하며 null을 무조건 false로 바꾸지 않는다.
- ID·큰 정수·소수·금액은 string, enum은 닫힌 문자열 집합, NaN/Infinity는 null로 표현한다.
- 감사 필드는 createdAt/createdBy/updatedAt/updatedBy를 기준으로 도메인 표기법을 적용한다.
- Spring/Jackson은 응답 DTO·매퍼 범위에서 루트 래핑과 NON_NULL/NON_EMPTY에 의한 필드 누락을 제거한다. 전역 ObjectMapper나 요청 역직렬화까지 무분별하게 변경하지 않는다.
- 배열·컨테이너는 실제 매퍼의 모든 생성 경로에서 non-null을 보장한다. 생성자/빌더 기본값만으로 보장됐다고 판단하지 않는다.
- 외부 passthrough 고정 키는 예외와 사유를 명시하고 필요한 필드에만 JsonProperty를 사용한다.
- 공통 목록 DTO와 ArchUnit은 선택 사항이다. 내부 Page 사용 자체가 아니라 와이어 응답 노출을 방지한다.

### 에러
```json
{
  "error": {
    "code": "ACCOUNT.ERRORS.USER.NOT_FOUND",
    "message": "사용자를 찾을 수 없습니다."
  }
}
```
- 공통 ErrorResponse를 사용한다. code는 `{SERVICE}.ERRORS.{RESOURCE}.{REASON}`의 사전 정의 값, message는 사용자에게 바로 표시 가능한 안전한 문장이다.
- 소비자는 code로 분기한다. 상태별 모든 발생 가능 코드와 대표 예시를 선작성하고 내부 예외·개인정보는 노출하지 않는다.

## 상태 코드
- 2xx: 성공
- 4xx: 클라이언트 오류 (400 잘못된 요청, 401 인증, 403 권한, 404 없음, 409 충돌, 422 검증 실패)
- 5xx: 서버 오류 (500 내부, 502/503/504 외부 의존성)

## 입력 검증
- DTO에 `@field:NotNull`, `@field:Size` 등 Bean Validation
- `@Valid` 또는 `.awaitBody<T>()` + validator
- 검증 실패 기본값은 400 + ErrorResponse다. 필드 안내는 안전한 message에 포함하고 구조화 확장이 필요하면 별도 합의한다. 기존 422 계약 유지 시 예외를 기록한다.

## 요청 의미와 조회
- 스코프는 X-Project-Id/X-Org-Id 헤더로 전달한다. 해당 API에 필요한 헤더를 required로 지정하고 누락은 400이다. body/query 값으로 권한 스코프를 대체하지 않는다.
- Create와 Update 요청 스키마는 독립 정의한다. PUT은 전체 교체이며 누락 필드 초기화/필수 필드 오류를 명세한다.
- PATCH는 Update의 필드 의미를 공유하되 부분 수정용 named schema를 둔다. 생략은 유지, 명시 null의 허용/삭제 의미는 별도 정의한다. 중첩 객체 구조를 유지하고 dot-notation을 쓰지 않는다.
- GET 목록은 page/size, 반복 sort (`createdAt,desc`), 정확 일치 필터, q/searchFields를 명세한다. 지원하지 않는 응답 필드는 제외 사유를 명시한다. 허용 필드를 검증하고 쿼리에 문자열로 직접 삽입하지 않는다.
- 배열 필터는 CSV 복수형 키(style: form, explode: false) 또는 반복 단수형 키(explode: true) 중 하나를 선택한다. 콤마를 포함하는 값은 반복 키를 사용하고 대괄호 표기는 쓰지 않는다.

## 인증/인가
- Bearer 토큰(JWT) `Authorization: Bearer <token>`
- 공개 API는 명시적으로 `@PermitAll` 표기
- 권한 체크는 `@PreAuthorize` 또는 Security DSL

## OpenAPI 문서
- 구현 전 API-SPEC.md와 front-matter 없는 openapi.yaml을 작성한다. Apidog import용 기본 버전은 OpenAPI 3.1이다.
- 요청/응답 body, 목록 items, 중첩 값객체, 오류, enum은 components/schemas의 named schema로 정의하고 `$ref`로 연결한다. operation에 익명 object를 두지 않는다.
- 이름은 `{Domain}[Page|List][Create|Update|Patch](Request|Response)`를 사용한다. 값객체·enum·공용 메타는 별도 이름을 둔다.
- ListMeta/PageMeta를 공용으로 두고 도메인 목록을 allOf로 조합할 수 있다. PATCH에 required가 있는 Update를 allOf로 연결하면 필수가 해제되지 않으므로 그렇게 구현하지 않는다.
- 응답 키의 존재(required)와 null 허용은 별개다. OpenAPI 3.1은 `type: [string, 'null']` 또는 anyOf로 null을 표현한다. 기존 3.0 export와 교환할 때 nullable 변환과 round-trip을 검증한다.
- 필드마다 description/example, 타입·필수·null·제약·기본값을 명시한다. ID는 string, 자기 식별자는 id, FK는 entityId이며 표시용 FK 이름이 필요하면 entityName을 함께 제공한다.
- 날짜 기본 형식은 string + pattern + 타임존 설명으로 표현한다. RFC 3339가 아닌 값에 format: date-time을 붙이지 않는다.
- 각 operation은 고유하고 안정적인 camelCase operationId, 한글 summary, 요청, 성공 예시 및 상태별 오류 예시를 갖춘다. DELETE 204에는 content/schema/body 예시를 넣지 않는다.
- 모든 조회/변경 operation에 x-permission과 해당 x-permission-space(PROJECT/ORGANIZATION/MGMT), description의 권한 설명을 둔다. 권한명은 `service.resource.action`이고 get_list 등 액션은 snake_case다.
- 공개 API는 x-permission: none과 사유, S2S는 추가로 x-auth: s2s를 명시한다. security에는 실제 인증을 선언하며 x-permission이 인증 설정을 대신하지 않는다.
- x-apidog-folder/status/maintainer를 채우되 실제 담당자를 추측하지 않는다. 설계는 designing으로 시작하고 미확정 담당자는 인계 전 확인한다.
- 설명이 필요한 enum, 특히 ErrorCode에는 표준 enum과 일치하는 x-apidog-enum(value/name/description)을 추가한다.
- `/v3/api-docs`, `/swagger-ui.html` 노출 (운영은 내부망 한정)
- 각 엔드포인트는 `@Operation`, 파라미터는 `@Parameter` 명시
- 응답 예시는 `@ExampleObject` 포함

## 검증과 발행
- 실제 HTTP 직렬화 테스트로 빈 목록, null 스칼라, 빈 구조적 객체/Map, nullable 관계, false, 중첩 필드, 오류 봉투, 204 무본문을 검증한다. DTO 생성만 검사하는 테스트로 대체하지 않는다.
- 인증 401, 권한 403, 스코프 누락 400, 검증 400, 없음 404, 충돌 409와 성공 케이스를 API-SPEC 및 OpenAPI에 연결한다.
- Apidog import/export 후 required/null, named ref, enum 확장, 배열 쿼리 직렬화, 권한 확장의 보존을 확인한다. 실행하지 못한 검증은 not_run으로 기록한다.
- 원격 import/브랜치 생성은 사용자 승인 후 수행한다. 플랫폼 Apidog MCP는 읽기 전용이다.
- 승인된 발행은 날짜 라벨 브랜치와 `{TARGET_PROJECT}/docs/<type>/<name>/spec-snapshots/<project>-YYYY-MM-DD.yaml`로 추적한다. 기존 스냅샷은 보존하며 특정 AI의 스킬 디렉터리에 종속시키지 않는다.

## Breaking Change 규칙
- 필드 삭제/이름 변경은 Breaking
- 신규 필드 추가는 Non-breaking (nullable 기본)
- Breaking 발생 시 `/v2` 신규 버전
