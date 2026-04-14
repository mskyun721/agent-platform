# <type>(<scope>): <subject>

<!--
제목 규칙 (standards/commit-convention.md):
- type: feat | fix | refactor | chore | docs | test | perf | style
- subject: 영어, 명령형 현재시제, 50자 이내
-->

## Summary
- 이 PR에서 달성하려는 것 (1~3줄)
- 핵심 변경 사항 bullet

## Related
- PRD: `docs/features/<name>/PRD.md`
- TASK: `docs/features/<name>/TASK.md`
- Issue/Ticket: #NNN

## Changes
### Domain / Application
- 추가: `WithdrawUserUseCase`
- 변경: `User.requestWithdrawal()` 도메인 로직

### Adapter
- 신규 엔드포인트: `POST /v1/users/me/withdrawal`
- Repository: `UserRepository.findForUpdateById()`

### DB / Migration
- Flyway: `V20260413_01__add_withdrawal_columns.sql`

### Config / Infra
- `application.yml`: `withdrawal.grace-period-days`

## How to Test
```bash
./gradlew test --tests "com.company.user.withdrawal.*"
```

### 수동 검증
```bash
curl -X POST http://localhost:8080/v1/users/me/withdrawal \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"password":"xxxxx"}'
```

## Test Results
- [ ] Unit tests 통과
- [ ] Integration tests 통과
- [ ] 커버리지 기준 충족
- [ ] `ktlintCheck` / `detekt` 통과

## Checklist (머지 전 확인)
- [ ] `standards/coding-style.md` 준수
- [ ] `standards/api-contract.md` 준수
- [ ] `standards/security-baseline.md` 검토 (하드코딩 시크릿 없음, PII 로깅 없음)
- [ ] 모든 AC 통과 (PRD 기준)
- [ ] `DECISIONS.md` 업데이트 (trade-off 있는 결정 시)
- [ ] `API-SPEC.md` 업데이트
- [ ] Breaking change 없음 (있으면 아래에 명시)

## Breaking Changes
- 없음 / (있을 경우 영향 범위와 마이그레이션 방법)

## Screenshots / Logs
<!-- 필요 시 첨부 -->

## Deploy Notes
- 마이그레이션 필요: [ ]
- 설정 변경: [ ]
- 외부 시스템 조율: [ ]
- 피처 플래그: [ ]

## Reviewer
- @reviewer1
- @reviewer2

---
Co-Authored-By: <agent-name> (Claude Code Subagent)
