---
description: MCP 툴로 새 feature 디렉터리와 PRD/TASK 템플릿을 생성하고 Planner 호출
argument-hint: <feature-name>
allowed-tools: mcp__agent-platform__feature_scaffold, mcp__agent-platform__log_append, Read, Write, Edit, Bash(mkdir:*, ls:*, test:*)
---

새 feature `$ARGUMENTS` 를 생성하라.

## 절차 (MCP 우선, 실패 시 파일 기반 fallback)

1. **MCP 툴 호출**: `mcp__agent-platform__feature_scaffold({ name: "$ARGUMENTS" })`
   - 성공 시 `created_files` 리스트를 출력에 사용
   - `FileExistsError` 발생 시 중단하고 사용자에게 알림

2. **Fallback** (MCP 서버 미응답 시에만):
   - `docs/features/$ARGUMENTS/` 디렉터리 생성 (이미 있으면 중단)
   - `templates/PRD.md` → `docs/features/$ARGUMENTS/PRD.md` 복사 후 치환
     - `<feature-name>` → `$ARGUMENTS`
     - `YYYY-MM-DD` → 오늘 날짜
   - `templates/TASK.md` 동일 절차

3. **로그 기록**: `mcp__agent-platform__log_append({ message: "feature scaffolded", agent: "orchestrator", feature: "$ARGUMENTS" })`

4. **결과 출력**:
   ```
   ✅ feature 스캐폴딩 완료
   - docs/features/$ARGUMENTS/PRD.md
   - docs/features/$ARGUMENTS/TASK.md
   다음: @planner 호출하여 PRD 작성 시작
   ```

## 주의
- feature 이름은 `^[a-z][a-z0-9-]{1,63}$` 규칙. MCP 툴이 자동 검증
- 이미 존재하는 디렉터리는 덮어쓰지 않음
