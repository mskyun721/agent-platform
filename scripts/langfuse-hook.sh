#!/usr/bin/env bash
# Claude hook — PreToolUse/PostToolUse lifecycle state와 Langfuse span 요약을 관리한다.

set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=/dev/null
. "$SCRIPT_DIR/langfuse-common.sh"

PHASE="${1:-post}"
INPUT=$(cat)

load_langfuse_env
ensure_langfuse_state_dir

SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)
TOOL_NAME=$(printf '%s' "$INPUT" | jq -r '.tool_name // "unknown"' 2>/dev/null)
TOOL_INPUT_JSON=$(printf '%s' "$INPUT" | jq -c '.tool_input // {}' 2>/dev/null || printf '{}')
TRACE_ID=$(trace_id_for_session "$SESSION_ID")
INVOCATION_ID=$(invocation_id_for_input "$SESSION_ID" "$TOOL_NAME" "$TOOL_INPUT_JSON")
STATE_FILE=$(invocation_state_file "$INVOCATION_ID")

if [ "$PHASE" = "pre" ]; then
  START_TIME=$(now_utc_iso)
  SPAN_ID=$(span_id)

  jq -n \
    --arg session_id "$SESSION_ID" \
    --arg trace_id "$TRACE_ID" \
    --arg updated_at "$START_TIME" \
    '{
      session_id: $session_id,
      trace_id: $trace_id,
      updated_at: $updated_at,
      source: "claude-hook"
    }' > "$LANGFUSE_ACTIVE_SESSION_FILE"

  jq -n \
    --arg invocation_id "$INVOCATION_ID" \
    --arg session_id "$SESSION_ID" \
    --arg trace_id "$TRACE_ID" \
    --arg span_id "$SPAN_ID" \
    --arg tool_name "$TOOL_NAME" \
    --arg start_time "$START_TIME" \
    '{
      invocation_id: $invocation_id,
      session_id: $session_id,
      trace_id: $trace_id,
      span_id: $span_id,
      tool_name: $tool_name,
      start_time: $start_time
    }' > "$STATE_FILE"

  echo '{}'
  exit 0
fi

START_TIME=$(read_json_field "$STATE_FILE" '.start_time')
SPAN_ID=$(read_json_field "$STATE_FILE" '.span_id')
STATE_TRACE_ID=$(read_json_field "$STATE_FILE" '.trace_id')
END_TIME=$(now_utc_iso)

if [ -n "$STATE_TRACE_ID" ]; then
  TRACE_ID="$STATE_TRACE_ID"
fi
if [ -z "$SPAN_ID" ]; then
  SPAN_ID=$(span_id)
fi
if [ -z "$START_TIME" ]; then
  START_TIME="$END_TIME"
fi

INPUT_SUMMARY=$(printf '%s' "$INPUT" | jq -c '
  (.tool_input // {}) as $value
  | {
      present: ($value != null),
      value_type: ($value | type),
      top_level_keys: (if ($value | type) == "object" then ($value | keys_unsorted) else [] end),
      size_bytes: ($value | tojson | length)
    }' 2>/dev/null || printf '{"present":false,"value_type":"unknown","top_level_keys":[],"size_bytes":0}')

OUTPUT_SUMMARY=$(printf '%s' "$INPUT" | jq -c '
  (.tool_response // .tool_output // {}) as $value
  | {
      present: ($value != null),
      value_type: ($value | type),
      top_level_keys: (if ($value | type) == "object" then ($value | keys_unsorted) else [] end),
      size_bytes: ($value | tojson | length),
      has_error: (if ($value | type) == "object" then (($value.error? != null) or ($value.errors? != null)) else false end),
      error_type: (
        if ($value | type) == "object" then
          ($value.error.type // $value.error.code // $value.error.message // "")
        else
          ""
        end
      )
    }' 2>/dev/null || printf '{"present":false,"value_type":"unknown","top_level_keys":[],"size_bytes":0,"has_error":false,"error_type":""}')

TOOL_STATUS=$(printf '%s' "$OUTPUT_SUMMARY" | jq -r 'if .has_error then "error" else "success" end' 2>/dev/null || printf 'unknown')
DURATION_MS=$(duration_ms_between "$START_TIME" "$END_TIME")

PAYLOAD=$(jq -n \
  --arg id "$SPAN_ID" \
  --arg trace_id "$TRACE_ID" \
  --arg name "$TOOL_NAME" \
  --arg start_time "$START_TIME" \
  --arg end_time "$END_TIME" \
  --arg session_id "$SESSION_ID" \
  --arg invocation_id "$INVOCATION_ID" \
  --arg tool_status "$TOOL_STATUS" \
  --argjson duration_ms "$DURATION_MS" \
  --argjson input_summary "$INPUT_SUMMARY" \
  --argjson output_summary "$OUTPUT_SUMMARY" \
  '{
    batch: [
      {
        id: $id,
        type: "span-create",
        timestamp: $end_time,
        body: {
          id: $id,
          traceId: $trace_id,
          name: $name,
          startTime: $start_time,
          endTime: $end_time,
          input: $input_summary,
          output: $output_summary,
          metadata: {
            source: "claude-hook",
            session_id: $session_id,
            invocation_id: $invocation_id,
            tool_status: $tool_status,
            duration_ms: $duration_ms
          }
        }
      }
    ]
  }')

PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY:-}"
SECRET_KEY="${LANGFUSE_SECRET_KEY:-}"
HOST="${LANGFUSE_HOST:-http://localhost:3000}"

if [ -n "$PUBLIC_KEY" ] && [ -n "$SECRET_KEY" ]; then
  HTTP_CODE=$(
    curl -sS -o /dev/null -w "%{http_code}" -X POST "$HOST/api/public/ingestion" \
      -H "Content-Type: application/json" \
      -u "$PUBLIC_KEY:$SECRET_KEY" \
      -d "$PAYLOAD" 2>/dev/null
  )
  CURL_EXIT=$?

  if [ "$CURL_EXIT" -ne 0 ] || [ -z "$HTTP_CODE" ] || [ "$HTTP_CODE" -ge 400 ]; then
    echo "[langfuse-hook] WARN: ingestion failed (tool=$TOOL_NAME status=${HTTP_CODE:-curl-error})" >&2
  fi
fi

rm -f "$STATE_FILE" 2>/dev/null || true
echo '{}'
