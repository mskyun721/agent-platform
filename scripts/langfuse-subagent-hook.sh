#!/usr/bin/env bash
# SubagentStart / SubagentStop hook
# SubagentStart: 부모 세션의 trace에 agent 실행 span을 시작한다.
# SubagentStop:  span을 닫고 Langfuse에 전송한다.

set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=/dev/null
. "$SCRIPT_DIR/langfuse-common.sh"

PHASE="${1:-start}"
INPUT=$(cat)

load_langfuse_env
ensure_langfuse_state_dir

# SubagentStart/Stop stdin 필드 추출
SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)
# subagent_id 또는 task_id로 식별 (Claude Code 버전에 따라 다를 수 있음)
SUBAGENT_ID=$(printf '%s' "$INPUT" | jq -r '.subagent_id // .task_id // empty' 2>/dev/null)
SUBAGENT_NAME=$(printf '%s' "$INPUT" | jq -r '.name // .subagent_type // .description // "unknown-agent"' 2>/dev/null | cut -c1-80)

# 상태 파일: subagent_id 또는 session_id+name 조합으로 식별
if [ -n "$SUBAGENT_ID" ]; then
  STATE_KEY=$(printf '%s' "$SUBAGENT_ID" | sha256_prefix 24)
else
  STATE_KEY=$(printf '%s|%s' "$SESSION_ID" "$SUBAGENT_NAME" | sha256_prefix 24)
fi
STATE_FILE="$LANGFUSE_STATE_DIR/subagent-$STATE_KEY.json"

TRACE_ID=$(trace_id_for_session "$SESSION_ID")
# 기존 active session trace_id가 있으면 우선 사용 (부모 trace에 연결)
ACTIVE_TRACE_ID=$(read_json_field "$LANGFUSE_ACTIVE_SESSION_FILE" '.trace_id')
if [ -n "$ACTIVE_TRACE_ID" ]; then
  TRACE_ID="$ACTIVE_TRACE_ID"
fi

PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY:-}"
SECRET_KEY="${LANGFUSE_SECRET_KEY:-}"
HOST="${LANGFUSE_HOST:-http://localhost:3000}"

if [ "$PHASE" = "start" ]; then
  START_TIME=$(now_utc_iso)
  SPAN_ID=$(span_id)

  jq -n \
    --arg session_id "$SESSION_ID" \
    --arg subagent_id "$SUBAGENT_ID" \
    --arg subagent_name "$SUBAGENT_NAME" \
    --arg trace_id "$TRACE_ID" \
    --arg span_id "$SPAN_ID" \
    --arg start_time "$START_TIME" \
    '{
      session_id: $session_id,
      subagent_id: $subagent_id,
      subagent_name: $subagent_name,
      trace_id: $trace_id,
      span_id: $span_id,
      start_time: $start_time
    }' > "$STATE_FILE"

  if [ -n "$PUBLIC_KEY" ] && [ -n "$SECRET_KEY" ]; then
    PAYLOAD=$(jq -n \
      --arg span_id "$SPAN_ID" \
      --arg trace_id "$TRACE_ID" \
      --arg name "agent:$SUBAGENT_NAME" \
      --arg start_time "$START_TIME" \
      --arg session_id "$SESSION_ID" \
      --arg subagent_id "$SUBAGENT_ID" \
      '{
        batch: [{
          id: $span_id,
          type: "span-create",
          timestamp: $start_time,
          body: {
            id: $span_id,
            traceId: $trace_id,
            name: $name,
            startTime: $start_time,
            metadata: {
              source: "subagent-start-hook",
              session_id: $session_id,
              subagent_id: $subagent_id,
              subagent_name: $name
            }
          }
        }]
      }')

    curl -sS -o /dev/null -X POST "$HOST/api/public/ingestion" \
      -H "Content-Type: application/json" \
      -u "$PUBLIC_KEY:$SECRET_KEY" \
      -d "$PAYLOAD" 2>/dev/null || true
  fi

  echo '{}'
  exit 0
fi

# PHASE = stop
SPAN_ID=$(read_json_field "$STATE_FILE" '.span_id')
START_TIME=$(read_json_field "$STATE_FILE" '.start_time')
STATE_TRACE_ID=$(read_json_field "$STATE_FILE" '.trace_id')
STORED_NAME=$(read_json_field "$STATE_FILE" '.subagent_name')
END_TIME=$(now_utc_iso)

[ -n "$STATE_TRACE_ID" ] && TRACE_ID="$STATE_TRACE_ID"
[ -z "$SPAN_ID" ] && SPAN_ID=$(span_id)
[ -z "$START_TIME" ] && START_TIME="$END_TIME"
[ -n "$STORED_NAME" ] && SUBAGENT_NAME="$STORED_NAME"

DURATION_MS=$(duration_ms_between "$START_TIME" "$END_TIME")

# 종료 결과 추출 (있는 경우)
EXIT_CODE=$(printf '%s' "$INPUT" | jq -r '.exit_code // .status // "unknown"' 2>/dev/null)

if [ -n "$PUBLIC_KEY" ] && [ -n "$SECRET_KEY" ]; then
  PAYLOAD=$(jq -n \
    --arg span_id "$SPAN_ID" \
    --arg trace_id "$TRACE_ID" \
    --arg name "agent:$SUBAGENT_NAME" \
    --arg start_time "$START_TIME" \
    --arg end_time "$END_TIME" \
    --arg session_id "$SESSION_ID" \
    --arg exit_code "$EXIT_CODE" \
    --argjson duration_ms "$DURATION_MS" \
    '{
      batch: [{
        id: $span_id,
        type: "span-create",
        timestamp: $end_time,
        body: {
          id: $span_id,
          traceId: $trace_id,
          name: $name,
          startTime: $start_time,
          endTime: $end_time,
          metadata: {
            source: "subagent-stop-hook",
            session_id: $session_id,
            exit_code: $exit_code,
            duration_ms: $duration_ms
          }
        }
      }]
    }')

  HTTP_CODE=$(
    curl -sS -o /dev/null -w "%{http_code}" -X POST "$HOST/api/public/ingestion" \
      -H "Content-Type: application/json" \
      -u "$PUBLIC_KEY:$SECRET_KEY" \
      -d "$PAYLOAD" 2>/dev/null
  )

  if [ -n "$HTTP_CODE" ] && [ "$HTTP_CODE" -ge 400 ]; then
    echo "[langfuse-subagent] WARN: span-update failed (agent=$SUBAGENT_NAME status=$HTTP_CODE)" >&2
  fi
fi

rm -f "$STATE_FILE" 2>/dev/null || true
echo '{}'
