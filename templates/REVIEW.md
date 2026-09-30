---
agent: reviewer
feature: <feature-name>
status: draft
created: YYYY-MM-DD
updated: YYYY-MM-DD
focus: all
ai_backend: <ai-backend>
---

# REVIEW: <기능명>

> 이 문서는 선택된 AI backend 또는 Reviewer Agent가 작성한 코드 리뷰 결과물이다. 특정 CLI(Codex/Claude)에 종속되는 표현을 남기지 않는다.

## 1. Summary
전반 평가를 1~2문단으로 요약한다.

## 2. Findings
문제는 severity 순서대로 작성한다. 실제 파일과 라인만 인용하고, 추정 파일은 쓰지 않는다.

### [HIGH] <title>
- 상태: open (해결 후 담당 검토자가 resolved (<현재 코드 fingerprint>)로 기록)
- 위치: `src/.../Foo.kt:42`
- 근거:
- 권장 조치:

### [MEDIUM] <title>
- ...

### [LOW] <title>
- ...

## 3. 쿼리 복잡도(시간)
신규·변경된 쿼리마다 한 행. 쿼리가 없으면 "해당 없음"과 근거를 한 줄로 적는다.

| 쿼리 (파일:라인) | 요청당 문장 수 | 접근 경로 (인덱스 / 풀스캔) | 차수·규모 가정 | 결과 상한 | TX 안 외부 호출 | 판정 |
|---|---|---|---|---|---|---|
| `FooRepository.findByX` (`src/.../FooPersistenceAdapter.kt:42`) | 페이지당 1 (IN 묶음) | `idx_foo_org_status` | O(page) · foo 10만 행 | size ≤ 100 | 없음 | OK |
| `BarRepository.countAll` (`...:88`) | 행당 1 → **N+1** | 풀스캔 (`LIKE '%q%'`) | O(n·m) · bar 50만 행 | 없음 | 없음 | HIGH — Findings 참조 |

## 4. Positive
잘 된 점과 유지할 구현 판단을 정리한다.

## 5. Action Items
- [ ] ...

---

## 6. Reviewer Notes
> Reviewer Agent 작성 영역. 발견 항목의 재분류 판단, 반려 사유, QA에 전달할 특별 요청 등을 기록.

### 재분류 결과
| Finding | Final Severity | 사유 |
|---|---|---|
| HIGH: <title> | HIGH | (유지) |
| MEDIUM: <title> | LOW | false positive — standards/coding-style.md 29라인 참조 |

### Handoff 결정
- [ ] 승인 (→ QA)
- [ ] 반려 (→ Backend, 사유: ______)

### 추가 의견
...
