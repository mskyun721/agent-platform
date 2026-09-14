# Run Event Contract v1

P2 defines dataclasses and validators in `agent_platform_mcp.events`; P4 owns collection, SQLite storage,
deduplication, export and retention. Defining an event does not claim it was collected or persisted.

- event_id/run_id are independent UUID4 values. Feature names and retry counters are not run identities.
- parent_run_id is present only for actual child execution, never equal to run_id.
- task_id is the canonical feature name; timestamps must be UTC. schema_version is currently 1.
- project_id may be null for unregistered contexts; backend/model may be null when not reported.
- skill_versions maps observed skill IDs to package SHA256 hashes. Empty means not supplied, not proof of no skill usage.
- collection_source is wrapper/direct/native_import. completeness is full/partial/unavailable.
- Usage preserves provider source and input/output/cache-read/cache-write fields separately. Unknown is null, not zero.
  Do not sum cache and input counts without provider-specific semantics. Actual cost and price snapshots belong to P4.
- ReviewResult has distinct decision_id/review_cycle_id/review_attempt_id, reviewer_id, role, attempt, decision,
  code_fingerprint, run_id and docs-relative artifact. A CLI exit code is not a review decision.
- Deduplicate retransmitted events by event_id and repeated decisions by decision_id. Do not collapse different roles
  that reviewed the same code. Only that role's approved decision resets its consecutive rejected counter.
- Three consecutive rejections request human intervention; code changes or another role's approval do not reset the count.
- Raw prompts, source and tool outputs are not collected by default. Validators check structure, not secret sanitization;
  P4 collectors must project metadata and mask before storage. No event is stored automatically by this module.

Example: `errors = validate(event)`. An empty error list means structurally valid, not approved, verified, or persisted.

## SQLite Storage

`tools.store.open()` opens `.local/state.db` (or `AGENT_PLATFORM_STATE_DB`) with
schema version 1, foreign keys, five-second lock timeout and transactional writes.
Store objects are context managers. New files use mode 0600. Symlink paths and
unknown future schemas fail closed. Store initialization/I/O errors are reported
as StoreError without raw SQLite diagnostics.

Repeated identical event/decision IDs are no-ops; changed content conflicts.
Run identity cannot change between events. Usage is a snapshot, never an additive
counter; missing fields can be completed but conflicting known counts are refused.
Review attempt collisions cannot overwrite decisions. Role counters follow insertion
order for the same project/task, preserving other roles and code-change history.
Only supported metadata payload keys are accepted; known secret patterns are rejected.
Structural validation cannot guarantee arbitrary caller strings contain no private data.
