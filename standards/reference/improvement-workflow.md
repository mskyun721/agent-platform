# Evidence-backed instruction improvements

Use `uv --directory mcp-server run agent-platform-agent` from the platform checkout
(the examples abbreviate this to `apa`). Every operation requires explicit `--root`.
This is a local operator workflow, not an automatic learning daemon.

1. Record selected feedback with `feedback add` and retain its ID.
2. Propose a complete, reviewable replacement:

```bash
apa improvement propose --root "$PWD" --feedback FEEDBACK_ID < candidate.json
apa improvement list --root "$PWD"
apa improvement show CANDIDATE_ID --root "$PWD"
```

`candidate.json` contains exactly `trigger`, `action`, `target`, `replacement`.
Target is an existing direct Markdown file under `standards/agents/` or
`standards/reference/`; replacement is its full new text. Trigger/action each have
2,000-byte limits; replacement is at most 64 KiB. Suspected secret patterns,
symlinks, unchanged replacements, missing feedback and mismatched workspaces are
rejected. Structured JSON input avoids shell interpolation of instruction text.

3. Run matched baseline/candidate trials using explicit available model IDs:

```bash
uv --directory mcp-server run --locked --dev python ../evals/run_task.py auto \
  --task observation-scope --ai claude --model MODEL_ID --repeat 3 --max-minutes 10 \
  --improvement-id CANDIDATE_ID --improvement-root "$PWD" --improvement-variant baseline
```

Repeat with `--improvement-variant candidate`, then both variants with `--ai codex`
and that backend's model ID. Run from the platform root; `uv --directory` changes
Python's working directory to mcp-server. The time limit is for the whole group,
not each trial. Model usage is billable according to the user's CLI account.
The observation fixture checks current session capture, historical-only records,
mixed workspaces, excluded projects, unchanged logs and a stale collector.

The runner appends the selected baseline/candidate instruction text to the fixture
prompt, retaining platform policy and fixture restrictions. It does not replace
all production instructions or evaluate the live collector. Thus this is a
controlled instruction smoke test, not proof of production behavior or improved
quality. Choose additional relevant tasks before approving a real change.

4. Compare the resulting run UUIDs, inspect the diff and record a review:

```bash
apa improvement evaluate CANDIDATE_ID --root "$PWD" --baseline BASELINE_RUN_IDS --candidate CANDIDATE_RUN_IDS
apa improvement show CANDIDATE_ID --root "$PWD"
apa improvement review CANDIDATE_ID --root "$PWD" --decision approved --reviewer REVIEWER
apa improvement apply CANDIDATE_ID --root "$PWD" --dry-run
apa improvement apply CANDIDATE_ID --root "$PWD"
apa improvement revert CANDIDATE_ID --root "$PWD" --dry-run
apa improvement revert CANDIDATE_ID --root "$PWD"
```

Each run-ID argument accepts multiple UUIDs. Comparison requires checked local
results, both backends, at least three independent runs per condition and variant,
matching task/judge hash, model, CLI version, instruction mode, Python version,
platform fingerprint and group budget. Results bind candidate/content hashes and
are hashed again at review/apply. Every candidate trial must pass with zero human
interventions. Missing conditions and incomparable groups are rejected. Failed or
invalid re-evaluation clears earlier approval. Passing is eligibility for review,
not automatic approval. Three runs do not establish statistical superiority.
Local result files and reviewer names are not authenticated attestations.

The normal lifecycle is draft → evaluated → approved → applied → reverted;
rejection is explicit. `show` reports stale content/targets; `list` returns stored
metadata status, without revalidating it. Review and apply revalidate live evidence,
results and target content. Expired or purged source feedback blocks new approval
or application but does not silently undo applied rules.

Application is restricted to this platform checkout. Registered external roots can
hold candidates/evaluations, but cannot apply/revert through this command. Existing
agent adapters must match the canonical source; both versions are saved and updated
together while preserving adapter frontmatter. Apply is one atomic replacement per
file, not a transaction spanning files and databases. `applying`/`reverting` journal
states permit explicit retry; an interrupted apply can also be reverted. Unrelated
file edits block retries and rollback. The platform lock serializes platform
operations, not arbitrary editors; avoid simultaneous manual edits during apply.

State schema 7 stores hashes, review/evaluation references and lifecycle metadata.
Instruction text and before/after snapshots are in adjacent 0600 `learning.db`,
excluded from observation exports. Unapplied candidates expire after 30 days and
are removed on candidate-content access; metadata remains. Applied, reverted and
pending operation snapshots remain for recovery and do not automatically expire.
Feedback purge does not delete these candidate snapshots. No automatic Git commit,
push, global rule generation or permission changes are performed.

Claude `/improve` provides a thin command entrypoint. Codex uses this same CLI.
Native command discovery is separate from Python CLI test coverage.

## Initial live smoke evidence (2026-09-25)

The first observation-scope experiment ran 12 trials: Codex baseline/candidate each
3/3 passed; Claude baseline/candidate each 2/3 passed, with the last trial exceeding
the shared 180-second group budget. The platform also changed during the first
group, so comparison rejected mismatched fingerprints. No candidate was approved
or applied. This is execution evidence, not a valid improvement comparison. Freeze
the checkout and allocate a sufficient budget before the next matched experiment.
