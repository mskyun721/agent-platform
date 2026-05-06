# Langfuse Observability Reference

Langfuse integration exists but currently needs environment-specific verification and repair before it is treated as reliable.

## Intended Design
- Claude hooks summarize tool calls and session timing.
- MCP subprocess wrappers summarize Gemini/Codex execution timing and exit codes.
- Raw prompts, stdout, stderr, tool input, and tool output should not be sent.

## Files
- `scripts/langfuse-hook.sh`
- `scripts/langfuse-stop-hook.sh`
- `mcp-server/src/agent_platform_mcp/observability.py`
- `docker-compose.langfuse.yml`

## Local Check
```bash
docker compose -f docker-compose.langfuse.yml up -d
cd mcp-server
uv sync
```

Set `.env.local` with `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_HOST`.

## Follow-up
Before relying on this in workflow gates, verify hook execution, trace correlation, MCP span creation, and no-op behavior when keys are absent.
