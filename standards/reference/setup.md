# Setup Reference

## Requirements
| Tool | Purpose | Required |
|---|---|---|
| Codex CLI | default standalone agent runtime | yes |
| Claude Code CLI | optional subagent UI/runtime | optional |
| Claude Pro/Max | Claude usage | optional |
| `uv` | MCP server runtime | yes |
| `jq` | Claude hook scripts | yes |

## Install
```bash
brew install uv jq
npm install -g @anthropic-ai/claude-code
claude login
codex login
```

## MCP
Claude uses checked-in project config. Codex needs user-level registration:
```bash
codex mcp add agent-platform -- uv --directory ./mcp-server run agent-platform-mcp
```

## Standalone Agent Runner
Codex can run without Claude Code:
```bash
uv --directory ./mcp-server run agent-platform-agent new-feature <feature>
uv --directory ./mcp-server run agent-platform-agent run planner <feature> --ai codex --requirements "..."
uv --directory ./mcp-server run agent-platform-agent run backend <feature> --ai codex
uv --directory ./mcp-server run agent-platform-agent run reviewer <feature> --ai codex
uv --directory ./mcp-server run agent-platform-agent run qa <feature> --ai codex
uv --directory ./mcp-server run agent-platform-agent gate-check <feature>
```

Verify:
```bash
claude mcp list
codex mcp list
```

## Claude Permissions
Set target-project allowlist roots in local `.agent-platform.env`:
```bash
AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS="/path/to/projects:/path/to/another-project-root"
```

Claude Code project permissions are generated into ignored local settings:
```bash
python3 scripts/sync_claude_settings.py
```

Do not hardcode personal paths in tracked `.claude/settings.json`.

## Target Project
`project_init` writes the active project path to:
```text
agent-platform/.active-project
```

All feature artifacts use that path as `TARGET_PROJECT`.
