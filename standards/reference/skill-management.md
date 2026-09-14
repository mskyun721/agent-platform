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
agent-platform-agent skill remove api-contract
```

Snapshots and metadata use `skills/packages/<id>` and `skills/registry.json`.
Review and commit these only when intentionally sharing packages with the team.
Project activation state is local. Used, dependent or user-modified snapshots cannot
be removed. Failed copying or registry publication restores the prior state.
Abrupt process termination is not yet a crash-recovery guarantee; unregistered
directories are preserved and reported rather than overwritten.
