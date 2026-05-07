# Coding Style — Java

- Java 21+, Spring Boot 3.x + WebFlux (Project Reactor)

## 네이밍
- 클래스/인터페이스: `PascalCase` / 메서드·변수: `camelCase` / 상수: `UPPER_SNAKE_CASE`
- 패키지: `lowercase.no.underscore`
- 테스트 메서드: `@DisplayName("탈퇴 시 개인정보 마스킹된다")` 사용

## 코드 원칙
- 필드는 `final` 기본, setter 금지 — Immutable first
- 값 객체는 `record` 사용 (Java 16+)
- `Optional` 남용 금지 — 반환 타입에만, 필드·파라미터 금지
- Early return으로 중첩 최소화 (최대 3단계), 메서드 30줄 초과 시 분리
- 매직 넘버 → `static final` 상수, 주석은 WHY만

## Reactor
- `Mono<T>` / `Flux<T>` 반환 타입 필수 (블로킹 반환 금지)
- Reactor 체인 내 블로킹 I/O 절대 금지 (`block()`, `Thread.sleep()` 등)
- 블로킹 작업 격리: `Mono.fromCallable(...).subscribeOn(Schedulers.boundedElastic())`
- `subscribe()`는 진입점에서만, 체인 중간 호출 금지

## 예외
- 도메인 예외: sealed interface + record 구현체로 정의
- `@RestControllerAdvice`로 일괄 처리, 빈 catch 금지

## 빌드 / Lint
- Gradle Kotlin DSL 또는 Maven (`pom.xml`)
- Checkstyle 필수 (`google_checks.xml` 기반)
- 커밋 전 `./gradlew checkstyleMain` 또는 `mvn checkstyle:check` 통과
