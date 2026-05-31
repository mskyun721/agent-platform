# Coding Style — Kotlin

- Kotlin 2.x / JVM 21+, Spring Boot 3.x + WebFlux

## 코드 원칙
- `val > var`, `data class` 기본 — Immutable first
- `!!` 사용 금지 (테스트 코드 예외), `?.let {}` 체인은 2단계까지
- Nullable 반환 대신 `Result<T>` 또는 sealed class 선호
- Early return으로 중첩 최소화 (최대 3단계), 함수 30줄 초과 시 분리
- 매직 넘버 → `companion object` 상수, 주석은 WHY만

## Coroutine
- Controller: `suspend fun` 또는 `coRouter`
- 블로킹 호출: `withContext(Dispatchers.IO)` 감싸기
- `GlobalScope` 금지, `runBlocking`은 테스트/main에서만

## 예외
- 도메인 예외: sealed class로 정의, `application/exception/` 에 모음
- `@RestControllerAdvice`로 일괄 처리, 빈 catch 금지

## 빌드 / Lint
- Gradle Kotlin DSL (`*.gradle.kts`), `buildSrc/` convention plugin, `libs.versions.toml`
- ktlint + detekt 필수 — 커밋 전 `./gradlew ktlintCheck detekt` 통과
