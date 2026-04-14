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
┌───────────────────────────────────────┐
│ Phase 3: 품질 검증 (QA)               │
│  Input:  코드, PRD, API-SPEC          │
│  Output: TEST-PLAN.md, 추가 테스트    │
│  QG:     P0/P1 없음, NFR 충족         │
└───────────────────────────────────────┘
    ↓
┌───────────────────────────────────────┐
│ Phase 4: 배포 (CICD)                  │
│  Input:  전체 산출물                  │
│  Output: PR, RELEASE-NOTE.md          │
│  QG:     CI 통과, 롤백 준비           │
└───────────────────────────────────────┘
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

### Handoff 조건 (→ QA)
- [ ] TASK 전 Phase 체크 완료
- [ ] 모든 AC 통과 (Integration Test)
- [ ] `ktlintCheck detekt test` 통과
- [ ] 커버리지 기준 충족
- [ ] API-SPEC, DECISIONS `status: approved`

### 반려 조건
- PRD 결함 발견 (모순, 누락) → Planner로 반환
- AC 일부 구현 불가 → Planner와 재논의

---

## Phase 3: 품질 검증 (QA)
### 트리거
- Backend Handoff 수신

### 절차
1. PRD AC, API-SPEC 에러 케이스 파싱
2. `templates/TEST-PLAN.md` 작성
3. 누락된 테스트 보강 (동시성, 경계값, 보안)
4. 부하 테스트 (필요 시)
5. 전체 테스트 실행 + 회귀 검증
6. 결함 발견 시 `BUG-REPORT.md` 작성

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
