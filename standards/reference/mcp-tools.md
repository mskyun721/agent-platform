# MCP Tools Reference

The FastMCP entry point is `mcp-server/src/agent_platform_mcp/server.py`.

| Tool | Purpose |
|---|---|
| `hello` | smoke test |
| `project_init` | Kotlin/Java Spring project creation |
| `feature_scaffold` | create PRD/TASK; optional root selects a validated project without changing active-project |
| `feature_list_artifacts` | list files/status in optional root; artifact symlinks rejected |
| `feature_gate_check` | canonical feature names, bounded links, empty-item failure and prerequisites; optional root, verify, verify_profile, risk_base. `track` is full \| light \| work. Requested verification not_run/error fails. Policy is advisory in P0. Risk conflict/invalid/unverified blocks declared risk; legacy undeclared remains report-only. risk_base includes committed changes from merge-base in addition to pending changes |
| `handoff_validate` | optional root, purpose (plan_review/implementation_complete/rework), verify, verify_profile; completion requires source approval, rework accepts rejected review/security/qa outputs to backend without requiring passing tests |
| `plan_run` | PRD/TASK draft (cli: auto\|codex) |
| `backend_run` | backend implementation and API/decision artifacts (cli: auto\|codex) |
| `review_run` | REVIEW draft (cli: auto\|codex) |
| `audit_run` | SECURITY-AUDIT draft (cli: auto\|codex) |
| `qa_run` | TEST-PLAN / QA draft (cli: auto\|codex) |
| `release_run` | PR/release/checklist drafts (cli: auto\|codex) |
| `standards_read` | read whitelisted standard/template/workflow doc |
| `standards_list` | list whitelisted docs |
| `confluence_fetch_page` | fetch a Confluence page by ID and return as Markdown |
| `confluence_list_space` | list pages in a Confluence space by space key |
| `confluence_create_page` | create a single Confluence page from Markdown under a parent page |
| `confluence_sync_feature` | bulk-upload a feature's MD artifacts to Confluence |
| `apidog_list_endpoints` | list summarized endpoints (method/path/summary) from an API Dog project |
| `apidog_export_openapi` | export full OpenAPI 3.0 spec from an API Dog project |
| `apidog_fetch_endpoint_detail` | fetch request/response detail for a single endpoint |

Debugging raw JSON-RPC calls should stay here, not in `README.md`.

## 장시간 위임 (10분 이상 예상 작업)

MCP 래퍼는 동기 호출이라 완료까지 블로킹된다 (`backend_run` 최대 1800초).
장시간 구현 위임은 다음 패턴을 권장한다:

1. `backend_run(feature, cli=..., dry_run=true)` 로 프롬프트/커맨드만 생성
2. 반환된 command를 Bash `run_in_background`로 직접 실행
3. 완료 후 산출물 파일(API-SPEC.md, DECISIONS.md, 코드)을 검증하고 front-matter status를 승격

`backend_run`/`plan_run`/`qa_run`/`release_run`은 외부 CLI가 대상 파일(API-SPEC.md, PRD.md/TASK.md, TEST-PLAN.md, PR-BODY.md 등)을 직접 작성하도록 지시한다 — wrapper는 완료 후 front-matter 보정만 수행하고, stdout은 요약(summary)으로만 반환된다.
반면 `review_run`/`audit_run`은 CLI의 stdout 전체를 캡처해 그대로 REVIEW.md/SECURITY-AUDIT.md 본문으로 저장한다 — stdout에 CLI 배너나 설치 로그가 섞이면 산출물에도 그대로 남으므로, 그런 경우 산출물을 재생성한다.
# WORK 계약 선택

## Project Identity

- `project_register(path, project_id=None, verify_profile=None)`: UUID 기반 ID 등록, allowlist/중복 검사.
- `project_list()`: 로컬 등록 메타데이터 조회.
- `project_rebind(project_id, new_path)`: 이동 후 명시적 경로 재연결, allowlist 재검사.
- `project_unregister(project_id)`: 등록 메타데이터만 삭제.
- scaffold/list/gate/handoff의 `root`에 ID 또는 경로를 전달한다. 결과에 project_id를 반환하고
  gate/handoff는 verify_profile_id도 반환한다. 명시적인 verify_profile이 등록 기본값보다 우선한다.
- worktree는 Git common directory로 ID만 공유하며 실행 경로를 등록 원본으로 치환하지 않는다.
- 역할 wrapper 6종도 root에 ID/경로를 받는다. 요청 시작에 context를 고정하며 결과에 project_id/project_dir/verify_profile_id를 반환한다.
- root 생략 시 기존 active-project fallback을 사용한다. 검증 프로필 메타데이터 반환이 wrapper 내부 자동 검증 실행을 뜻하지 않는다.

`feature_scaffold(name, root=None, contract=None)`에서 `contract="work-v1"`을 지정하면
WORK.md만 생성한다. 생략 시 기존 PRD/TASK를 생성하며 알 수 없는 계약은 생성 전에 거부한다.
list/gate/handoff는 같은 root의 WORK.md를 인식한다. 잘못된 WORK도 legacy로 우회하지 않는다.
위험 선언은 필수이고 high의 QA/cicd 인계에는 SECURITY-AUDIT.md 승인이 필요하다.
선언은 실제 변경 경로와 교차 검사된다 (`risk_rules.paths`; `low` 선언 + 위험 경로 변경 = 게이트 실패).
`feature_gate_check(..., risk_base="origin/main")`와 `handoff_validate(..., risk_base="origin/main")`은
해당 revision과 HEAD의 merge-base부터 커밋된 변경 및 staged/unstaged/untracked를 검사한다.
생략 시 pending-only이므로 PR 전체를 검사한 것으로 보고하지 않는다. 결과 risk에 scope/base_ref/comparison_revision을 기록한다.
Git 실패, 기준 revision 오류, 비어 있거나 잘못된 규칙은 unverified로 선언된 위험의 인계를 차단한다.
선언 없는 기존 계약은 undeclared로 보고만 하며, 경로 미일치를 저위험 자동 판정으로 쓰지 않는다.
직접 세션용 경로이며 역할 wrapper 출력 계약 전환은 아직 제공하지 않는다.
