---
agent: investment
feature: <feature-name>
status: draft
created: YYYY-MM-DD
updated: YYYY-MM-DD
as_of: YYYY-MM-DD
---

# INVESTMENT REPORT: <feature-name>

## 1. Summary
- 질문 / 대상 종목·시장·통화:
- 기준일 / 시간대 / cutoff 시각:
- 연구 상태: INSUFFICIENT (READY / INSUFFICIENT / INVALID / ERROR 중 선택하고 근거 기록)
- 확인한 사실 / 추론 / 가정 / 미확인 사항:

## 2. Evidence
| source_id | 출처 URL·문서 위치 | published_at | available_at | retrieved_at | 버전·해시(확인 시) |
|---|---|---|---|---|---|

수치마다 source_id·단위·통화를 명시한다. 미래 공개·수정 자료를 기준 시점의 자료로 취급하지 않는다.

## 3. Thesis and Counterevidence
| 주장 | 근거 source_id | 반대 근거 source_id | 무효화 조건 | 불확실성 |
|---|---|---|---|---|

## 4. Risks and Validation
| 항목 | 확인한 근거 | 결과(passed/failed/not_run) | 잔여 한계 |
|---|---|---|---|
| 시점 누출·수정 이력 | | not_run | |
| universe·생존 편향 | | not_run | |
| 수수료·세금·슬리피지·체결 | | not_run | |
| 표본·민감도·보류 데이터·워크포워드 | | not_run | |
| 평가 구간 길이·포함 레짐·구간 선택 근거 | | not_run | |

실행한 명령·데이터 snapshot·코드 revision을 기록한다. 미실행 성과를 기입하지 않는다.

## 5. Development Handoff
| 문제 | 실제 파일 / 신규 제안 구분 | 제안 | 인수 기준 | 검증 방법 |
|---|---|---|---|---|

보고서는 planner의 개발 기획 입력이며 거래 명령·승인이 아니다.

## 6. Skill Usage
| skill | tier | mode | version | status | reason / evidence |
|---|---|---|---|---|---|
