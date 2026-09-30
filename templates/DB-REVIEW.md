---
agent: dba
feature: <feature-name>
status: draft
created: YYYY-MM-DD
updated: YYYY-MM-DD
ai_backend: <ai-backend>
links:
  catalog: docs/db/DB-CATALOG.md
---

# DB REVIEW: <기능명>

> dba 역할의 스키마·쿼리 검토 결과. 조회 API 1초 SLO 판정을 포함한다. 마이그레이션·쿼리 변경이 없으면 1절에 "해당 없음"과 근거만 적는다.

## 1. Summary
검토 범위(기준 revision, 마이그레이션 파일, 변경 adapter 메서드)와 전반 판정을 1~2문단으로. SLO 위반·반려 여부를 첫 문장에.

## 2. Query Complexity
신규·변경 쿼리마다 한 행. 규모 가정은 [DB-CATALOG.md](../../db/DB-CATALOG.md)의 현재 값과 3년 예상을 쓴다.

| 쿼리 (파일:라인) | 실제 SQL 형태 | 요청당 문장 수 | 접근 경로 (인덱스 / 풀스캔) | 차수·규모 가정 (현재 → 3년) | 실측 (EXPLAIN ANALYZE, p95) | 1초 SLO | 판정 |
|---|---|---|---|---|---|---|---|
| `FooRepository.findByX` (`src/.../FooPersistenceAdapter.kt:42`) | `SELECT … WHERE org_id=? AND status=? ORDER BY created_at DESC LIMIT 20` | 1 | `idx_foo_org_status_created` Index Scan | O(log n + 20) · foo 10만 → 50만 | 3 ms → 4 ms (staging) | OK | OK |
| `BarRepository.latestByIds` (`…:88`) | `… WHERE seq = (SELECT MAX(seq) FROM bar b2 WHERE b2.parent_id = bar.parent_id)` | 1 | 외부 `idx_bar_parent` + SubPlan 외부 행마다 재실행 | O(Σ nₛ²) · 7천 → 2만 행 | 미실측 (staging 없음) | 위반 예상 | HIGH — Findings |

## 3. Schema and Indexes
| 변경 | 파일 | 판단 |
|---|---|---|
| `CREATE INDEX idx_bar_parent_seq ON bar (parent_id, seq DESC)` | `V21__….sql` | WHERE/ORDER BY 와 일치, 기존 `idx_bar_parent` 대체 가능 |
| 보존 정책 | `bar` | 없음 — 무한 증가. 별도 항목 |

카탈로그 갱신: [DB-CATALOG.md](../../db/DB-CATALOG.md) 의 `bar` 행에 증가율·인덱스 반영 (커밋 <hash>).

## 4. Findings
severity 순. 실제 파일과 라인만 인용한다.

### [HIGH] <title>
- 상태: open
- 위치: `src/.../BarPersistenceAdapter.kt:88`
- 근거:
- 재현·규모:
- 권장 조치 (택일, 우선순위 순):

### [MEDIUM] <title>
- ...

### [LOW] <title>
- ...

## 5. Action Items
- [ ] ...

---

## 6. Reviewer Notes
> dba 역할 작성 영역. REVIEW.md 의 `쿼리 복잡도(시간)` 절과 판정이 다르면 여기서 재분류 사유를 남긴다.

### Handoff 결정
- [ ] 승인 (→ QA)
- [ ] 반려 (→ Backend, 사유: ______)

## Skill Usage
| skill | tier | mode | version | status | reason / evidence |
|---|---|---|---|---|---|
| standards/agents/dba.md (직접 절차) | main | manual | platform | used | ... |
