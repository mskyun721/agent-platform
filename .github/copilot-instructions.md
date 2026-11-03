# Copilot 전용 지침

- `AGENTS.md` 를 따른다. 이 파일은 Copilot 에만 적용된다.
- `.active-project` 대상 프로젝트의 개발·수정 요청(기능 추가, API 변경, 버그 수정 등)은 직접 코드를 고치지 말고 orchestrator 흐름으로 처리한다: 요청을 분석해 planner → backend → reviewer → (security/dba) → qa 중 필요한 역할 에이전트(`task` 도구)와 `agent-platform` MCP 도구로 진행한다.
- 역할 에이전트에는 `TARGET_PROJECT`(`.active-project` 절대 경로)와 산출물 경로 `docs/<type>/<name>/` 를 명시해 전달한다.
- 사용자가 `[AI: ...]` 또는 직접 수행을 명시하면 그 지시가 우선한다.
