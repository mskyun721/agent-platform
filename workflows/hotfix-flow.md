# Hotfix Flow

P0/P1 장애·긴급 결함 대응 흐름. Planner는 생략하고 Backend → QA → CICD로 진행한다.

## Criteria
- P0: 서비스 중단, 데이터 손실/유출, 보안 취약점
- P1: 주요 기능 장애, 다수 사용자 영향

## Flow
1. Orchestrator가 hotfix 여부 판단
2. Backend: 재현 테스트 작성 → 원인 분석 → 최소 수정
3. QA: 재현 테스트와 인접 회귀 확인
4. CICD: hotfix PR, CI, rollback/monitoring 확인
5. Postmortem 초안 작성

## Gates
| To | Required |
|---|---|
| QA | 재현 테스트가 실패→수정 후 통과, 영향 범위 명시 |
| CICD | 재현/회귀 테스트 통과, 신규 결함 없음 |
| done | PR/배포 완료, rollback 준비, 모니터링 확인, postmortem 초안 |

## Rules
- 전체 stack trace와 재현 조건을 확보한다.
- 핫픽스 범위를 결함 수정으로 제한한다. 리팩토링/개선은 별도 작업.
- 보안/데이터 이슈는 Security 검증을 추가한다.
- DB migration이 있으면 forward-compatible과 rollback을 확인한다.
- 배포 후 24시간 내 postmortem을 작성한다.

## Log
target project `claude_log.md`에 `[HOTFIX]`로 감지, 수정 시작, QA 완료, 배포, 복구 확인 시각을 기록한다.
