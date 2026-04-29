# Test Policy

## 테스트 피라미드
```
        /  E2E  \         5%
       /--------\
      / Integ   \        25%
     /----------\
    /   Unit     \       70%
   /--------------\
```

## 도구

### [Kotlin]
- **Unit**: JUnit5 + MockK + Kotest assertions
- **Integration**: Spring Boot Test + Testcontainers (PostgreSQL, Redis 등)
- **E2E**: WebTestClient + 실제 DB (Testcontainers)

### [Java]
- **Unit**: JUnit5 + Mockito + AssertJ
- **Integration**: Spring Boot Test + Testcontainers (PostgreSQL, Redis 등)
- **E2E**: WebTestClient + 실제 DB (Testcontainers)

## 파일 구조

### [Kotlin]
```
src/test/kotlin/
├── unit/          # 단일 클래스, 의존성 mock
├── integration/   # 여러 컴포넌트 + 실제 DB
└── e2e/           # HTTP 레벨 전체 플로우
```

### [Java]
```
src/test/java/
├── unit/          # 단일 클래스, 의존성 mock
├── integration/   # 여러 컴포넌트 + 실제 DB
└── e2e/           # HTTP 레벨 전체 플로우
```

## 네이밍

### [Kotlin]
- 클래스: `<ProductionClass>Test` 또는 `<Feature>IntegrationTest`
- 메서드: backtick 한국어, Given-When-Then 구조
```kotlin
@Test
fun `가입된 유저가 탈퇴 요청 시 상태가 WITHDRAWN으로 변경된다`() { ... }
```

### [Java]
- 클래스: `<ProductionClass>Test` 또는 `<Feature>IntegrationTest`
- 메서드: `@DisplayName` 한국어, Given-When-Then 구조
```java
@Test
@DisplayName("가입된 유저가 탈퇴 요청 시 상태가 WITHDRAWN으로 변경된다")
void withdrawnUser_shouldChangeStatusToWithdrawn() { ... }
```

## 커버리지 기준 (공통)
- Domain 레이어: **90%+**
- Application 레이어: **85%+**
- Adapter 레이어: **70%+**
- 전체: **80%+** (JaCoCo)
- DTO, Configuration 클래스 제외

## 필수 테스트 대상 (공통)
- 모든 UseCase (`application/service/`)
- 모든 도메인 규칙 (`domain/`)
- 모든 Controller 엔드포인트 (happy path + 주요 에러)
- 모든 Repository 쿼리 (복잡한 조건 포함 시)

## Mock 정책 (공통)
- **Unit Test**: 외부 의존성 모두 mock ([Kotlin] MockK / [Java] Mockito)
- **Integration Test**: DB는 **실제 사용** (Testcontainers), 외부 API만 MockWebServer
- **E2E**: 최대한 실제, 필수 불가피한 외부 시스템만 mock

## 비동기 테스트

### [Kotlin] Coroutine
- `runTest { }` 사용 (kotlinx-coroutines-test)
- `Dispatchers.setMain()` + `resetMain()` 셋업
- Flow 테스트는 `turbine` 라이브러리

### [Java] Reactor
- `StepVerifier.create(...).expectNext(...).verifyComplete()` 사용
- `StepVerifier.withVirtualTime(...)` 으로 시간 기반 테스트
- 블로킹 `block()` 은 테스트에서만 허용

## 실패 정책 (공통)
- 빈 테스트, `@Disabled` 남발 금지
- Flaky 테스트 발견 시 즉시 수정 또는 격리 (무시 금지)
- 테스트 깨지면 기능 개발보다 우선

## CI 연동 (공통)
- PR 생성 시 전체 테스트 실행
- 커버리지 리포트 PR 코멘트 자동 게시
- 기준 미달 시 머지 차단
