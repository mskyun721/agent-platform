# Feature Flow

신규 기능 개발 표준 워크플로우. Orchestrator가 이 문서를 기반으로 Agent 호출 순서와 Handoff를 관리한다.

## 전체 흐름
```
[사용자 요청]
    ↓
[Orchestrator]
    ↓
┌───────────────────────────────────────┐
│ Phase 1: 기획 (Planner)               │
│  Input:  사용자 요청                   │
│  Output: PRD.md, TASK.md              │
│  QG:     PRD Quality Gate 통과        │
└───────────────────────────────────────┘
    ↓
┌───────────────────────────────────────┐
│ Phase 2: 개발 (Backend)               │
│  Input:  PRD.md, TASK.md              │
│  Output: 코드, API-SPEC.md, DECISIONS │
│  QG:     AC 전부 통과, 커버리지 충족  │
└───────────────────────────────────────┘
    ↓
┌───────────────────────────────────────────────┐
│ Phase 2.5: 교차 검증 (Reviewer ∥ Security)    │
│  병렬 실행 — MCP 툴로 외부 CLI 호출            │
│  Reviewer (Codex)   → REVIEW.md               │
│  Security (Gemini)  → SECURITY-AUDIT.md       │
│  QG: HIGH/Critical 0건, 두 문서 approved      │
└───────────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────────────┐
│ Phase 3: 품질 검증 (QA, Codex CLI)             │
│  Input:  코드, PRD, API-SPEC, REVIEW, AUDIT    │
│  Output: TEST-PLAN.md, 테스트 코드             │
│  QG:     P0/P1 없음, NFR 충족                  │
└────────────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────────────┐
│ Phase 4: 배포 (CICD, Gemini CLI)               │
│  Input:  전체 산출물 + git log                 │
│  Output: PR-BODY, RELEASE-NOTE, CHECKLIST, PR  │
│  QG:     CI 통과, 롤백 절차, 모니터링 명시     │
└────────────────────────────────────────────────┘
    ↓
[완료 보고 → 사용자]
```

## Phase 1: 기획 (Planner)
### 트리거
- 사용자의 신규 기능 요청
- 기존 기능 대규모 변경 요청

### 절차
1. Orchestrator가 feature name 확정 (예: `user-withdraw`)
2. `docs/features/<name>/` 디렉토리 생성
3. `@planner` 호출
4. Planner는 `templates/PRD.md`, `templates/TASK.md` 작성
5. Assumption 정리 → 사용자 확인

### Handoff 조건 (→ Backend)
- [ ] PRD 모든 섹션 작성됨
- [ ] 모든 AC에 검증 방법 명시
- [ ] 도메인 모델 변경/마이그레이션 명시
- [ ] Business Rules 번호 부여
- [ ] API 엔드포인트 목록 확정
- [ ] Assumption 합의 완료
- [ ] status: `approved`

### 반려 조건
- 요구사항 모호 → 사용자에게 추가 질문
- Assumption이 유관부서 합의 필요 → 대기

---

## Phase 2: 개발 (Backend)
### 트리거
- Planner Handoff 수신

### 절차
1. PRD/TASK 읽기
2. TASK Phase 1~7 순차 진행
   - Phase 1: 도메인 & 스키마
   - Phase 2: Application
   - Phase 3: Adapter Inbound
   - Phase 4: Adapter Outbound
   - Phase 5: 이벤트/배치
   - Phase 6: 관측성
   - Phase 7: 문서화
3. 각 Phase 완료 시 TASK 체크박스 업데이트 + commit
4. 전체 완료 시 `API-SPEC.md`, `DECISIONS.md` 최종화

### Handoff 조건 (→ Reviewer + Security)
- [ ] TASK 전 Phase 체크 완료
- [ ] 모든 AC 통과 (Integration Test)
- [ ] `ktlintCheck detekt test` 통과
- [ ] 커버리지 기준 충족
- [ ] API-SPEC, DECISIONS `status: approved`

### 반려 조건
- PRD 결함 발견 (모순, 누락) → Planner로 반환
- AC 일부 구현 불가 → Planner와 재논의

---

## Phase 2.5: 교차 검증 (Reviewer ∥ Security)
Reviewer(Codex)와 Security(Gemini)는 **병렬 실행**. 둘 다 승인되어야 QA 진입.

### Reviewer (@reviewer)
- MCP 툴 `review_run_codex` 호출 → `REVIEW.md` 생성
- Codex 원문을 분류·우선순위화하고 Reviewer Notes 작성
- HIGH 1건 이상 → Backend 반려

### Security (@security)
- MCP 툴 `audit_run_gemini` 호출 → `SECURITY-AUDIT.md` 생성
- Gemini 결과를 Triage하고 Severity 재분류
- Critical/High → Backend 반려 (Critical 시 hotfix 권장)

### Handoff 조건 (→ QA)
- [ ] `REVIEW.md` `status: approved`, HIGH 없음
- [ ] `SECURITY-AUDIT.md` `status: approved`, Critical/High 없음
- [ ] MCP `handoff_validate(from_agent, to_agent="qa", ...)` 통과

### 반려 조건
- Reviewer: HIGH 발견 → Backend
- Security: Critical/High 발견 → Backend (Critical 은 hotfix)

---

## Phase 3: 품질 검증 (QA)
### 트리거
- Reviewer + Security 양쪽 Handoff 수신

### 절차
1. PRD AC, API-SPEC 에러 케이스 파싱
2. `REVIEW.md`, `SECURITY-AUDIT.md` 의 "특별 검증 요청" 반영
3. `templates/TEST-PLAN.md` 작성
4. 누락된 테스트 보강 (동시성, 경계값, 보안)
5. 부하 테스트 (필요 시)
6. 전체 테스트 실행 + 회귀 검증
7. 결함 발견 시 `BUG-REPORT.md` 작성

### Handoff 조건 (→ CICD)
- [ ] 모든 AC에 대응 TC 존재
- [ ] 모든 에러 케이스 TC 존재
- [ ] 커버리지 기준 충족
- [ ] P0/P1 결함 없음
- [ ] NFR 기준 충족
- [ ] TEST-PLAN `status: approved`

### 반려 조건
- P0/P1 결함 발견 → Backend로 반환 (BUG-REPORT 포함)
- 구현 누락 발견 → Backend로 반환

---

## Phase 4: 배포 (CICD)
### 트리거
- QA Handoff 수신

### 절차
1. 모든 산출물 `status: approved` 확인
2. 커밋/브랜치 정리
3. CI 파이프라인 검증
4. PR 생성 (`templates/PR-TEMPLATE.md`)
5. `RELEASE-NOTE.md` 작성
6. 배포 체크리스트 검증 (마이그레이션, 롤백, 모니터링)

### Handoff 조건 (→ Orchestrator, 완료)
- [ ] PR 생성 완료 + Reviewer 지정
- [ ] CI 전체 통과
- [ ] RELEASE-NOTE `status: approved`
- [ ] 롤백 절차 문서화
- [ ] 모니터링/알람 준비

---

## 반려 및 재진입 규칙
- 각 Phase는 이전 Phase로 반려 가능
- 반려 시 **사유와 기대 조치를 명확히 기록**
- 반려된 산출물은 `status: rejected`로 변경, 수정 후 `draft` → `approved` 재진행
- 3회 이상 반복 반려 시 사용자 개입 요청

## 작업 로그 기록
모든 Phase 시작/완료 시 `claude_log.md`에 기록:
```markdown
## YYYY-MM-DD

### <feature-name>
- [HH:mm] Phase 1 (Planner) 시작
- [HH:mm] Phase 1 완료, Handoff → Backend
- ...
```
