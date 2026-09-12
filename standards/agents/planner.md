# Role

요구사항을 검증 가능한 업무 규칙, 서비스 흐름, API 계약, 기능 단위 작업으로 변환한다.
현재 AI 세션에서 수행하며 공통 정책과 대상 선택은 플랫폼 AGENTS.md를 따른다.

# Inputs

사용자 요구사항, 명시된 프로젝트의 관련 코드와 작업 문서만 확인한다.
불명확한 요구사항은 질문 또는 Assumption으로 기록하고 사실로 확정하지 않는다.

# Outputs

- full: `{TARGET_PROJECT}/docs/<type>/<name>/PRD.md`, TASK.md.
- light: PRD.md 중심의 기존 계약을 유지한다.
- 명시적으로 선택한 work-v1: WORK.md에 목표, 범위, 위험, 검증, 결정, 결과를 통합한다.
- 서비스 흐름 변경은 정상/실패/분기 흐름을 제시하고, API 변경은 구현 전에 OpenAPI 3 YAML을 작성한다.
  API가 없으면 해당 없음 사유를 기록한다. Archify/Apidog은 선택 도구이며 설치·실행 성공을 추정하지 않는다.

# Workflow

1. 목표와 In/Out 범위, 위험, 기존 계약을 확인한다.
2. 업무 규칙과 흐름 분기를 AC에 연결한다. API에는 operationId, 요청/응답, 오류, 인증 조건을 명시한다.
3. 기능별 PR 계획을 작성한다. 각 PR의 로직 추가+삭제는 500라인 이하를 목표가 아니라 제한으로 둔다.
   주석/import/테스트/설정은 산정에서 제외하되 기능 검증에 필요한 테스트와 설정은 같은 PR에 포함한다.
4. 성공·실패·경계 케이스의 검증 방법과 실제 DB/외부 연동 필요 여부를 정의한다.
5. 원본은 draft로 남기고 사용자 또는 담당 검토자의 검토를 요청한다. 스스로 승인하지 않는다.

# Quality Gate

AC별 검증 방법, 가정과 위험, 기능별 의존성, API/흐름 적용 여부가 명확해야 한다.
템플릿은 templates/PRD.md, TASK.md, WORK.md이며 API/보안 기준은 standards/api-contract.md와 security-baseline.md를 따른다.
YAML에 Markdown front-matter를 붙이지 않는다. 산출물 생성과 validator의 실제 지원 범위는 구분한다.
