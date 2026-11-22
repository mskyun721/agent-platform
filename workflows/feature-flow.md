# Feature Flow

신규 기능 개발 표준 흐름. Orchestrator는 이 문서로 순서와 gate만 판단하고, 세부 실행은 각 `standards/agents/<role>.md`(원본)와 `standards/reference/*.md`를 따른다. 역할은 현재 세션이 직접 수행하며 다른 AI 위임은 명시 요청 시에만 한다.

## Flow
1. `planner` → `PRD.md`(§6 서비스 흐름 포함), `TASK.md`, `API-SPEC.md`, API 변경 시 `openapi.yaml` (FLOW.drawio 는 작성하지 않는다)
2. `backend` → 코드, `API-SPEC.md`, `DECISIONS.md` (현재 세션에서 직접 구현. 다른 AI 위임을 명시 요청한 경우에만 `standards/reference/mcp-tools.md`의 장시간 위임 패턴 사용)
3. `reviewer` + `security` + `dba` 병렬
   - reviewer: 선택된 AI backend 실행, `REVIEW.md` (마이그레이션·쿼리 변경은 "DB-REVIEW 대상" 표시만)
   - security: 선택된 AI backend(기본 현재 세션), `SECURITY-AUDIT.md`
   - dba: `DB-REVIEW.md` — 스키마·인덱스·쿼리 복잡도, 조회 1초 SLO 판정, `docs/db/DB-CATALOG.md` 갱신. 마이그레이션·쿼리 변경이 없으면 "해당 없음"
4. `qa` → `TEST-PLAN.md`, 필요 시 테스트 코드/BUG 문서
5. `cicd` → `PR-BODY.md`, `RELEASE-NOTE.md`, `DEPLOY-CHECKLIST.md`, PR

## Gates
| To | Required |
|---|---|
| backend | PRD/TASK `approved`(PRD `## 검토 요청` 결정 모두 `[x]`), API-SPEC·PRD §6 흐름 검토, API 변경 시 OpenAPI 계약 확인, assumptions resolved |
| reviewer/security/dba | TASK phases complete, tests pass, PRD/API-SPEC/DECISIONS `approved` |
| qa | REVIEW `approved` with HIGH 0, SECURITY-AUDIT `approved` with Critical/High 0, DB-REVIEW `approved` with HIGH 0 |
| cicd | PRD/API-SPEC/DECISIONS/REVIEW/SECURITY-AUDIT/DB-REVIEW/TEST-PLAN all `approved`, P0/P1 0 |
| done | CI pass, PR created, release note/checklist ready |

backend/reviewer/security/dba/qa 인계는 target 루트 `ARCHITECTURE.md` 존재도 요구한다. WORK/light 계약의 선행 문서는 README §3 과 `config.py` 의 track 별 표를 따른다.

## Rejection
- Reviewer HIGH → Backend 수정 후 재리뷰
- Security Critical/High → Backend 수정, Critical은 hotfix 우선
- DBA HIGH (1초 SLO 위반, N+1, 무제한 풀스캔) → Backend 수정(쿼리·인덱스·마이그레이션) 후 재검토. `handoff_validate` 의 rework purpose 는 아직 dba→backend 를 지원하지 않으므로 DB-REVIEW 를 `rejected` 로 두고 backend 작업을 직접 지시한다
- QA P0/P1 → Backend 수정 후 QA 재검증
- 3회 이상 반복 반려 → 사용자 개입 요청

## Logging
모든 phase 시작/완료는 TASK.md 체크박스 갱신과 conventional commit으로 기록한다.
