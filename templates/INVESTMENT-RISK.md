---
agent: investment-risk
feature: <feature-name>
status: draft
created: YYYY-MM-DD
updated: YYYY-MM-DD
as_of: YYYY-MM-DD
---

# INVESTMENT RISK: <feature-name>

## 1. Summary

검토 대상·기준 시점·연구 상태와 중대한 미해결 위험을 요약한다. 위험도 판단과 거래 승인을 구분한다.

- 연구 상태: INSUFFICIENT (근거 확인 뒤 갱신; 거래 승인 아님)
- 기준일 / 시간대 / cutoff:

## 2. Exposure and Limits

집중도·상관 노출·유동성·레버리지·현금/증거금·회전율을 검토한다. 관측값과 정책 한도를 source_id·단위·시점으로 연결하고 계좌 자료가 없으면 unknown으로 둔다.

## 3. Scenarios and Counterevidence

급락·갭·거래 정지·유동성 고갈·데이터 지연·상관 급등·중복 주문 상황과 손실 가정을 기록한다. 시나리오 가정값을 실제 예측이나 측정된 손실로 표시하지 않는다.

| 검토 항목 | 출처·코드·실행 근거 | 결과(passed/failed/not_run) | 한계 |
|---|---|---|---|

## 4. Controls and Gaps

위험 → 실제 통제 코드 → 검증 증거 → 잔여 위험을 연결한다. BuyGate/RiskCheck·예산 예약·거래 정지·멱등성과 주문 경로 우회를 검토한다. 코드 존재만으로 통제 효과가 검증됐다고 하지 않는다.

| 검토 항목 | 출처·코드·실행 근거 | 결과(passed/failed/not_run) | 한계 |
|---|---|---|---|

## 5. Development Handoff

심각도·근거·조치·인수 기준을 planner/backend/qa에 전달한다. 한도를 임의 변경하거나 전략을 자동 승인하지 않는다.

## 6. Skill Usage

실제 사용한 스킬, 도구, 실행 여부와 한계를 기록한다.

| skill | tier | mode | version | status | reason / evidence |
|---|---|---|---|---|---|
