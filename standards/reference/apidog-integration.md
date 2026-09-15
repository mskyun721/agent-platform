# API Dog 연동 지침 (Planner / Backend Agent)

## 개요

`apidog_list_endpoints` / `apidog_export_openapi` / `apidog_fetch_endpoint_detail` MCP 툴을 사용해 API Dog 프로젝트에 등록된 기존 API 명세를 PRD/API-SPEC 작성 전에 참조할 수 있다.

| 툴 | 용도 |
|---|---|
| `apidog_list_endpoints(project_id)` | 프로젝트의 엔드포인트 목록(요약)을 조회 |
| `apidog_export_openapi(project_id)` | OpenAPI 3.0 전체 스펙을 export |
| `apidog_fetch_endpoint_detail(project_id, path, method)` | 단일 엔드포인트의 요청/응답 상세를 조회 |

## 필수 환경변수

| 변수 | 설명 |
|---|---|
| `APIDOG_API_TOKEN` | API Dog Personal Access Token (`X-Apidog-Api-Access-Token` 헤더로 전달) |

## 사용 절차

신규·수정 API의 선작성 정책은 `standards/api-contract.md`를 따른다. OpenAPI 3.1 named schema, 응답 계약, 권한 확장, enum 설명을 작성하고 기존 3.0 export와 교환 시 null/required 및 확장 보존을 검증한다. 원격 import·발행은 이 읽기 전용 MCP의 기능이 아니며 사용자 승인과 별도 도구가 필요하다. 날짜별 스냅샷은 대상 프로젝트의 작업 문서 아래 보관한다.

사용자가 API Dog 프로젝트 ID를 제공하면:

1. **목록부터 확인** — `apidog_list_endpoints(project_id)` 로 등록된 엔드포인트 목록(method/path/summary/operation_id/tags)을 먼저 훑는다.
2. **상세가 필요한 경우** — 특정 엔드포인트의 요청/응답 스키마가 필요하면 `apidog_fetch_endpoint_detail(project_id, path, method)` 로 상세(parameters/request_body/responses)를 가져온다.
3. **전체 스펙이 필요한 경우** — 신규 기능이 기존 API 전반과의 정합성을 요구하면 `apidog_export_openapi(project_id)` 로 전체 OpenAPI 3.0 spec을 가져온다.
4. **requirements/문서 조합** — 가져온 내용을 아래 형식으로 앞부분에 추가:

```
## API Dog 참고 자료 (project: {project_id})

### 기존 엔드포인트
{method} {path} — {summary}
...

---

## 사용자 요구사항

{사용자가 입력한 원본 요구사항}
```

5. PRD/API-SPEC 작성 시 기존 엔드포인트와 네이밍·스키마 컨벤션이 일치하는지 비교 근거로 사용한다.

## 에러 처리

툴이 `{"error": "..."}` 를 반환하면:

| 에러 메시지 | 원인 | 조치 |
|---|---|---|
| `Missing env var: APIDOG_API_TOKEN` | 환경변수 미설정 | 사용자에게 토큰 발급/설정 안내 후 진행 여부 질의 |
| `API Dog auth failed. Check APIDOG_API_TOKEN.` | 토큰 인증 실패 (401) | `APIDOG_API_TOKEN` 값 재확인 요청 |
| `API Dog: no access to project {project_id}. Check token permissions.` | 권한 없음 (403) | 토큰의 프로젝트 접근 권한 확인 요청 |
| `API Dog project not found: {project_id}` | 잘못된 프로젝트 ID (404) | 올바른 `project_id` 확인 요청 |
| `API Dog API error: HTTP {status}` | 기타 비정상 응답 | 잠시 후 재시도 또는 API Dog 상태 확인 |
| `API Dog request timed out after {DEFAULT_TIMEOUT_SEC}s` | 타임아웃 (30초) | 네트워크 상태 확인 후 재시도 |
| `API Dog returned a non-JSON response` | 응답 파싱 실패 | API Dog 측 이슈 가능성, 재시도 |
| `Path '{path}' not found in project {project_id}` | 상세 조회 시 path 불일치 | `apidog_list_endpoints` 결과의 `path` 값을 그대로 사용했는지 확인 |
| `Method '{METHOD} {path}' not found in project {project_id}` | 상세 조회 시 method 불일치 | 해당 path에 등록된 method인지 `apidog_list_endpoints` 결과로 확인 |

## 참고

- `apidog_list_endpoints`/`apidog_fetch_endpoint_detail`은 내부적으로 `apidog_export_openapi`를 호출해 spec을 가져온 뒤 가공하므로, 동일 프로젝트에 대해 반복 조회 시 매번 전체 spec을 새로 export한다 — 다수의 엔드포인트 상세가 필요하면 `apidog_export_openapi`로 한 번에 받아 직접 탐색하는 편이 더 효율적일 수 있다.
- 읽기 전용(Read-only) 연동이다. API Dog 프로젝트에 데이터를 생성/수정하는 기능은 제공하지 않는다.
