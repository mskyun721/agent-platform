# Setup Reference

## Requirements
| Tool | Purpose | Required |
|---|---|---|
| Codex CLI | default standalone agent runtime | yes |
| Gemini CLI | alternate standalone agent runtime | yes |
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
gemini
```

## MCP
Claude and Gemini use checked-in project config. Codex needs user-level registration:
```bash
codex mcp add agent-platform -- uv --directory ./mcp-server run agent-platform-mcp
```

## Standalone Agent Runner
Codex and Gemini can run without Claude Code:
```bash
uv --directory ./mcp-server run agent-platform-agent new-feature <feature>
uv --directory ./mcp-server run agent-platform-agent run planner <feature> --ai codex --requirements "..."
uv --directory ./mcp-server run agent-platform-agent run backend <feature> --ai codex
uv --directory ./mcp-server run agent-platform-agent run backend <feature> --ai gemini
uv --directory ./mcp-server run agent-platform-agent run reviewer <feature> --ai codex
uv --directory ./mcp-server run agent-platform-agent run security <feature> --ai gemini
uv --directory ./mcp-server run agent-platform-agent run qa <feature> --ai codex
uv --directory ./mcp-server run agent-platform-agent run cicd <feature> --ai gemini
uv --directory ./mcp-server run agent-platform-agent gate-check <feature>
```

Verify:
```bash
claude mcp list
codex mcp list
```

## Claude Permissions
Update `.claude/settings.json` so `additionalDirectories`, `Read`, `Write`, and `Edit` include the parent directory that contains target projects.

## Target Project
`project_init` writes the active project path to:
```text
agent-platform/.active-project
```

All feature artifacts use that path as `TARGET_PROJECT`.
