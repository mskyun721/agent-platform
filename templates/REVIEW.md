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

## 검토 요청 (사람이 결정할 것)
> 인계 결정과 Finding 상태를 본문보다 먼저 둔다. 결정 열에 `[x]` 가 하나 이상 있어야 `approved` 로 올릴 수 있다(gate 검사).

| # | 항목 | 제안 | 결정 |
|---|---|---|---|
| R-1 | 인계 결정 — 미해결 HIGH <n>건, MEDIUM <n>건 | 승인 (→ QA) / 반려 (→ Backend, 사유) | [ ] 승인 / [ ] 반려 |

### Findings 상태
| Finding | Severity | 상태 | 위치 |
|---|---|---|---|
| <title> | HIGH | open | `src/.../Foo.kt:42` |

## 1. Summary
전반 평가를 1~2문단으로 요약한다. 마이그레이션·쿼리 변경이 있으면 "DB-REVIEW 대상" 과 파일:라인을 적는다(판정은 dba).

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

## 3. Positive
잘 된 점과 유지할 구현 판단을 정리한다.

## 4. Action Items
- [ ] ...

---

## 5. Reviewer Notes
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
