---
agent: planner
feature: <feature-name>
contract: work-v1
status: draft
risk: undecided
risk_reason:
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# WORK: <feature-name>

## 1. 목표
- 목표와 수락 조건:

## 2. 범위
- 포함:
- 제외:
- 기능별 PR 범위와 로직 변경 예산 (추가+삭제 500라인 이하):
- 기획 시 [API-SPEC.md](API-SPEC.md), [FLOW.drawio](FLOW.drawio)(draw.io, 정상·실패·분기)를 선작성한다. 노드 ↔ AC 연결은 4절 표의 `흐름 노드` 열에 적는다.
- API 변경 시 같은 디렉터리의 openapi.yaml에 계약 작성. API 변경이 없으면 API-SPEC.md에 해당 없음 사유 기록.

## 3. 위험
- 인증/권한/데이터/공개 계약/파괴적 변경 여부:
- 판단 후 risk를 low 또는 high로 변경. high이면 risk_reason 필수.
- 고위험 완료 인계는 SECURITY-AUDIT.md 검토 필요.

## 4. 검증
| AC | 흐름 노드 | 성공/실패 시나리오 | 명령 및 환경 | 기대 결과 |
|---|---|---|---|---|
| AC-1 | | | | |

## 5. 결정
- 선택과 근거:

## 6. 결과
- 변경 파일 및 코드 revision:
- 실행 결과와 리포트 경로 (passed/failed/blocked/not_run):
- 실제 DB/외부 연동과 테스트 대역 범위:
- 데이터 정리 및 잔여 위험:

원본은 draft로 유지한다. 구현 또는 결과 변경 뒤 기존 승인을 재사용하지 않는다.
필요한 테스트 미실행은 완료가 아니다. 별도 planner 호출은 필수가 아니다.
