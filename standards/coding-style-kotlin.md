# Coding Style — Kotlin

- Kotlin 2.x / JVM 21+, Spring Boot 3.x + WebFlux

## 네이밍
- 클래스/인터페이스: `PascalCase` / 함수·변수: `camelCase` / 상수: `UPPER_SNAKE_CASE`
- 패키지: `lowercase.no.underscore`
- 테스트 함수: backtick 한국어 허용 (`` `탈퇴 시 개인정보 마스킹된다`() ``)

## 구조 (Hexagonal)
```
com.company.feature/
├── adapter/in/web/          # coRouter Router + Handler
├── adapter/out/persistence/ # R2DBC Repository 구현
├── application/port/in/     # UseCase 인터페이스
├── application/port/out/    # Repository 인터페이스
├── application/service/     # UseCase 구현
└── domain/                  # 순수 도메인 모델 (인프라 의존 금지)
```

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
