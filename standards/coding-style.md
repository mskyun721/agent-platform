# Coding Style Standard

## 언어 & 버전
- Kotlin 2.x / JVM 21+
- Spring Boot 3.x + WebFlux
- Kotlin Coroutine (`suspend fun`, `Flow`)

## 네이밍
- 클래스/인터페이스: `PascalCase`
- 함수/변수: `camelCase`
- 상수: `UPPER_SNAKE_CASE`
- 패키지: `lowercase.no.underscore`
- 테스트 함수: backtick 한국어 허용 (`` `탈퇴 시 개인정보 마스킹된다`() ``)

## 구조 (Hexagonal Architecture)
```
com.company.feature/
├── adapter/
│   ├── in/web/           # Controller (coRouter)
│   └── out/persistence/  # Repository 구현
├── application/
│   ├── port/in/          # UseCase 인터페이스
│   ├── port/out/         # Repository 인터페이스
│   └── service/          # UseCase 구현
└── domain/               # 순수 도메인 모델
```

## 코드 원칙 (글로벌 CLAUDE.md 준수)
- **Immutable first**: `val > var`, `data class` 기본
- **Early return**으로 중첩 최소화, 최대 들여쓰기 3단계
- 매직 넘버 → `companion object` 상수 추출
- 함수 30줄 초과 시 분리
- 변수명은 의미 있게 (루프 인덱스만 `i, j` 예외)
- 주석은 WHY만 (WHAT/HOW는 코드로 표현)

## Null 처리
- Nullable 반환 대신 `Result<T>` 또는 sealed class 선호
- `!!` 사용 금지 (테스트 코드 예외)
- `?.let {}` 체인은 2단계까지

## Coroutine 규칙
- Controller는 `suspend fun` 또는 `coRouter`
- 블로킹 호출은 `withContext(Dispatchers.IO)` 감싸기
- `GlobalScope` 금지, 구조화된 동시성 준수
- `runBlocking`은 테스트/main에서만

## Exception
- 도메인 예외는 sealed class로 정의
- `application/exception/` 에 모음
- `@RestControllerAdvice`로 일괄 처리, 빈 catch 금지

## Gradle
- Kotlin DSL (`*.gradle.kts`)
- 공통 설정은 `buildSrc/src/main/kotlin/` 의 convention plugin
- 버전 관리는 `libs.versions.toml`

## Lint / Format
- ktlint + detekt 필수
- 커밋 전 `./gradlew ktlintCheck detekt` 통과 필수
