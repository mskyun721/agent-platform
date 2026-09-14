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

## Pricing and Retention

Optional manual `.agent-config.json` pricing configuration (illustrative fixture rates,
not actual provider prices):

```json
{"pricing":{"price_id":"my-reviewed-rates","currency":"USD","as_of":"2026-09-14","models":{
  "exact-model-id":{"input_per_mtok":"2","output_per_mtok":"4","cache_read_per_mtok":"0.5",
                    "cache_write_per_mtok":"1","input_includes_cache":true}
}}}
```

Set cache semantics explicitly. Inclusive input subtracts the separately priced
cache fields; cache is never blindly added to total input. All needed counts/rates
must be known for an estimate. Decimal rates and source date/ID/currency/model are
stored in the run-start snapshot; configuration changes cannot rewrite old estimates.
`usage_summary(scenario=...)` explicitly recalculates a separate scenario. Mixed
currencies are not summed. Actual reported cost remains null when not collected.

CLI `state usage`, `state export --out new.json`, `state import export.json`, and
`state prune --before <UTC timestamp>` operate on this one SQLite store. Exports
are structured JSON snapshots, not a second JSONL event journal. Imports are
idempotent replay, not an all-or-nothing transaction; retry a stopped import with
the same IDs. Finished unreferenced runs older than the cutoff are pruned; active
runs and review-linked runs/history remain to preserve counters and audit identity.
Default explicit prune cutoff is 180 days; no background deletion occurs.

## Codex Native Usage

CLI 0.154.0 live JSON probe (2026-09-14) returned one turn.completed usage object
with input_tokens=15557, cached_input_tokens=12160, cache_write_input_tokens=0,
output_tokens=5, reasoning_output_tokens=0. The collector maps the first four
fields, without adding cached or reasoning tokens again. These are probe values,
not estimates of normal task cost. Native source identity includes thread ID and
the single observed turn; a repeated source cannot be attributed to another run.
Multiple completed turns, malformed streams, missing thread identity or invalid
counts remain unavailable rather than being guessed or blindly summed. Resume
telemetry needs a separate source-event adapter; this parser handles fresh exec only.
