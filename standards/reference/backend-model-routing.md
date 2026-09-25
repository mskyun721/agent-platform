# Backend and model routing

A role wrapper can run Claude Code or Codex independently for each invocation.
This does not change the model/backend of an already running native session.
Use direct same-AI roles normally; wrappers are explicit delegated operations.

```bash
# Selection only: no model call, writes or automatic fallback
uv --directory mcp-server run agent-platform-agent route planner --root "$PWD"
uv --directory mcp-server run agent-platform-agent route reviewer --ai claude --model sonnet --root "$PWD"
# Explicit task execution (feature artifacts must already exist)
uv --directory mcp-server run agent-platform-agent run backend FEATURE --ai codex --model YOUR_CODEX_MODEL --root "$PWD" --dry-run
uv --directory mcp-server run agent-platform-agent run reviewer FEATURE --ai claude --model sonnet --root "$PWD" --dry-run
```

Remove `--dry-run` only when intending to invoke that backend. `--ai auto` is now
the standalone default. MCP role run tools use `cli` and optional `model`.
An `[AI: ...]` instruction must be passed by the calling agent as explicit `cli`;
raw requirement text is not scanned for routing tags.

Selection order:
- CLI: explicit → project role → common role → preferred_cli (legacy default Codex).
- Model for that CLI: explicit → project role models → common role models →
  cli_models → claude_models[role] for Claude → CLI default.
- allowed_cli/allowed_models apply to every selection, including explicit overrides.
  A model allowlist requires a selected model; an unknown CLI default cannot bypass it.

Trusted policy lives only in the platform `.agent-config.json`. Project entries are
keyed by registered project ID or resolved absolute workspace path, with ID priority.
They do not modify active-project and are not read from arbitrary target configuration.
Malformed policy fails closed. This is wrapper policy, not enforcement over standalone
native sessions or a replacement for company-level vendor access controls.

Example configuration (replace model IDs with models available to your account):

```json
{
  "preferred_cli": "codex",
  "cli_models": {},
  "routing": {
    "allowed_cli": ["claude", "codex"],
    "allowed_models": {},
    "roles": {
      "planner": {"cli": "claude", "models": {"claude": "sonnet"}},
      "backend": {"cli": "codex"},
      "reviewer": {"cli": "claude"},
      "qa": {"cli": "claude", "models": {"claude": "haiku"}}
    },
    "projects": {
      "my-stock": {"reviewer": {"cli": "codex", "models": {"codex": "YOUR_CODEX_MODEL"}}}
    }
  }
}
```

These role choices are examples, not benchmark recommendations. Installed defaults
keep empty role/project routes and preserve preferred_cli. Claude native subagent
frontmatter remains controlled exclusively by claude_models; routing.models changes
wrapper invocations only. No automatic model ranking, difficulty classification,
retry, failover or cost-budget enforcement is included in this version.

The selection response and run_started metadata include requested CLI/model,
selection sources, configuration hash and runtime_model_status=unverified. A requested
model/alias is not proof of the exact model used by the provider. Run detail displays
selection reasons. No full prompt or config contents are copied into selection metadata.

Claude uses `-p --output-format json --permission-mode dontAsk --strict-mcp-config`,
explicit tools and no permission bypass. Coding roles expose Read/Glob/Grep/Edit/Write/Bash;
only file operations are additionally allowed, while Bash still requires existing CLI
permission rules. A denied command must be reported as unverified work, not retried with
weaker permissions. Research roles expose only Read/Glob/Grep/WebSearch/WebFetch; no
shell, write or delegation tools. Codex retains workspace-write or research read-only
sandbox. These are different permission systems, not equivalent OS sandboxes. Existing
Claude hooks/settings may still execute; the wrapper is for trusted project workspaces.

Claude JSON result errors/malformed output mark the process failed even with exit code
zero. Available usage is projected; missing token fields stay unknown. Authentication,
model availability, native lifecycle and actual task quality require real CLI evaluation;
unit/dry-run tests do not establish them. No paid calls are needed for route preview.

Flags were checked against installed `claude --help` and the
[official CLI reference](https://code.claude.com/docs/en/cli-reference).
