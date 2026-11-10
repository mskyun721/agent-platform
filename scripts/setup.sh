#!/usr/bin/env bash
# One-shot local setup after `git clone`. Safe to re-run: it never overwrites .env,
# local settings, or skill directories that already exist.
#
#   ./scripts/setup.sh [--roots "<dir>[:<dir>...]"] [--target <path|git-url>]...
#
#   --roots   allowed project roots, written to a NEW .env only (an existing .env is never edited)
#   --target  project to work on: a local path, or a git URL that is cloned into the first
#             allowed root. Repeatable; the first one becomes the default target.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
ROOTS=""
TARGETS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --roots)  ROOTS="${2:?--roots needs a value}"; shift 2 ;;
    --target) TARGETS+=("${2:?--target needs a value}"); shift 2 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
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

step "2/6 .env"
created_env=0
if [ ! -f .env ]; then
  cp .env.example .env
  created_env=1
  echo "  .env 를 .env.example 에서 만들었습니다."
  if [ -n "$ROOTS" ]; then
    ROOTS="$ROOTS" python3 - <<'PY'
import os, re
from pathlib import Path
roots = os.pathsep.join(str(Path(p).expanduser().resolve()) for p in os.environ["ROOTS"].split(os.pathsep) if p)
path = Path(".env")
text, count = re.subn(r'(?m)^AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS=.*$',
                      lambda _: f'AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS="{roots}"', path.read_text(encoding="utf-8"))
assert count == 1, ".env.example must define AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS once"
path.write_text(text, encoding="utf-8")
PY
    created_env=2
    echo "  허용 범위를 --roots 값으로 기록했습니다."
  fi
else
  echo "  .env 유지"
  [ -n "$ROOTS" ] && echo "  주의: .env 가 이미 있어 --roots 는 적용하지 않았습니다. 직접 수정하세요."
fi
for legacy in .agent-platform.env .env.local; do
  [ -f "$legacy" ] && echo "  주의: $legacy 는 더 이상 쓰지 않는 이름입니다. 값을 .env 로 옮기고 삭제하세요 (그때까지는 계속 읽습니다)."
done

step "3/6 의존성 (uv sync)"
uv --directory "$ROOT/mcp-server" sync --locked

step "4/6 호스트 설정 생성 (.claude / .gemini / .github)"
python3 scripts/sync_claude_settings.py
python3 scripts/sync_claude_settings.py --agents-only

step "5/6 스킬 설치 (skills/packages → .claude/skills, .agents/skills)"
if ! apa project-list | grep -q "\"project_id\": \"$PLATFORM_ID\""; then
  apa project-register "$ROOT" --project-id "$PLATFORM_ID" >/dev/null
  echo "  플랫폼을 '$PLATFORM_ID' 로 등록했습니다."
fi
apa skill sync "$PLATFORM_ID"

if [ ${#TARGETS[@]} -gt 0 ]; then
  echo "  대상 프로젝트 추가 (.active-project)"
  for target in "${TARGETS[@]}"; do
    apa project-add "$target" >/dev/null && echo "    추가  $target" || { echo "    실패  $target (허용 범위·경로·URL 확인)"; exit 1; }
  done
fi

step "6/6 진단"
if apa doctor --root "$ROOT" >/dev/null 2>&1; then
  echo "  doctor 통과 (상세: uv --directory mcp-server run agent-platform-agent doctor --root .)"
else
  echo "  doctor 가 문제를 보고했습니다: uv --directory mcp-server run agent-platform-agent doctor --root ."
fi

cat <<EOF

== 완료. 남은 일
EOF
[ "$created_env" = 1 ] && echo "  - .env 의 AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS 를 내 프로젝트 상위 경로로 바꾸고 이 스크립트를 다시 실행 (Claude 권한 반영)"
cat <<EOF
  - Codex 를 쓰면 MCP 등록 (한 번):
      codex mcp add agent-platform -- uv --directory "$ROOT/mcp-server" run agent-platform-mcp
  - 대상 프로젝트 지정:
      새 프로젝트    /init-project <name> <pkg>
      기존 프로젝트  uv --directory mcp-server run agent-platform-agent project-add <경로 | git URL>
                     (git URL 은 허용 범위 안에 clone. 첫 줄이 기본 타겟, 전환은 project-use <폴더명>)
  - 새 세션을 열면 스킬과 설정이 적용됩니다.
EOF
