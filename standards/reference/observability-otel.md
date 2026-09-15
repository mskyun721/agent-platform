# External LLM Observability (OpenTelemetry)

The platform's own store (`.local/state.db`, P4) keeps run/handoff/verification/review
metadata and Codex wrapper usage. Everything below is **outside** the platform: the CLIs
themselves export OpenTelemetry to a collector. Prompt/response bodies stay redacted unless
you opt in per CLI — do not opt in on shared collectors.

Verified 2026-09-15 through `scripts/otel` collector 0.160.0 (Claude Code 2.1.269, codex-cli 0.154.0); no prompt text arrived with content logging off.

## 1. Collector

```bash
cd scripts/otel && docker compose up -d      # otel/opentelemetry-collector-contrib, ports 4317/4318 on 127.0.0.1
# telemetry lands in scripts/otel/otel-data/{metrics,logs,traces}.jsonl (gitignored)
```

`otel-collector-config.yaml` drops `prompt`/`response`/`tool_input`/`tool_parameters`
attributes in the logs/traces pipelines as a second guard. Replace the `file` exporters with
`otlphttp` (Langfuse, Grafana, Datadog …) when a backend exists.

## 2. Claude Code

`source scripts/otel/claude.env` before starting `claude`, or copy the keys into
`~/.claude/settings.json` → `"env"`. Project-level `.claude/settings.json` does **not** apply
`OTEL_*` variables.

What arrives (observed):

| Signal | Name | Key attributes |
|---|---|---|
| metric | `claude_code.session.count` | `start_type` |
| metric | `claude_code.token.usage` | `type` = input/output/cacheRead/cacheCreation, `model`, `query_source` = main/subagent/auxiliary, `agent.name`, `skill.name`, `mcp_tool.name` |
| metric | `claude_code.cost.usage` | same labels, USD estimate at API list price |
| metric | `claude_code.active_time.total`, `lines_of_code.count`, `commit.count`, `pull_request.count`, `code_edit_tool.decision` | |
| event | `user_prompt` | `prompt.id`, `prompt_length` (text only with `OTEL_LOG_USER_PROMPTS=1`) |
| event | `api_request` | `model`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens`, `cost_usd`, `duration_ms`, `request_id` |
| event | `assistant_response`, `api_error`, `tool_result` (`tool_name`, `success`, `duration_ms`, sizes) | correlated by `session.id` + `prompt.id` |
| event | `hook_registered`, `hook_execution_start/complete`, `plugin_loaded` | session bootstrap |
| trace (beta) | `claude_code.interaction` → `llm_request` (TTFT, stop_reason) → `tool` → `tool.execution`; subagent spans nest | needs `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1` |

Note: a one-line `claude -p` produced two `api_request`s — an `auxiliary` haiku call (title
generation) and the `main` call. Sum `query_source=main` when you want the task's own cost.

`claude -p … --output-format json` also returns `usage` and `total_cost_usd` in its JSON without
any OpenTelemetry; `evals/auto.py` already records that path.

## 3. Codex

Append `scripts/otel/codex-otel.toml` to `~/.codex/config.toml` (user config; there is no
per-project OTel file). Interactive sessions export logs (API requests, streamed responses,
user input, tool approvals, tool results), traces and metrics with `service.name=codex-cli`.
`codex exec` (the platform wrapper) is fully covered on 0.154.0 — verified through the collector:
`service.name=codex_exec`; events `codex.conversation_starts`, `codex.user_prompt`, `codex.api_request`,
`codex.sse_event`, `codex.turn_ttft`; metrics `codex.turn.token_usage`, `codex.turn.ttft.duration_ms`,
`codex.turn.e2e_duration_ms`, `codex.turn.tool.call`, `codex.conversation.turn.count` (+ ~50 startup/mcp
internals); spans `codex.exec` → `session_loop` → `run_turn` → `stream_request` with
`gen_ai.usage.input_tokens / cache_read.input_tokens / output_tokens`, `codex.usage.reasoning_output_tokens`.
Pass the `[otel]` config through `~/.codex/config.toml` or `-c otel.…` overrides. The wrapper's `--json`
usage parsing stays the P4 source of truth; OTel is the external, session-level view.

## 4. Joining platform runs to CLI traces

When Claude Code tracing is on, Bash subprocesses inherit `TRACEPARENT`. Every platform run
started from such a session (`state start`, wrappers, `handoff`) stores `trace_id`/`span_id`
in its `run_started` payload (`state runs` shows them). Query the collector by that
`trace_id` to see the prompt, tool calls and token cost around the run.

## 5. Limits

- Cost values are estimates at API list price, not subscription billing. Subscription rate
  limits are not exported.
- Codex `mcp-server` entry point exports nothing (not used by the platform).
- Custom subagent/skill names are anonymised (`custom`, `third-party`) unless
  `OTEL_LOG_TOOL_DETAILS=1`.
- No model-internal reasoning; output quality is P5 evaluation, not observability.
