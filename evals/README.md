# Local Evaluation Fixtures

Three small P0 smoke tasks preserve repeatable starting conditions. They do
not measure real backend project quality or establish model superiority.
P5 adds broader tasks and repeated comparisons.

| Task | Required change | Evaluator checks |
|---|---|---|
| small-feature | multiply implementation and test | signed/zero behavior, required tests, mutation detection |
| seeded-bug | subtract implementation | behavior, unchanged original tests |
| broken-test | incorrect test expectation | unchanged implementation, required tests, mutation detection |
| api-add | divide + zero-denominator tests | arithmetic, mutation checks, actual loopback HTTP success/error responses |
| skill-remove | safe removal procedure | real managed activation/removal guards and preservation of generated product files |

## Prepare And Check

From the platform checkout, prepare an empty workspace outside this repository:

```bash
uv --directory mcp-server run python ../evals/run_task.py setup --task seeded-bug --workspace /tmp/platform-eval-example --ai codex --model MODEL --cli-version VERSION --instructions task-only
```

Use the returned workspace and task instructions in a fresh AI session.
Use a different workspace per run. Record the actual model/CLI version when
known; omitted values stay null. `--instructions` distinguishes a task-only
CLI run from a run with platform instructions. This runner does not launch
AI processes or claim to enforce their sandbox.

After the session, use the returned run_id:

```bash
uv --directory mcp-server run python ../evals/run_task.py check --run-id RUN_ID --human-interventions 0 --note "No intervention"
uv --directory mcp-server run python ../evals/run_task.py record-skip --task seeded-bug --ai claude --reason "Not executed"
```

State and results are in ignored `evals/results/`, outside the edited workspace.
Original immutable fixture/overlay hashes determine unchanged files. A forged
workspace `.eval-start.json` is never consulted. The judge reads current source
instead of cached bytecode, checks arithmetic behavior and verifies tests detect
incorrect functions. The fixture uses direct test functions; general pytest
fixtures/decorators are outside this tiny task contract.

The judge is not a security sandbox for hostile code. Run AI work and judging
with the existing local execution restrictions; no real service credentials,
network dependencies, deployment, or external project writes are needed.
Raw subprocess output is not stored. Runtime and model metadata may be missing
and is never converted into zero usage. `session_wall_sec` includes human idle
time; it is not pure model latency. Rechecking the same run updates its result;
create another run for an independent trial.

## Bounded Automation

```bash
uv --directory mcp-server run python ../evals/run_task.py auto --task api-add --ai codex --repeat 3 --max-minutes 5
uv --directory mcp-server run python ../evals/run_task.py auto --task skill-remove --ai claude --repeat 3 --max-minutes 5
uv --directory mcp-server run python ../evals/summarize.py
uv --directory mcp-server run python ../evals/summarize.py --regress --baseline evals/baseline.json
```

Automation is explicitly requested, never part of normal pytest. Each repeat uses
an isolated temporary workspace; only local fixture source is editable. Platform
mode materializes canonical policy and role text with a fixture-only override.
AI processes have a total per-command budget, process-group termination on timeout,
no remote-action approval bypass, and no delegation request. Native CLI settings can
still affect the model or available global skills; those versions are unavailable
unless explicitly recorded. Test criteria stay outside the AI workspace.

Judge version 2 adds real local HTTP integration (including invalid/missing/nonfinite
input and zero denominator) and real skill-manager lifecycle checks. Its OpenAPI 3
YAML and flowchart are evaluator-owned contracts under tasks/api-add, hashed with
the judge/task. The HTTP adapter is evaluator-owned, not a production service server.

AI output is transient; records contain numeric usage/status/identities and missingness,
not raw conversation text. P4 observation run IDs correlate the evaluation with SQLite
usage and price snapshots. A missing model/rate yields unknown cost. CLI and judge
failure remain distinct. Compare only compatible task hashes/instruction modes; small
samples are explicitly marked, and no model-superiority claim is generated.

`direct_observation_smoke.py` is a separate explicit Claude walkthrough of state
start, owning review decision and state end. It registers only a temporary project,
uses a temporary DB, leaves source unchanged and unregisters its own identity afterward.

Results retain task/judge hashes, platform revision and source fingerprint,
dirty state, instruction mode, Python version, timestamps and human count.
Only selected source files are covered by the platform fingerprint; environment
changes require separately recorded CLI/model versions. A prepared or skipped
run is not a successful AI run. Before/after comparisons must use the same
fixture and instruction mode.
