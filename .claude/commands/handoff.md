---
description: MCP 툴로 Quality Gate 검증 후 다음 Agent로 handoff
argument-hint: <next-agent> <feature-name>
allowed-tools:
  - mcp__agent-platform__handoff_validate
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

`purpose` 는 역할 쌍에서 추론된다 — planner→reviewer/security = `plan_review`(문서만),
reviewer/security/qa→backend = `rework`(반려 문서가 `rejected` 여야 함, 테스트 요구 없음),
그 외 = `implementation_complete`(소스 산출물 `approved` + 검증 프로필 실행). 사용자가 반려 수정을
요청하면 `to_agent: "backend"`, `from_agent: <반려한 역할>` 로 호출한다. 검증 프로필이 필요하면
`verify_profile` 을 넘긴다 (`.agent-config.json` `verify_profiles`).

PR 범위의 완료 인계에는 실제 기준 revision을 `risk_base`로 전달한다 (`--risk-base` 옵션).
생략하면 미커밋 변경만 검사한다. conflict/invalid/unverified는 해결 전 인계하지 않는다.

특수 케이스 — `$1 = qa` 인 경우: reviewer/security **둘 다** 통과 확인 필요
- `handoff_validate(from="reviewer", to="qa", feature=...)` 호출
- `handoff_validate(from="security", to="qa", feature=...)` 호출
- 둘 다 `passed: true` 여야 진행

### 3. 결과 분기

**통과**:
1. handoff 승인 내역은 TASK.md 체크박스와 commit으로 남는다.
2. `@$1` Agent 호출하며 다음 메시지 전달:
   ```
   @$1 `$2` feature handoff
   - Quality Gate: 통과
   - 승인된 산출물: <gate_check.files 에서 passed: true 파일들>
   - 입력 컨텍스트: {TARGET_PROJECT}/docs/<type>/$2/ (`$2`에 `/`가 있으면 docs/$2/, 없으면 docs/features/$2/)
   ```

**실패**:
1. handoff 중단
2. 다음 포맷으로 리포트:
   ```
   ❌ Handoff 차단 — 다음 항목 미충족:
   - purpose: <purpose>
   - source_output_errors: <list>
   - gate_check 실패 파일:
     - <file>: <errors>
   - risk: <gate_check.risk.status> (conflict 면 path_hits 나열)
   - verification_status / policy_status: <값>
   ```
3. 이전 Agent(`$from`)에게 반려 제안

## 주의
- Agent 이름은 `planner | backend | reviewer | security | qa | cicd` 중 하나
- `from_agent` 는 MCP 서버가 아직 추론하지 않음 — 본 명령이 직접 결정
- `docs/<type>/<name>/...` 상대 경로는 `.active-project` 가 가리키는 타겟 프로젝트 기준이다 (CLAUDE.md 참고)
