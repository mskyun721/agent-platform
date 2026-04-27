#!/usr/bin/env bash

LANGFUSE_STATE_DIR="${LANGFUSE_STATE_DIR:-.claude/langfuse}"
LANGFUSE_ACTIVE_SESSION_FILE="$LANGFUSE_STATE_DIR/active-session.json"

trim_whitespace() {
  printf '%s' "$1" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

load_langfuse_env() {
  local env_file="${LANGFUSE_ENV_FILE:-.env.local}"
  [ -f "$env_file" ] || return 0

  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in
      ''|'#'*) continue ;;
    esac

    if [ "${line#*=}" = "$line" ]; then
      continue
    fi

    local key="${line%%=*}"
    local value="${line#*=}"

    key="$(trim_whitespace "$key")"
    value="$(printf '%s' "$value" | sed -e 's/^[[:space:]]*//')"

    if [ -z "$key" ]; then
      continue
    fi

    if [ "${value#\"}" != "$value" ] && [ "${value%\"}" != "$value" ]; then
      value="${value#\"}"
      value="${value%\"}"
    elif [ "${value#\'}" != "$value" ] && [ "${value%\'}" != "$value" ]; then
      value="${value#\'}"
      value="${value%\'}"
    fi

    export "$key=$value"
  done < "$env_file"
}

ensure_langfuse_state_dir() {
  mkdir -p "$LANGFUSE_STATE_DIR"
}

now_utc_iso() {
  python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"))' 2>/dev/null \
    || date -u +"%Y-%m-%dT%H:%M:%SZ"
}

random_hex() {
  local bytes="$1"
  python3 -c "import os, sys; print(os.urandom(int(sys.argv[1])).hex())" "$bytes" 2>/dev/null \
    || uuidgen 2>/dev/null | tr -d '-' | tr '[:upper:]' '[:lower:]' | cut -c1-$((bytes * 2)) \
    || printf "%0$((bytes * 2))x" "$(date +%s)"
}

sha256_prefix() {
  local prefix_len="$1"
  python3 -c "import hashlib, sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest()[:int(sys.argv[1])])" "$prefix_len" 2>/dev/null \
    || shasum -a 256 | cut -c1-"$prefix_len"
}

trace_id_for_session() {
  local session_id="$1"
  if [ -z "$session_id" ]; then
    random_hex 16
    return 0
  fi

  local normalized
  normalized="$(printf '%s' "$session_id" | tr -cd '[:alnum:]' | tr '[:upper:]' '[:lower:]')"
  if [ "${#normalized}" -eq 32 ]; then
    printf '%s\n' "$normalized"
    return 0
  fi

  printf '%s' "$session_id" | sha256_prefix 32
  printf '\n'
}

span_id() {
  random_hex 8
}

invocation_id_for_input() {
  local session_id="$1"
  local tool_name="$2"
  local tool_input_json="$3"
  printf '%s' "$session_id|$tool_name|$tool_input_json" | sha256_prefix 24
  printf '\n'
}

invocation_state_file() {
  local invocation_id="$1"
  printf '%s/invocation-%s.json\n' "$LANGFUSE_STATE_DIR" "$invocation_id"
}

read_json_field() {
  local file="$1"
  local query="$2"
  [ -f "$file" ] || return 1
  jq -r "$query // empty" "$file" 2>/dev/null
}

duration_ms_between() {
  local start_time="$1"
  local end_time="$2"
  python3 -c 'from datetime import datetime; import sys
start = datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
end = datetime.fromisoformat(sys.argv[2].replace("Z", "+00:00"))
print(max(0, int((end - start).total_seconds() * 1000)))' "$start_time" "$end_time" 2>/dev/null \
    || printf '0\n'
}

cleanup_langfuse_state() {
  rm -f "$LANGFUSE_ACTIVE_SESSION_FILE" "$LANGFUSE_STATE_DIR"/invocation-*.json 2>/dev/null || true
}
