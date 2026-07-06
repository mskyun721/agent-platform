# MCP Tools Reference

The FastMCP entry point is `mcp-server/src/agent_platform_mcp/server.py`.

| Tool | Purpose |
|---|---|
| `hello` | smoke test |
| `project_init` | Kotlin/Java Spring project creation |
| `feature_scaffold` | create PRD/TASK from templates |
| `feature_list_artifacts` | list feature files and status |
| `feature_gate_check` | validate front-matter and prerequisites; `fix/`\|`hotfix/` names use a lightweight PRD+REVIEW track (`track: "light"`\|`"full"` in result); `verify=true` also runs `.agent-config.json`'s `gate_verify_command` and gates on its exit code |
| `handoff_validate` | validate agent transition |
| `plan_run` | PRD/TASK draft (cli: auto\|codex\|gemini) |
| `backend_run` | backend implementation and API/decision artifacts (cli: auto\|codex\|gemini) |
| `review_run` | REVIEW draft (cli: auto\|codex\|gemini) |
| `audit_run` | SECURITY-AUDIT draft (cli: auto\|codex\|gemini) |
| `qa_run` | TEST-PLAN / QA draft (cli: auto\|codex\|gemini) |
| `release_run` | PR/release/checklist drafts (cli: auto\|codex\|gemini) |
| `standards_read` | read whitelisted standard/template/workflow doc |
| `standards_list` | list whitelisted docs |
| `confluence_fetch_page` | fetch a Confluence page by ID and return as Markdown |
| `confluence_list_space` | list pages in a Confluence space by space key |
| `confluence_create_page` | create a single Confluence page from Markdown under a parent page |
| `confluence_sync_feature` | bulk-upload a feature's MD artifacts to Confluence |
| `apidog_list_endpoints` | list summarized endpoints (method/path/summary) from an API Dog project |
| `apidog_export_openapi` | export full OpenAPI 3.0 spec from an API Dog project |
| `apidog_fetch_endpoint_detail` | fetch request/response detail for a single endpoint |

Debugging raw JSON-RPC calls should stay here, not in `README.md`.

## 장시간 위임 (10분 이상 예상 작업)

MCP 래퍼는 동기 호출이라 완료까지 블로킹된다 (`backend_run` 최대 1800초).
장시간 구현 위임은 다음 패턴을 권장한다:

1. `backend_run(feature, cli=..., dry_run=true)` 로 프롬프트/커맨드만 생성
2. 반환된 command를 Bash `run_in_background`로 직접 실행
3. 완료 후 산출물 파일(API-SPEC.md, DECISIONS.md, 코드)을 검증하고 front-matter status를 승격

`backend_run`/`plan_run`/`qa_run`/`release_run`은 외부 CLI가 대상 파일(API-SPEC.md, PRD.md/TASK.md, TEST-PLAN.md, PR-BODY.md 등)을 직접 작성하도록 지시한다 — wrapper는 완료 후 front-matter 보정만 수행하고, stdout은 요약(summary)으로만 반환된다.
반면 `review_run`/`audit_run`은 CLI의 stdout 전체를 캡처해 그대로 REVIEW.md/SECURITY-AUDIT.md 본문으로 저장한다 — stdout에 CLI 배너나 설치 로그가 섞이면 산출물에도 그대로 남으므로, 그런 경우 산출물을 재생성한다.
