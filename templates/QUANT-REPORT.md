---
agent: quant
feature: <feature-name>
status: draft
created: YYYY-MM-DD
updated: YYYY-MM-DD
as_of: YYYY-MM-DD
---

# QUANT REPORT: <feature-name>

## 1. Summary

전략 가설, 기준 시점, 연구 상태와 미확인 사항을 요약한다.

- 연구 상태: INSUFFICIENT (근거 확인 뒤 갱신; 거래 승인 아님)
- 기준일 / 시간대 / cutoff:

## 2. Strategy Specification

진입·청산·보유기간·리밸런싱·포지션 크기 규칙과 무효화 조건을 측정 가능한 명세로 정의한다. 임계값은 근거 없이 최적값으로 제시하지 않는다.

## 3. Data and Methodology

source_id, published_at/available_at/retrieved_at, 데이터 버전, universe, 코드 revision, 비용·체결 가정, 학습/검증/보류 구간을 기록한다.

| 검토 항목 | 출처·코드·실행 근거 | 결과(passed/failed/not_run) | 한계 |
|---|---|---|---|

## 4. Results and Robustness

시점 누출·생존 편향·다중 검정·과최적화·표본 수·민감도·워크포워드를 검토한다. 평가 구간 길이와 포함된 시장 레짐 수, 그 구간을 고른 근거를 함께 기록한다. 기준선과 동일 입력·비용으로 비교하고 실제 결과와 제안 실험을 분리한다. 실행 증거가 없으면 not_run이다.

| 검토 항목 | 출처·코드·실행 근거 | 결과(passed/failed/not_run) | 한계 |
|---|---|---|---|

## 5. Development Handoff

실제 파일과 신규 제안 경로를 구분하고 전략 명세·인수 기준·테스트 데이터·검증 명령을 planner/qa에 전달한다.

## 6. Skill Usage

실제 사용한 스킬, 도구, 실행 여부와 한계를 기록한다.

| skill | tier | mode | version | status | reason / evidence |
|---|---|---|---|---|---|
