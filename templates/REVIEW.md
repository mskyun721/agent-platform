---
agent: reviewer
feature: <feature-name>
status: draft
created: YYYY-MM-DD
updated: YYYY-MM-DD
focus: all
tool: codex
---

# REVIEW: <기능명>

> 이 문서는 `review_run_codex` MCP 툴이 생성한 원문에 Reviewer Agent가 분류·주석을 추가한 결과물이다. 원문 영역은 수정하지 않는다.

## 1. Summary
(Codex 원문)

## 2. Findings
(Codex 원문 — Severity 별 항목)

### [HIGH] <title>
- 위치: `src/.../Foo.kt:42`
- 근거:
- 권장 조치:

### [MEDIUM] <title>
- ...

### [LOW] <title>
- ...

## 3. Positive
(Codex 원문 — 잘 된 점)

## 4. Action Items
- [ ] ...

---

## 5. Reviewer Notes
> Reviewer Agent 작성 영역. Codex 원문의 분류 판단, 반려 사유, QA에 전달할 특별 요청 등을 기록.

### 재분류 결과
| Original | Final Severity | 사유 |
|---|---|---|
| HIGH: <title> | HIGH | (유지) |
| MEDIUM: <title> | LOW | false positive — standards/coding-style.md 29라인 참조 |

### Handoff 결정
- [ ] 승인 (→ QA)
- [ ] 반려 (→ Backend, 사유: ______)

### 추가 의견
...
