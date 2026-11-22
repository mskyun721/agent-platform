#!/usr/bin/env bash
# One-shot local setup after `git clone`. Safe to re-run: it never overwrites .env,
# local settings, or skill directories that already exist.
#
#   ./scripts/setup.sh [--roots "<dir>[:<dir>|,<dir>...]"] [--target <path|git-url>]...
#
#   --roots   workspaces (where projects may live), ':' or ',' separated, added to .agent-projects.json
#   --target  project to work on: a local path, or a git URL that is cloned into the first
#             workspace. Registered in .agent-projects.json. Repeatable; the first one
#             becomes the default target.
# Finally an old layout (.active-project, AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS) is migrated.
#   --otel    only: show the OTel settings for ~/.claude/settings.json and ~/.codex/config.toml, apply on confirmation
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
ROOTS=""
TARGETS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --roots)  ROOTS="${2:?--roots needs a value}"; shift 2 ;;
    --target) TARGETS+=("${2:?--target needs a value}"); shift 2 ;;
    --otel)   exec python3 "$ROOT/scripts/otel/user_settings.py" ;;  # user-run; prompts before each change
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "알 수 없는 인자: $1 (--help 참고)"; exit 2 ;;
  esac
done
PLATFORM_ID="agent-platform"
apa() { uv --directory "$ROOT/mcp-server" run --locked agent-platform-agent "$@"; }
step() { printf '\n== %s\n' "$1"; }

step "1/6 필수 도구"
for tool in uv python3 git; do
  command -v "$tool" >/dev/null || { echo "없음: $tool (필수). 설치 후 다시 실행하세요. 예: brew install uv"; exit 1; }
done
for tool in claude codex gemini copilot graphify whodb; do
  command -v "$tool" >/dev/null && echo "  있음  $tool" || echo "  없음  $tool (선택)"
done

step "2/6 .env (연동 토큰 같은 비밀값만)"
created_env=0
if [ ! -f .env ]; then
  cp .env.example .env
  created_env=1
  echo "  .env 를 .env.example 에서 만들었습니다."
else
  echo "  .env 유지"
fi
for legacy in .agent-platform.env .env.local; do
  [ -f "$legacy" ] && echo "  주의: $legacy 는 더 이상 쓰지 않는 이름입니다. 값을 .env 로 옮기고 삭제하세요 (그때까지는 계속 읽습니다)."
done

step "3/6 의존성 (uv sync)"
uv --directory "$ROOT/mcp-server" sync --locked

step "4/6 호스트 설정 생성 (.claude / .gemini / .github)"
python3 scripts/sync_claude_settings.py --agents-only

step "5/6 스킬 설치 (skills/packages → .claude/skills, .agents/skills)"
if ! apa project-list | grep -q "\"project_id\": \"$PLATFORM_ID\""; then
  apa project-register "$ROOT" --project-id "$PLATFORM_ID" >/dev/null
  echo "  플랫폼을 '$PLATFORM_ID' 로 등록했습니다."
fi
apa skill sync "$PLATFORM_ID"

if [ -n "$ROOTS" ]; then
  echo "  workspace 추가 (.agent-projects.json)"
  IFS=':,' read -r -a ROOT_LIST <<< "$ROOTS"
  for dir in "${ROOT_LIST[@]}"; do
    [ -z "$dir" ] && continue
    added="$(apa project-workspace add "$dir")" || { echo "    실패  $dir (존재하는 디렉터리인지 확인)"; exit 1; }
    echo "    추가  $dir"
    # The first add also imports the deprecated env roots; show what came along.
    printf '%s' "$added" | python3 -c 'import json, sys
d = json.load(sys.stdin)
for p in d.get("imported_from_env", []): print("    env 에서 가져옴  " + p)
for p in d.get("rejected_from_env", []): print("    env 값 제외(플랫폼 경로)  " + p)'
  done
fi
if [ ${#TARGETS[@]} -gt 0 ]; then
  echo "  대상 프로젝트 등록 (.agent-projects.json)"
  first=1
  for target in "${TARGETS[@]}"; do
    flag=(); [ "$first" = 1 ] && flag=(--default); first=0
    apa project-add "$target" ${flag[@]+"${flag[@]}"} >/dev/null && echo "    추가  $target" || { echo "    실패  $target (workspace·경로·URL 확인)"; exit 1; }
  done
fi
echo "  이전 설정 이전 (project-migrate, 멱등)"
migration="$(apa project-migrate)"
if printf '%s' "$migration" | grep -q '"notice": "'; then
  echo "  주의: .env 의 AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS 줄을 직접 지우세요 (값은 workspaces 로 옮겼습니다)."
fi
if printf '%s' "$migration" | grep -q '"renamed": \['; then
  echo "  .active-project 를 .active-project.migrated 로 이름을 바꿨습니다 (확인 후 삭제 가능)."
fi

python3 scripts/sync_claude_settings.py  # Claude 권한: workspaces + 등록 경로

step "6/6 진단"
if apa doctor --root "$ROOT" >/dev/null 2>&1; then
  echo "  doctor 통과 (상세: uv --directory mcp-server run agent-platform-agent doctor --root .)"
else
  echo "  doctor 가 문제를 보고했습니다: uv --directory mcp-server run agent-platform-agent doctor --root ."
fi

cat <<EOF

== 완료. 남은 일
EOF
[ "$created_env" = 1 ] && echo "  - 연동(Confluence/Notion/Apidog)을 쓰면 .env 에 토큰을 채우세요 (비밀값만 둡니다)"
if apa project-workspace list | grep -q '"workspaces": \[\]'; then
  echo "  - workspace 가 없습니다: uv --directory mcp-server run agent-platform-agent project-workspace add <내 프로젝트 상위 경로>"
fi
cat <<EOF
  - Codex 를 쓰면 MCP 등록 (한 번):
      codex mcp add agent-platform -- uv --directory "$ROOT/mcp-server" run agent-platform-mcp
  - 대상 프로젝트 지정:
      새 프로젝트    /init-project <name> <pkg>
      기존 프로젝트  uv --directory mcp-server run agent-platform-agent project-add <경로 | git URL> [--default]
                     (git URL 은 첫 workspace 에 clone 후 등록. 기본 타겟 전환은 project-use <ID|폴더명>)
  - 새 세션을 열면 스킬과 설정이 적용됩니다.
EOF
