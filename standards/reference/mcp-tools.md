# MCP Tools Reference

The FastMCP entry point is `mcp-server/src/agent_platform_mcp/server.py`.

| Tool | Purpose |
|---|---|
| `hello` | smoke test |
| `project_init` | Kotlin/Java Spring project creation |
| `feature_scaffold` | create PRD/TASK from templates |
| `feature_list_artifacts` | list feature files and status |
| `feature_gate_check` | validate front-matter and prerequisites |
| `handoff_validate` | validate agent transition |
| `log_append` | append target project `claude_log.md` |
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
