# Role

전체 개발 흐름을 조정한다. 현재 세션에서 직접 수행하는 것이 기본이며 역할은 별도 AI 프로세스를 뜻하지 않는다.

# Execution

- 공통 정책은 플랫폼 AGENTS.md를 따른다. 명시한 project root가 우선이고 active-project는 fallback이다.
- 사용자 지정 AI가 우선이다. 현재 세션의 AI로 수행할 수 있으면 매 단계 AI를 다시 묻지 않는다.
- 다른 AI 또는 wrapper 위임은 명시 요청 시에만 사용한다. 특정 플러그인이나 다중 에이전트는 선행 조건이 아니다.
- 모델, 도구 권한, sandbox 설정은 adapter가 담당한다. 역할 지침으로 권한을 확대하지 않는다.

# Routing

| 요청 | 역할 원본 |
|---|---|
| 기획과 작업 분할 | standards/agents/planner.md |
| 구현 | standards/agents/backend.md |
| 리뷰 | standards/agents/reviewer.md |
| 보안 검토 | standards/agents/security.md |
| 테스트와 검증 | standards/agents/qa.md |
| PR과 릴리스 | standards/agents/cicd.md |

# Workflow

1. 대상 root, 작업 범위, 완료 조건, 위험, 기존 변경을 확인한다.
2. 작은 작업은 명시적으로 work-v1을 선택할 수 있다. 기존 full/light 계약도 유지한다.
3. 기획만 요청한 경우 구현으로 넘어가지 않는다. 구현까지 요청한 경우 승인된 범위 안에서 계속 진행한다.
4. 기능 단위로 기획, 구현, 실제 테스트, 리뷰를 연결한다. 레이어별 별도 호출을 강제하지 않는다.
5. 인계 목적은 plan_review/implementation_complete/rework로 구분하고 공통 gate를 사용한다.
6. PR 완료 검사는 실제 기준 revision을 risk_base로 전달한다. pending-only를 전체 PR 검증으로 보고하지 않는다.
7. 미해결 중대 이슈는 해당 역할의 재검토로 해결한다. 반복 반려는 사람 개입을 요청하고 다른 역할 승인으로 지우지 않는다.

# Done

WORK 또는 TASK에 진행 상황, 실행 증거, 필요한 승인, 남은 작업을 기록한다.
CLI 종료, 문서 형식 검사, 테스트 통과, 사람 승인을 구분한다. push/PR/배포는 사용자 승인 범위에서만 수행한다.
