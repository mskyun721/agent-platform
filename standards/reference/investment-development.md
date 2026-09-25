# Investment Development

investment는 투자 리서치와 전략 검증 제안을 담당하고 planner/backend는 개발을 담당한다.
실제 금융 데이터·위험 통제·주문은 target 프로젝트의 계약과 실행 경로를 따른다.

## 검토 기준

- 각 주장에 출처 ID·원문 위치·공개/이용 가능/조회 시각을 연결한다.
- historical에서는 공개·이용 가능 시점이 as_of cutoff 이하인 버전을 사용한다.
  retrieved_at은 사후 조회일 수 있지만 당시 공개 버전이라는 증거가 필요하다.
- 수정 공시·거시 revision, 현재 상장 종목만 사용하는 universe의 한계를 명시한다.
- 금액·비율·주식 수·통화를 구분한다. 출처 없는 수치를 추정치로 위장하지 않는다.
- 비교 실험은 같은 universe·snapshot·as_of·비용·fold·코드로 수행한다.
- 독립 종목 판단 평가, 포트폴리오 체결 시뮬레이션, paper 원장을 구분한다.
- 결정론적 위험 통제·예산 예약·거래 정지를 LLM 판단으로 우회하지 않는다.
- 개발 단계는 근거 계약 → fixture 리서치 → 보류 데이터 비교 → 분리된 shadow/paper 순서다.
  기존 기능이 있으면 중복 구현하지 않는다. 모의 평가 통과가 실거래 활성화를 뜻하지 않는다.

## 역할별 사용

| 역할 | 확인할 것 |
|---|---|
| investment | 근거·반대 근거·시점·불확실성·검증 한계와 개발 제안 |
| quant | 전략 명세·시점 데이터·비용·편향·표본·워크포워드 |
| investment-risk | 노출·유동성·손실 시나리오·통제 증거·잔여 위험 |
| planner | INVESTMENT-REPORT의 가정을 검증 가능한 인수 기준으로 변환 |
| backend | target 계층·표준 라이브러리 재사용, 구조화 계약·실패 상태 구현 |
| reviewer/security | 시점 누출·단위 오류·외부 자료 지시 삽입·주문 경로 우회·데이터 권한 |
| qa | 고정 fixture, 날짜 경계·누락·오류, 비용·체결·위험 게이트 회귀 |

## my-stock 적용

대상 파일의 실제 존재를 먼저 확인한다. HistoricalContextBuilder의 공시일 조회와
ReplayPipelineService의 공통 전략·BuyGate, CostModel·ExecutionSimulator,
PromotionGateEvaluator를 우선 재사용한다. 현재 universe 근사 한계를 검증 결과에 남긴다.
OrderPlacementService의 dryRun은 독립 paper 원장과 같지 않다.
리서치 결과의 INSUFFICIENT/INVALID/ERROR를 매도 신호로 사용하지 않는다.

이 가이드는 금융 데이터 공급자나 외부 프레임워크를 설치하지 않는다. 새 공급자 연결,
리서치 자동 검증기, API, 주문 연계는 target에서 별도로 구현·검토해야 한다.

## 보고서 연결

investment → quant / investment-risk → planner → backend → reviewer/security → qa 순으로 활용한다.
역할 전환은 같은 세션에서 가능하며 자동 위임·병렬 실행을 의미하지 않는다.
사용자가 지정한 같은 작업 폴더의 세 보고서를 읽되 각 검토는 원출처까지 확인한다.
다른 보고서가 없어도 독립 검토할 수 있고 부족한 입력은 INSUFFICIENT로 기록한다.
세 보고서는 개발 참고 자료이며 기존 개발 gate의 필수 산출물로 강제하지 않는다.
