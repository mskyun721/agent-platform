#!/usr/bin/env bash
# PostToolUse hook — Claude Code tool call을 Langfuse span으로 기록한다.
# LANGFUSE_PUBLIC_KEY+SECRET_KEY가 없으면 조용히 종료 (no-op).

INPUT=$(cat)

if [ -f .env.local ]; then
  export $(grep -v '^#' .env.local | xargs) 2>/dev/null || true
fi

PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY:-}"
SECRET_KEY="${LANGFUSE_SECRET_KEY:-}"
HOST="${LANGFUSE_HOST:-http://localhost:3000}"

if [ -z "$PUBLIC_KEY" ] || [ -z "$SECRET_KEY" ]; then
  echo '{}'
  exit 0
fi

SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // "unknown"')
TOOL_INPUT=$(echo "$INPUT" | jq -c '.tool_input // {}' | cut -c1-500)
TOOL_OUTPUT=$(echo "$INPUT" | jq -c '.tool_response // .tool_output // {}' | cut -c1-500)
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# trace ID: 32-char lowercase hex; random fallback when session_id is absent
if [ -n "$SESSION_ID" ]; then
  TRACE_ID=$(echo "$SESSION_ID" | tr -d '-' | tr '[:upper:]' '[:lower:]')
else
  TRACE_ID=$(python3 -c "import os; print(os.urandom(16).hex())" 2>/dev/null \
    || printf '%032x' "$(date +%s)")
fi

# span ID: 16-char lowercase hex (8 random bytes)
SPAN_ID=$(python3 -c "import os; print(os.urandom(8).hex())" 2>/dev/null \
  || uuidgen 2>/dev/null | tr -d '-' | tr '[:upper:]' '[:lower:]' | cut -c1-16 \
  || printf '%016x' "$(date +%s)")

# Langfuse public API uses Basic Auth: public_key (username) + secret_key (password)
curl -sf -X POST "$HOST/api/public/ingestion" \
  -H "Content-Type: application/json" \
  -u "$PUBLIC_KEY:$SECRET_KEY" \
  -d "{
    \"batch\": [{
      \"type\": \"span-create\",
      \"timestamp\": \"$TIMESTAMP\",
      \"body\": {
        \"id\": \"$SPAN_ID\",
        \"traceId\": \"$TRACE_ID\",
        \"name\": \"$TOOL_NAME\",
        \"startTime\": \"$TIMESTAMP\",
        \"input\": $TOOL_INPUT,
        \"output\": $TOOL_OUTPUT
      }
    }]
  }" > /dev/null 2>&1 || echo "[langfuse-hook] WARN: ingestion failed (tool=$TOOL_NAME)" >&2

echo '{}'
