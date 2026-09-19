---
agent: planner
feature: project-structure
status: draft
created: 2026-09-18
updated: 2026-09-18
links:
  prd: docs/refactor/project-structure/PRD.md
  task: docs/refactor/project-structure/TASK.md
  api: docs/refactor/project-structure/API-SPEC.md
---

# API-SPEC: 프로젝트 구조 개선

## 적용 범위

외부 API 변경 없음. Python 내부 모듈 경로를 재편하는 작업이며 HTTP endpoint나 이벤트를
추가하지 않는다. 따라서 openapi.yaml은 생성하지 않는다.

## 보존 계약

- pyproject.toml의 agent-platform-mcp / agent-platform-agent 진입점 유지.
- server.py의 MCP 도구 이름·입력 schema·반환값·오류 의미 유지.
- cli.py의 argparse 명령·옵션·기본값·종료 코드 유지.
- target docs/<type>/<name>, front-matter 및 draft/approved 의미 유지.
- DB schema version 5, 기존 이벤트 필드, 프로젝트 registry 형식 유지.
- allowlist와 외부 변경 승인 절차 유지.
- 내부 파일 이동에 따른 verifier fingerprint 변경은 정상적인 승인 만료로 처리한다.
  기존 reviewed_verifier_hash를 새 값으로 자동 갱신하지 않는다.

## 검증 방법

이동 전후 FastMCP 도구 목록/inputSchema와 argparse 트리를 정규화하여 비교한다.
설치된 FastMCP API로 목록을 수집하고 실제 stdio 클라이언트에서 initialize/list_tools를 검증한다.
help/dry-run·실패 종료 코드는 기존 CLI 테스트로 검증한다. 외부 AI·HTTP 호출은 테스트 대역을 사용한다.
SQLite 업그레이드는 임시 디렉터리의 실제 SQLite DB로 검증한다.

내부 import 변경은 README에 설명하고 저장소의 tests/scripts/evals 소비자를 같은 단계에서 갱신한다.
관련 계획: [TASK.md](TASK.md), 진행 흐름: [FLOW.drawio](FLOW.drawio).
