# Feedback and observation diagnostics

Run commands from the platform checkout with `uv --directory mcp-server run agent-platform-agent`.

- `doctor --root ROOT`: CLI version availability, project hook configuration and observation status. It never executes configured hook commands. Runtime hook status remains unknown until independently observed. CLI --version is a bounded probe.
- `observe status --root ROOT`: capture setting, collector heartbeat and per-backend latest stored turn/session. Heartbeats older than 30 seconds are stale. A fresh heartbeat proves polling, not capture of a particular active session. This creates/opens local DBs but does not scan transcripts.
- `feedback add --root ROOT --source-kind manual --kind correction`: read `{"summary":"..."}` from stdin, return feedback metadata and text. Nonmanual source kinds platform_run/native_turn require --source-id and a matching existing workspace. Imported state references are local availability checks, not independently trusted evidence.
- `feedback list --root ROOT`: newest 100 metadata records, no text.
- `feedback show ID --root ROOT`: selected text plus evidence availability.
- `feedback purge --root ROOT`: remove metadata and text only for that workspace; does not change rules or original CLI logs.

Kind is correction/failure/suggestion. Summary must be 1..2000 characters and is masked for known secret patterns. Identical workspace/source/kind/masked-summary inputs return the same ID; different corrections on one run remain separate. Explicit re-add after expiry can store the selected summary again.

State DB schema 6 adds metadata-only feedback; schema 7 adds improvement metadata (see [workflow](improvement-workflow.md)). Existing state export remains schema 5 and excludes feedback (metadata and text); observation import does not activate or recreate learning. Full DB backup is needed to preserve feedback metadata. Summary text is in adjacent learning.db, 0600, secure_delete, 30-day TTL cleaned on access. Metadata does not expire automatically. Source transcript expiry leaves feedback text subject to its own TTL and evidence_status=unavailable.

Metadata and text use separate transactions. A failed text write leaves content_status=missing; explicit retry repairs it. During purge the metadata write lock serializes changes; failure is reported and is never called a successful purge. Purge must be retried after a storage error. No raw prompt/tool output is copied. Pattern masking is not a guarantee of removal of all personal data.

The collector persists its last poll in the content DB while observe serve runs. Restart an older running viewer after updating the platform, particularly when state schema changes. Errors writing health are exposed in the live API; persisted health eventually becomes stale.

Claude project hooks use scripts/hooks/platform_hook.py with bounded JSON input and a 10-second configured timeout. SessionStart synchronizes agent adapters only; it no longer reads environment files to synchronize local permission settings. Explicit setup retains its existing configuration procedures. Hook warnings do not count as test/approval evidence. Destructive-command matching is a limited guard, not a shell parser or sandbox. Codex hook configuration is unchanged and doctor reports its runtime as unknown.
