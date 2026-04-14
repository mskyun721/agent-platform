# Agent Platform - Project Instructions

이 프로젝트는 기획/백엔드/QA/CICD 4개 역할을 Claude Code Subagent로 구성한 팀 공통 개발 워크플로우 플랫폼이다.

## 기본 원칙
- 모든 Subagent는 본 문서와 `standards/` 하위 표준을 **반드시** 참조한다
- 모든 산출물은 `templates/` 의 Front-matter 규약을 준수한다
- Feature 작업 산출물은 `docs/features/<feature-name>/` 하위에 저장한다
- Agent 간 Handoff는 `workflows/` 플로우를 따른다

## 기술 스택
- Language: Kotlin (JVM 21+)
- Framework: Spring Boot 3.x + WebFlux (reactive, coRouter)
- Async: Kotlin Coroutine
- Build: Gradle Kotlin DSL + buildSrc
- Test: JUnit5 + MockK + Testcontainers
- Architecture: Hexagonal (Ports & Adapters)

## 공통 표준 참조
- 코드 스타일: `standards/coding-style.md`
- 커밋/브랜치: `standards/commit-convention.md`
- API 계약: `standards/api-contract.md`
- 테스트 정책: `standards/test-policy.md`
- 보안 베이스라인: `standards/security-baseline.md`

## Front-matter 규약 (모든 산출물 필수)
```yaml
---
agent: planner | backend | qa | cicd
feature: <feature-name>
status: draft | review | approved | rejected
created: YYYY-MM-DD
updated: YYYY-MM-DD
links:
  prd: docs/features/<name>/PRD.md
  api: docs/features/<name>/API-SPEC.md
---
```

## Agent 호출 규칙
- 직접 호출: `@planner`, `@backend`, `@qa`, `@cicd`
- 자동 라우팅: 사용자 요청을 Orchestrator가 분석하여 적절한 Agent 위임
- 다음 Agent는 이전 Agent의 Quality Gate 통과 산출물만 수용

## 글로벌 지침 상속
사용자 글로벌 `~/.claude/CLAUDE.md` 규칙(응답 한국어, 보안 절대 규칙 등)을 모두 상속한다.

## 작업 로그
모든 진행 작업은 루트 `claude_log.md`에 기록한다.
