---
agent: cicd
feature: <feature-name>
status: draft
created: YYYY-MM-DD
updated: YYYY-MM-DD
version: vX.Y.Z
---

# Release Note: <버전> - <기능명>

## 릴리즈 정보
- **버전**: vX.Y.Z
- **릴리즈 일시**: YYYY-MM-DD HH:mm KST
- **배포 환경**: dev → stage → prod
- **담당**: Backend / CICD
- **관련 PR**: #123

## 변경 요약
### ✨ 신규 기능 (Features)
- 회원 탈퇴 기능 추가 (`POST /v1/users/me/withdrawal`)
- 90일 유예 후 hard delete 배치 추가

### 🔧 개선 (Improvements)
- 유저 조회 쿼리 성능 개선

### 🐛 버그 수정 (Bug Fixes)
- (해당 시 기재)

### ⚠️ Breaking Changes
- 없음 / (있을 경우 상세)

## 배포 체크리스트
### 배포 전
- [ ] 모든 테스트 통과
- [ ] 스테이징 검증 완료
- [ ] DB 마이그레이션 스크립트 리뷰 완료
- [ ] 피처 플래그 설정 (필요 시)
- [ ] 관측성 대시보드 확인 (Grafana, Sentry)
- [ ] 롤백 계획 문서화

### 배포 중
- [ ] DB 마이그레이션 실행
- [ ] 배포 시작 Slack 공지
- [ ] Canary 배포 (10% → 50% → 100%)

### 배포 후
- [ ] 핵심 메트릭 모니터링 (15분)
- [ ] 에러율/응답시간 정상 확인
- [ ] 배포 완료 공지

## 마이그레이션
### DB 스키마
- `V20260413_01__add_withdrawal_columns.sql`
- Forward: `ALTER TABLE user ADD COLUMN ...`
- Rollback: `ALTER TABLE user DROP COLUMN ...` (주의: 데이터 손실)

### 데이터 마이그레이션
- 기존 유저 `status=ACTIVE` 백필 (자동)

### 설정 변경
- `application.yml`: `withdrawal.grace-period-days: 90` 추가
- Secret: 없음

## 의존성
- 외부 시스템: Order Service v1.2.0 이상 필요
- 라이브러리 업데이트: 없음

## 롤백 절차
1. 이전 버전 이미지로 재배포: `kubectl rollout undo deployment/user-api`
2. 필요 시 DB 마이그레이션 롤백 (주의: 탈퇴 유저 데이터 보존 고려)
3. 메트릭 복구 확인
4. 사후 분석 문서 작성

## 모니터링 포인트
- **핵심 메트릭**
  - `withdrawal.request.count` 정상 증가
  - `withdrawal.failure.rate` < 1%
  - API P95 < 500ms
- **알람 임계치**
  - 실패율 > 5% (5분) → 즉시 대응
  - P95 > 1s (5분) → 조사

## 알려진 이슈 / 제약
- (해당 시 기재)

## 참고 자료
- PRD: `docs/features/<name>/PRD.md`
- API-SPEC: `docs/features/<name>/API-SPEC.md`
- TEST-PLAN: `docs/features/<name>/TEST-PLAN.md`

## Quality Gate
- [ ] 모든 배포 전 체크 완료
- [ ] 롤백 절차 검증 완료
- [ ] 모니터링 대시보드 준비
- [ ] status: `draft` → `approved`
