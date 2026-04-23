#!/usr/bin/env bash
# Stop hook — 세션 종료 시 Langfuse에 claude-session trace를 생성한다.
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
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# trace ID: 32-char lowercase hex; random fallback when session_id is absent
if [ -n "$SESSION_ID" ]; then
  TRACE_ID=$(echo "$SESSION_ID" | tr -d '-' | tr '[:upper:]' '[:lower:]')
else
  TRACE_ID=$(python3 -c "import os; print(os.urandom(16).hex())" 2>/dev/null \
    || printf '%032x' "$(date +%s)")
fi

curl -sf -X POST "$HOST/api/public/ingestion" \
  -H "Content-Type: application/json" \
  -u "$PUBLIC_KEY:$SECRET_KEY" \
  -d "{\"batch\":[{\"type\":\"trace-create\",\"timestamp\":\"$TIMESTAMP\",\"body\":{\"id\":\"$TRACE_ID\",\"name\":\"claude-session\",\"tags\":[\"agent-platform\"]}}]}" \
  > /dev/null 2>&1 || echo "[langfuse-stop] WARN: session trace-create failed (session=$SESSION_ID)" >&2

echo '{}'
