# Setup Reference

## Requirements
| Tool | Purpose | Required |
|---|---|---|
| Claude Code CLI | main agent runtime | yes |
| Claude Pro/Max | Claude usage | yes |
| `uv` | MCP server runtime | yes |
| `jq` | Claude hook scripts | yes |
| Codex CLI | optional CLI backend, reviewer default pair | optional |
| Gemini CLI | optional CLI backend, reviewer default pair | optional |
| Docker | Langfuse self-hosted check | optional |

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
