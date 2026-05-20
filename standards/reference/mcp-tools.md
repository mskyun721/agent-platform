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
| `plan_run_gemini` | PRD/TASK draft via Gemini |
| `plan_run_codex` | PRD/TASK draft via Codex |
| `backend_run_codex` | backend implementation and API/decision artifacts via Codex |
| `backend_run_gemini` | backend implementation and API/decision artifacts via Gemini |
| `review_run_gemini` | REVIEW draft via Gemini |
| `review_run_codex` | REVIEW draft via Codex |
| `audit_run_gemini` | SECURITY-AUDIT draft via Gemini |
| `audit_run_codex` | SECURITY-AUDIT draft via Codex |
| `qa_run_gemini` | TEST-PLAN / QA draft via Gemini |
| `qa_run_codex` | TEST-PLAN / QA draft via Codex |
| `release_run_gemini` | PR/release/checklist drafts via Gemini |
| `release_run_codex` | PR/release/checklist drafts via Codex |
| `standards_read` | read whitelisted standard/template/workflow doc |
| `standards_list` | list whitelisted docs |
| `confluence_fetch_page` | fetch a Confluence page by ID and return as Markdown |
| `confluence_list_space` | list pages in a Confluence space by space key |
| `confluence_create_page` | create a single Confluence page from Markdown under a parent page |
| `confluence_sync_feature` | bulk-upload a feature's MD artifacts to Confluence |

Debugging raw JSON-RPC calls should stay here, not in `README.md`.
