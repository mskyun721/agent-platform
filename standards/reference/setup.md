# Setup Reference

## Quick Start
```bash
./scripts/setup.sh --roots ~/Projects --target ~/Projects/my-service   # or a git URL as --target
# manual: cp .env.example .env, edit AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS, then ./scripts/setup.sh
```
Steps: tools check, `.env`, uv sync, host adapters, skills, targets, doctor. Re-runnable;
`--roots` is written to a newly created `.env` only. Step-by-step guide for new users:
[getting-started.md](getting-started.md).
The sections below describe what the script does and the manual equivalents.

## Requirements
| Tool | Purpose | Required |
|---|---|---|
| Codex CLI | default standalone agent runtime | yes |
| Claude Code CLI | optional subagent UI/runtime | optional |
| Claude Pro/Max | Claude usage | optional |
| Gemini CLI | optional host/wrapper backend | optional |
| GitHub Copilot CLI | optional host/wrapper backend | optional |
| `uv` | MCP server runtime | yes |

## Install
```bash
brew install uv
npm install -g @anthropic-ai/claude-code
claude login
codex login
```

## MCP
Claude uses checked-in project config. Codex needs user-level registration:
```bash
codex mcp add agent-platform -- uv --directory ./mcp-server run agent-platform-mcp
```

Gemini reads the generated `.gemini/settings.json`; Copilot reads the workspace
`.mcp.json`. Both use their own CLI login; the platform never reads their auth files.
Regenerate host adapters with `python3 scripts/sync_hosts.py`.

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
`.env` is the only local environment file (copy `.env.example`). Set the
target-project allowlist roots there; legacy `.agent-platform.env` / `.env.local`
are still read with a deprecation notice:
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

The file may list several targets, one absolute path per line. The first line is
the default `TARGET_PROJECT`; the others are picked per request by folder name.
Listing a path never widens the allowlist.
```bash
uv --directory ./mcp-server run agent-platform-agent gate-check <feature> --root service-b   # listed folder name
uv --directory ./mcp-server run agent-platform-agent project-add <path | git URL>            # list a target; a URL is cloned into the allowlist
uv --directory ./mcp-server run agent-platform-agent project-use service-b                   # move to first line
uv --directory ./mcp-server run agent-platform-agent project-register /abs/service --project-id service-a  # optional ID: verify profile, skills
```

## Skills
`skills/packages/` is the tracked source. `.claude/skills/<id>` and `.agents/skills/<id>`
are generated (gitignored) by `setup.sh` via `skill sync agent-platform`; graphify is
installed by the graphify tool and stays tracked.
