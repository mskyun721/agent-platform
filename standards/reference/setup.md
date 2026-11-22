# Setup Reference

## Quick Start
```bash
./scripts/setup.sh --roots ~/Projects --target ~/Projects/my-service   # or a git URL as --target
# manual: ./scripts/setup.sh, then `project-workspace add <dir>` and `project-add <path|git URL>`
```
Steps: tools check, `.env` (secrets only), uv sync, host adapters, skills, workspaces
(`--roots` → `project-workspace add`), targets (`--target` → `project-add`, the first is the
default), `project-migrate`, Claude permissions, doctor. Re-runnable. Step-by-step guide for new users:
[getting-started.md](getting-started.md).
The sections below describe what the script does and the manual equivalents.

## Requirements
| Tool | Purpose | Required |
|---|---|---|
| AI CLI (Claude Code — default, Codex, Gemini CLI, Copilot CLI) | at least one host to run the roles | yes (one or more) |
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

## Explicit Delegation Runner
Same-AI roles run directly in the current session. Use the runner only when a role must run on another CLI (explicit delegation):
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

## Project Registry
All project settings live in one ignored, local-only file, `.agent-projects.json`,
created automatically by `setup.sh` / `project-add` / `project-workspace add`
(`.agent-projects.lock` next to it is the automatic write lock):
```json
{"version": 2, "default": "<project_id>", "workspaces": ["/abs/dir"],
 "projects": {"<project_id>": {"path": "/abs/path", "git_common_dir": null, "verify_profile_id": null,
                               "registered_at": "...", "skills": {}, "publish": {"target": "none"}}}}
```
Allowed paths are the platform root itself, workspace subtrees and registered project
subtrees (symlinks resolved). Workspaces and paths outside them are changed by the CLI
only; MCP `project_register`/`project_rebind`/`project_init` stay inside workspaces and
`project_use` picks registered projects only.

`.env` (copy `.env.example`) holds secrets only. Legacy `.agent-platform.env` /
`.env.local` are still read with a deprecation notice; merge them into `.env` and delete
them. `AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS` is deprecated: it is used only while the
registry has no workspaces (then only those roots count, as before) and warned about
otherwise.

Migrating an old layout (idempotent; `.env` is never read or edited by it):
```bash
uv --directory ./mcp-server run agent-platform-agent project-migrate --dry-run
uv --directory ./mcp-server run agent-platform-agent project-migrate
```
It copies the env roots into `workspaces`, registers each `.active-project` line (reusing
existing IDs, new IDs = folder name with `-2` on collision; missing, platform-root and
out-of-workspace lines are skipped), makes the first line the default and renames the
file to `.active-project.migrated`. Then remove the env line yourself.

## Claude Permissions
Claude Code project permissions (workspaces + registered paths outside them) are
generated into ignored local settings:
```bash
python3 scripts/sync_claude_settings.py
```

Do not hardcode personal paths in tracked `.claude/settings.json`.

## Target Project
Every registered project is a target; the registry `default` is `TARGET_PROJECT`.
`root` resolves as registered ID → registered folder name → allowed absolute path;
omitted, the default is used. `project_init` registers the new project and makes it
the default. An unmigrated checkout still reads the first line of `.active-project`.
```bash
uv --directory ./mcp-server run agent-platform-agent gate-check <feature> --root service-b   # ID or folder name
uv --directory ./mcp-server run agent-platform-agent project-add <path | git URL> [--default] [--project-id] [--into]
uv --directory ./mcp-server run agent-platform-agent project-use service-b                   # change the default
uv --directory ./mcp-server run agent-platform-agent project-workspace add|remove|list [<dir>]   # remove 로 마지막 하나를 지울 때 --allow-empty
uv --directory ./mcp-server run agent-platform-agent project-register /abs/service --project-id service-a --verify-profile gradle
```

## Skills
`skills/packages/` is the tracked source. `.claude/skills/<id>` and `.agents/skills/<id>`
are generated (gitignored) by `setup.sh` via `skill sync agent-platform`; graphify is
installed by the graphify tool and stays tracked.
