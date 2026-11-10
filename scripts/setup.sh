#!/usr/bin/env bash
# One-shot local setup after `git clone`. Safe to re-run: it never overwrites .env,
# local settings, or skill directories that already exist.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
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
else
  echo "  .env 유지"
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
      기존 프로젝트  .active-project 에 절대경로를 한 줄씩 (첫 줄이 기본 타겟)
                     기본 전환: uv --directory mcp-server run agent-platform-agent project-use <폴더명>
  - 새 세션을 열면 스킬과 설정이 적용됩니다.
EOF
