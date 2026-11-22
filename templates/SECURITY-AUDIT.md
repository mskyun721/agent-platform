---
agent: security
feature: <feature-name>
status: draft
created: YYYY-MM-DD
updated: YYYY-MM-DD
scope: all
ai_backend: <ai-backend>
---

# SECURITY AUDIT: <기능명>

> 이 문서는 현재 세션의 Security 역할 또는 (다른 AI 위임 시) `audit_run` 이 작성한 draft에 Triage·주석을 추가하는 양식이다. 형식 오류 원문은 기본 보존하지 않으며 자동 승인하지 않는다.

## 1. Risk Level
- Overall: Critical / High / Medium / Low / None

## 2. Findings
(역할 판정 원문 — 위임 시 CLI 원문)

### [Critical] <title>
- 재현: (요청/조건)
- 영향: (데이터 노출/권한 상승/서비스 거부 등)
- 근거: `src/.../Foo.kt:42`
- 권장 조치:

### [High] <title>
- ...

### [Medium] <title>
- ...

### [Low] <title>
- ...

## 3. Checklist
(역할 판정 원문 — 통과 항목)

## 4. Recommendations
- [ ] 우선순위 1:
- [ ] 우선순위 2:

---

## 5. Triage
> Security Agent 작성 영역. false positive 판정, 완화 조치로 승격/강등된 항목을 기록.

### 제외·강등 항목
| Finding | Original | Final | 근거 |
|---|---|---|---|
| <title> | High | Medium | 내부망 전용 + 인증 우회 불가 (standards/security-baseline.md §3 준수) |

### Handoff 결정
- [ ] 승인 (→ QA)
- [ ] 조건부 승인 (→ QA, 조치 티켓 발행)
- [ ] 반려 (→ Backend, Critical/High 존재)

### 보안 베이스라인 매핑
| standards/security-baseline.md 항목 | 결과 |
|---|---|
| 하드코딩 금지 | ✅ / ❌ |
| PII 로깅 금지 | ✅ / ❌ |
| 외부 호출 timeout | ✅ / ❌ |
