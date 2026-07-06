---
description: MCP 툴로 새 feature 디렉터리와 PRD/TASK 템플릿을 생성하고 Planner 호출
argument-hint: <feature-name>|<type>/<feature-name>
allowed-tools:
  - mcp__agent-platform__feature_scaffold
  - Read
  - Write
  - Edit
  - Bash(mkdir:*)
  - Bash(ls:*)
  - Bash(test:*)
---

새 feature `$ARGUMENTS` 를 생성하라.

## 사전 단계 (선택)
설계가 불확실하거나 복잡한 기능이면 PRD 작성 전 `/superpowers:brainstorm` 실행을 권장한다.
브레인스토밍 결과를 PRD 요구사항·AC 작성 시 컨텍스트로 활용한다.

## 절차 (MCP 우선, 실패 시 파일 기반 fallback)

`$ARGUMENTS`에 `/`가 포함되면 (`<type>/<name>`, 예: `fix/login-bug`) `{TARGET_PROJECT}/docs/<type>/<name>/`,
포함되지 않으면 `{TARGET_PROJECT}/docs/features/$ARGUMENTS/` 에 생성한다 (CLAUDE.md `docs/<type>/<name>/` 규칙).
아래 `<dir>` 은 이 경로를 가리킨다.

1. **MCP 툴 호출**: `mcp__agent-platform__feature_scaffold({ name: "$ARGUMENTS" })`
   - 성공 시 `created_files` 리스트를 출력에 사용 (`<dir>/...`)
   - `FileExistsError` 발생 시 중단하고 사용자에게 알림

2. **Fallback** (MCP 서버 미응답 시에만):
   - 먼저 `agent-platform/.active-project` 를 읽어 `TARGET_PROJECT` 절대 경로를 확인한다
   - `.active-project` 가 없거나 경로가 유효하지 않으면 중단하고 `/init-project` 또는 타겟 프로젝트 설정을 안내한다
   - `<dir>/` 디렉터리 생성 (이미 있으면 중단)
   - `templates/PRD.md` → `<dir>/PRD.md` 복사 후 치환
     - `<feature-name>` → `$ARGUMENTS`
     - `YYYY-MM-DD` → 오늘 날짜
   - `templates/TASK.md` 동일 절차

3. **결과 출력**:
   ```
   ✅ feature 스캐폴딩 완료
   - <dir>/PRD.md
   - <dir>/TASK.md
   다음: @planner 호출하여 PRD 작성 시작
   ```

## 주의
- feature 이름은 `^[a-z][a-z0-9-]{1,63}(?:/[a-z][a-z0-9-]{1,63})*$` 규칙. MCP 툴이 자동 검증
- 이미 존재하는 디렉터리는 덮어쓰지 않음
- `agent-platform/docs/` 에 직접 생성하지 않음
