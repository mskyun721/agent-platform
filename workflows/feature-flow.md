# Feature Flow

신규 기능 개발 표준 흐름. Orchestrator는 이 문서로 순서와 gate만 판단하고, 세부 실행은 각 `.claude/agents/*.md`와 `standards/reference/*.md`를 따른다.

## Flow
1. `planner` → `PRD.md`, `TASK.md`, `API-SPEC.md`, `FLOW.md`(Mermaid), API 변경 시 `openapi.yaml`
2. `backend` → 코드, `API-SPEC.md`, `DECISIONS.md` (10분 이상 예상되면 `standards/reference/mcp-tools.md`의 장시간 위임 패턴 사용)
3. `reviewer` + `security` + `dba` 병렬
   - reviewer: 선택된 AI backend 실행, `REVIEW.md` (쿼리 복잡도 1차 선별 포함)
   - security: Orchestrator가 사용자에게 선택받은 CLI
   - dba: `DB-REVIEW.md` — 스키마·인덱스·쿼리 복잡도, 조회 1초 SLO 판정, `docs/db/DB-CATALOG.md` 갱신. 마이그레이션·쿼리 변경이 없으면 "해당 없음"
4. `qa` → `TEST-PLAN.md`, 필요 시 테스트 코드/BUG 문서
5. `cicd` → `PR-BODY.md`, `RELEASE-NOTE.md`, `DEPLOY-CHECKLIST.md`, PR

## Gates
| To | Required |
|---|---|
| backend | PRD/TASK complete, API-SPEC/FLOW 검토 완료, API 변경 시 OpenAPI 계약 확인, assumptions resolved, `status: approved` |
| reviewer/security/dba | TASK phases complete, tests pass, API-SPEC/DECISIONS `approved` |
| qa | REVIEW `approved` with HIGH 0, SECURITY-AUDIT `approved` with Critical/High 0, DB-REVIEW `approved` with HIGH 0 |
| cicd | PRD/API-SPEC/DECISIONS/REVIEW/SECURITY-AUDIT/DB-REVIEW/TEST-PLAN all `approved`, P0/P1 0 |
| done | CI pass, PR created, release note/checklist ready |

## Rejection
- Reviewer HIGH → Backend 수정 후 재리뷰
- Security Critical/High → Backend 수정, Critical은 hotfix 우선
- DBA HIGH (1초 SLO 위반, N+1, 무제한 풀스캔) → Backend 수정(쿼리·인덱스·마이그레이션) 후 재검토
- QA P0/P1 → Backend 수정 후 QA 재검증
- 3회 이상 반복 반려 → 사용자 개입 요청

## Logging
모든 phase 시작/완료는 TASK.md 체크박스 갱신과 conventional commit으로 기록한다.
