---
agent: planner
feature: <feature-name>
status: draft
created: YYYY-MM-DD
updated: YYYY-MM-DD
links:
  prd: docs/features/<feature-name>/PRD.md
---

# TASK: <기능명>

> PRD를 구현 가능한 작업 단위로 분해한 문서.

## Phase 구성 원칙
- 각 Phase는 **독립적으로 테스트 가능한 아키텍처 단위**
- Phase 완료 시 commit 필수 — `commit:` 필드에 해시 기록 전까지 완료 처리 불가
- 순서: Domain → Application → Adapters → Quality

---

## 의존성 & 블로커
| ID | 블로커 | 해결 상태 |
|---|---|---|
| - | 외부 API 스펙 확정 대기 | [ ] 해결 |

## Quality Gate (전체 완료 기준)
- [ ] 전 Phase 체크박스 완료
- [ ] 전 Phase `commit:` 해시 기록 완료
- [ ] 모든 AC(PRD의 Acceptance Criteria) 통과
- [ ] 커버리지 기준 충족 (`standards/test-policy.md`)
- [ ] API-SPEC, DECISIONS `status: approved`
