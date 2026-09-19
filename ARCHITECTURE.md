# agent-platform Architecture

## Layout

`mcp-server/src/agent_platform_mcp/`의 Python/FastMCP 서버와 CLI가 플랫폼 런타임이다. `tools/`는 플랫폼 작업을 구현한다. `scripts/`는 보조 명령, `standards/`와 `templates/`는 대상 프로젝트 지침과 산출물 계약, `tests/`는 플랫폼 검증이다.

## Rules

- server/CLI는 공통 tools 로직을 재사용한다. backend별 구현 차이는 runner 경계에 둔다.
- 대상 경로는 config의 allowlist 및 등록 프로젝트 검사를 통과시킨다. 사용자 문자열을 쉘 코드로 실행하지 않는다.
- 원문 prompt/source/tool output을 관측 DB에 기본 저장하지 않는다.
- 외부 변경은 action ledger와 명시적 사용자 승인 범위를 따른다. CLI 성공과 산출물 승인을 구분한다.
- 역할 원본은 standards/agents이며 .claude/agents는 동기화 adapter다.
- Kotlin/WebFlux 헥사곤 규칙은 대상 JVM 프로젝트용이며 Python 플랫폼에 강제하지 않는다.
- 파일/의존 현황은 코드 그래프와 실제 소스로 검증한다. ignored docs/PROMPT는 공통 코드 탐색에서 제외한다.

## Verification

`uv --directory mcp-server run --locked --dev python -m pytest ../tests -q`와 역할 adapter 동기화 검사를 사용한다.
