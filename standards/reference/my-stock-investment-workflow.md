# my-stock 투자 역할 연결

플랫폼은 개발·리서치 역할을 실행하고 my-stock은 전략·데이터·위험 통제·주문을 소유한다.
아래 흐름은 명시적으로 선택한 같은 target/작업 폴더에 보고서를 모으는 방식이다.
자동 매매 연결이나 자동 다중 에이전트 실행이 아니다.

## 역할과 결과

| 역할 | 검토 질문 | 산출물 |
|---|---|---|
| investment | 왜 이 전략인가? 출처와 반대 근거는 무엇인가? | INVESTMENT-REPORT.md |
| quant | 규칙이 측정 가능하고 백테스트·통계가 타당한가? | QUANT-REPORT.md |
| investment-risk | 어떤 상황에서 손실이 커지고 어떤 통제가 빠졌는가? | INVESTMENT-RISK.md |
| planner | 검토 결과를 어떤 변경과 인수 기준으로 구현할 것인가? | PRD.md, TASK.md, API-SPEC.md, FLOW.drawio |

보고서는 target `docs/research/strategy-review/`에 저장한다. 각 역할은 독립적으로 실행할 수 있다.
다른 보고서를 인용할 때 원출처·데이터 시점·코드 revision을 재확인하며 초안에 대한 동의를 승인으로 처리하지 않는다.

## 현재 세션에서 요청하기

아래 요청들은 순서대로 사용할 수 있다. 기준일은 실제 작업에 맞게 지정한다.

```text
investment 역할로 research/strategy-review를 수행해줘.
root=/Users/seongkyunmoon/Documents/project/my-stock, as_of=2026-09-23.
현재 구현된 전략과 관련 코드만 확인하고 투자 가설·출처·반대 근거를 정리해줘.
보고서는 docs/research/strategy-review/INVESTMENT-REPORT.md에 작성해줘.
```

```text
quant 역할로 같은 root와 research/strategy-review를 검토해줘. as_of=2026-09-23.
docs/research/strategy-review/INVESTMENT-REPORT.md와 실제 전략·백테스트 코드를 확인해줘.
시점 누출·universe 편향·비용·체결·표본·워크포워드를 검토하고 QUANT-REPORT.md를 작성해줘.
실제 실행이 필요한 실험은 명령·환경·기대 결과를 구분해 qa에 넘겨줘.
```

```text
investment-risk 역할로 같은 root와 research/strategy-review를 검토해줘. as_of=2026-09-23.
같은 폴더의 INVESTMENT-REPORT.md와 QUANT-REPORT.md를 입력으로 읽고,
BuyGate·RiskCheck·예산 예약·거래 정지 관련 실제 코드와 연결해 INVESTMENT-RISK.md를 작성해줘.
계좌·포지션 자료가 없으면 노출 측정은 unknown으로 남기고 코드에서 확인 가능한 통제를 검토해줘.
```

```text
planner 역할로 root=/Users/seongkyunmoon/Documents/project/my-stock에
investment-validation 기능을 계획해줘. docs/research/strategy-review/의
INVESTMENT-REPORT.md, QUANT-REPORT.md, INVESTMENT-RISK.md를 읽어줘.
초안의 미검증 가정을 확정 사실로 취급하지 말고 인수 기준과 검증 과제로 변환해줘.
docs/features/investment-validation/에 기존 planner 산출물을 작성하고
기존 랭킹 변경을 보존하면서 독립 검증 가능한 작업으로 나눠줘.
```

구현 요청은 해당 계획 검토 후 backend로 전달한다. reviewer/security는 코드·보안,
qa는 실제 테스트를 수행한다. quant의 보고서 검토와 테스트 실행 성공을 구분한다.

## 명시적인 CLI/MCP 위임

같은 AI의 직접 세션에서는 wrapper가 필수가 아니다. 다른 CLI 실행을 명시적으로 요청한 경우 사용한다.
저장소 root에서 다음 명령을 사용하며 외부 root는 기존 허용 목록을 따른다.

```bash
# 작업 폴더가 없을 때 한 번만 실행; 기본 PRD/TASK scaffold도 생성한다.
uv --directory mcp-server run agent-platform-agent new-feature research/strategy-review --root /Users/seongkyunmoon/Documents/project/my-stock

uv --directory mcp-server run agent-platform-agent run quant research/strategy-review --root /Users/seongkyunmoon/Documents/project/my-stock --as-of 2026-09-23 --requirements "현재 전략·백테스트 코드의 시점·비용·표본 검토" --dry-run

uv --directory mcp-server run agent-platform-agent run investment-risk research/strategy-review --root /Users/seongkyunmoon/Documents/project/my-stock --as-of 2026-09-23 --requirements "현재 위험 통제 코드와 미검증 손실 시나리오 검토" --dry-run
```

dry-run은 경로·프롬프트만 확인하며 보고서를 생성하지 않는다. 실제 위임 실행은 해당 요청 범위에서
`--dry-run`을 제거한다. MCP는 `investment_run`, `quant_run`, `investment_risk_run`이며 공통 입력은
`feature`, `requirements`, `as_of`, `root`, `dry_run`, `timeout_sec`, `cli`다.
기존 서버가 실행 중이면 새 도구 목록을 반영하도록 MCP 서버를 재시작/재연결한다.
Claude adapter 역시 새 세션에서 역할 등록을 확인한다.

## 확인된 연계와 한계

2026-09-23 실제 my-stock root와 기존 `refactor/investment-agent-adoption` 작업 폴더를 대상으로
세 MCP 함수의 dry-run을 실행했다. 세 출력 경로가 my-stock 아래로 결정되는 것과
Codex read-only sandbox, active-project 불변을 확인했다. 제품 파일이나 투자 보고서는 생성하지 않았다.
실제 외부 AI 분석, 시장 데이터 조회, 백테스트 실행, 주문 연계는 이 연결 확인에 포함되지 않는다.

새 역할 추가는 my-stock의 ResearchEvidence 검증기나 자동 paper 운용 기능을 구현하지 않는다.
현재 역할은 구조화된 검토 문서를 개발 흐름에 연결하며 금융 주장의 진위는 자동 승인하지 않는다.
