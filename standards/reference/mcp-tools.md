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
| `review_run_gemini` | REVIEW draft via Gemini |
| `review_run_codex` | REVIEW draft via Codex |
| `audit_run_gemini` | SECURITY-AUDIT draft via Gemini |
| `qa_run_gemini` | TEST-PLAN / QA draft via Gemini |
| `qa_run_codex` | TEST-PLAN / QA draft via Codex |
| `release_run_gemini` | PR/release/checklist drafts via Gemini |
| `standards_read` | read whitelisted standard/template/workflow doc |
| `standards_list` | list whitelisted docs |

Debugging raw JSON-RPC calls should stay here, not in `README.md`.
