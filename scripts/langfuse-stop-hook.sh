#!/usr/bin/env bash
# Stop hook — 세션 trace를 마무리하고 로컬 timing 상태를 정리한다.

set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=/dev/null
. "$SCRIPT_DIR/langfuse-common.sh"

INPUT=$(cat)

load_langfuse_env
ensure_langfuse_state_dir

SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)
ACTIVE_SESSION_ID=$(read_json_field "$LANGFUSE_ACTIVE_SESSION_FILE" '.session_id')
ACTIVE_TRACE_ID=$(read_json_field "$LANGFUSE_ACTIVE_SESSION_FILE" '.trace_id')

if [ -z "$SESSION_ID" ] && [ -n "$ACTIVE_SESSION_ID" ]; then
  SESSION_ID="$ACTIVE_SESSION_ID"
fi

TRACE_ID=$(trace_id_for_session "$SESSION_ID")
if [ -n "$ACTIVE_TRACE_ID" ]; then
  TRACE_ID="$ACTIVE_TRACE_ID"
fi

TIMESTAMP=$(now_utc_iso)

PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY:-}"
SECRET_KEY="${LANGFUSE_SECRET_KEY:-}"
HOST="${LANGFUSE_HOST:-http://localhost:3000}"
TRACE_NAME="${LANGFUSE_TRACE_NAME:-claude-session}"

# LANGFUSE_TAGS: comma-separated → JSON array. default: "agent-platform"
RAW_TAGS="${LANGFUSE_TAGS:-agent-platform}"
TAGS_JSON=$(python3 -c "
import sys, json
tags = [t.strip() for t in sys.argv[1].split(',') if t.strip()]
print(json.dumps(tags))
" "$RAW_TAGS" 2>/dev/null || printf '["agent-platform"]')

if [ -n "$PUBLIC_KEY" ] && [ -n "$SECRET_KEY" ]; then
  PAYLOAD=$(jq -n \
    --arg id "$TRACE_ID" \
    --arg timestamp "$TIMESTAMP" \
    --arg session_id "$SESSION_ID" \
    --arg trace_name "$TRACE_NAME" \
    --argjson tags "$TAGS_JSON" \
    '{
      batch: [
        {
          id: $id,
          type: "trace-create",
          timestamp: $timestamp,
          body: {
            id: $id,
            name: $trace_name,
            tags: $tags,
            metadata: {
              source: "claude-stop-hook",
              session_id: $session_id
            }
          }
        }
      ]
    }')

  HTTP_CODE=$(
    curl -sS -o /dev/null -w "%{http_code}" -X POST "$HOST/api/public/ingestion" \
      -H "Content-Type: application/json" \
      -u "$PUBLIC_KEY:$SECRET_KEY" \
      -d "$PAYLOAD" 2>/dev/null
  )
  CURL_EXIT=$?

  if [ "$CURL_EXIT" -ne 0 ] || [ -z "$HTTP_CODE" ] || [ "$HTTP_CODE" -ge 400 ]; then
    echo "[langfuse-stop] WARN: session trace-create failed (session=$SESSION_ID status=${HTTP_CODE:-curl-error})" >&2
  fi
fi

cleanup_langfuse_state
echo '{}'
