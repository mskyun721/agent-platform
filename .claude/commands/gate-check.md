---
description: MCP 툴로 feature 산출물의 Front-matter·링크 정합성 검사
argument-hint: [feature-name]
allowed-tools: mcp__agent-platform__feature_gate_check, mcp__agent-platform__feature_list_artifacts, Read, Glob, Bash(ls:*)
---

Front-matter 및 링크 정합성을 검사하라.

## 절차

### 1. 대상 결정
- `$ARGUMENTS` 가 주어진 경우: 해당 feature 만
- 없는 경우: `docs/features/` 하위 모든 feature 디렉터리 순회

### 2. MCP 툴 호출
각 feature 에 대해:
```
mcp__agent-platform__feature_gate_check({ name: <feature> })
```
반환 구조:
```json
{ "feature": "...", "passed": bool, "files": [{ "file": "...", "errors": [...], "passed": bool }], "agent_gate": null }
```

### 3. 결과 집계 및 출력
```
📋 Gate Check Result

✅ Passed: N files
❌ Failed: M files

[FAILURES]
- docs/features/<name>/PRD.md
  - <error-1>
  - <error-2>
...
```

### 4. 실패 시 조치 제안
각 실패 항목에 대해:
- Front-matter 누락 → 해당 템플릿 참조 안내
- `status` 불일치 → `review`/`approved` 전환 시점 확인 요청
- 링크 경로 누락 → 해당 Agent 산출물 생성 단계 확인

## 참고
- draft 상태 문서는 링크 검증이 완화됨 (forward reference 허용)
- Agent별 prerequisites 체크하려면 `agent` 파라미터 추가: `feature_gate_check({ name, agent: "backend" })`
