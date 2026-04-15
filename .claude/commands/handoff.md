---
description: MCP 툴로 Quality Gate 검증 후 다음 Agent로 handoff
argument-hint: <next-agent> <feature-name>
allowed-tools:
  - mcp__agent-platform__handoff_validate
  - mcp__agent-platform__log_append
  - Read
  - Glob
  - Grep
---

`$2` feature 를 `$1` Agent 에게 handoff 하라.

## 절차

### 1. 이전 Agent 추론
`$1` (다음 Agent) 로부터 역산:
- `$1 = backend` → from = planner
- `$1 = reviewer` or `security` → from = backend
- `$1 = qa` → from = reviewer 또는 security (둘 다 승인 필요)
- `$1 = cicd` → from = qa

### 2. MCP 툴 호출
```
mcp__agent-platform__handoff_validate({
  from_agent: <추론된 from>,
  to_agent: "$1",
  feature: "$2"
})
```

특수 케이스 — `$1 = qa` 인 경우: reviewer/security **둘 다** 통과 확인 필요
- `handoff_validate(from="reviewer", to="qa", feature=...)` 호출
- `handoff_validate(from="security", to="qa", feature=...)` 호출
- 둘 다 `passed: true` 여야 진행

### 3. 결과 분기

**통과**:
1. `mcp__agent-platform__log_append({ message: "handoff $from → $1 approved", agent: "orchestrator", feature: "$2" })`
2. `@$1` Agent 호출하며 다음 메시지 전달:
   ```
   @$1 `$2` feature handoff
   - Quality Gate: 통과
   - 승인된 산출물: <gate_check.files 에서 passed: true 파일들>
   - 입력 컨텍스트: docs/features/$2/
   ```

**실패**:
1. handoff 중단
2. 다음 포맷으로 리포트:
   ```
   ❌ Handoff 차단 — 다음 항목 미충족:
   - source_output_errors: <list>
   - gate_check 실패 파일:
     - <file>: <errors>
   ```
3. 이전 Agent(`$from`)에게 반려 제안

## 주의
- Agent 이름은 `planner | backend | reviewer | security | qa | cicd` 중 하나
- `from_agent` 는 MCP 서버가 아직 추론하지 않음 — 본 명령이 직접 결정
