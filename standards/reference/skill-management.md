# Managed Local Skills

Packages are explicit local imports. Existing plugins, global skills and unmanaged
files are never adopted or deleted automatically. Importing does not run scripts.

Use a native `SKILL.md` with `name` and `description` front-matter, plus a structured
`skill.json` manifest (metadata is separate to preserve native skill compatibility):

```json
{"id":"api-contract","version":"1.0.0","supports":["claude","codex"],"depends_on":[],"requires_tools":[]}
```

`name` must match `id`. Dependencies must already be installed; installing new IDs
with existing-only dependencies prevents cycles. Resources and executable bits are
included in the hash. Hidden files, protected filenames, symlinks and special files
are refused before content import. Limits: 2000 files, 64 MiB total.

```bash
agent-platform-agent skill add /absolute/path/to/package
agent-platform-agent skill list
agent-platform-agent skill enable api-contract my-project
agent-platform-agent skill list --project-id my-project
agent-platform-agent skill disable api-contract my-project
agent-platform-agent skill remove api-contract
```

Snapshots and metadata use `skills/packages/<id>` and `skills/registry.json`.
Review and commit these only when intentionally sharing packages with the team.
Project activation state is local. Used, dependent or user-modified snapshots cannot
be removed. Failed copying or registry publication restores the prior state.
Abrupt process termination is not yet a crash-recovery guarantee; unregistered
directories are preserved and reported rather than overwritten.

## Native Activation

`enable` requires a registered project ID and materializes supported backends into
`.claude/skills/<id>` and `.agents/skills/<id>`. No global configuration is changed.
Native location references checked 2026-09-14: [Claude skills](https://code.claude.com/docs/en/skills),
[Codex skills](https://learn.chatgpt.com/docs/build-skills).

State and ownership hashes live in the local project registry. Enable/disable
roll back file moves/copies when registry publication fails. Missing dependencies,
unmanaged destination collisions, and dependency removal are blocked. Required
tool names are returned as unverified warnings, not granted as permissions.

User-modified copies remain native-discoverable after a disable request. The result
reports `complete: false`, `user_modified`; it never claims effective disablement.
Restore the imported content and marker to permit managed cleanup, or move your
customized copy explicitly. Unregister/rebind are blocked while managed state remains.
Materialization targets the registered path, not every worktree automatically.

`active_versions` reports expected native hashes, not proof of loaded/used skills.
It excludes modified or shadowed copies. Same-ID project and known global/ancestor
directories are detected by presence only. Plugin namespaces and arbitrary native
configuration are not exhaustively inspected: `external_discovery: partial`.
Common AGENTS policy and project allowlists remain active with all skills disabled.
