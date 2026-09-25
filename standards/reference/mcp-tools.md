# MCP Tools Reference

The FastMCP entry point is `mcp-server/src/agent_platform_mcp/server.py`.

| Tool | Purpose |
|---|---|
| `hello` | smoke test |
| `graph_status` | read-only graph integrity and snapshot freshness |
| `graph_impact` | advisory reverse-dependency file/test candidates with explanations |
| `project_init` | Kotlin/Java Spring project creation |
| `feature_scaffold` | create PRD/TASK; optional root selects a validated project without changing active-project |
| `feature_list_artifacts` | list files/status in optional root; artifact symlinks rejected |
| `feature_gate_check` | canonical feature names, bounded links, empty-item failure and prerequisites; `*.drawio` (FLOW.drawio) validated structurally with drawio-skill `validate.py` (`files[].kind: drawio`, no approval status; full-track backend prerequisite); optional root, verify, verify_profile, risk_base. `structure` reports whether the target root has `ARCHITECTURE.md` (present \| missing); backend/reviewer/security/qa prerequisites require it. `track` is full \| light \| work. Requested verification not_run/error fails. Policy is advisory in P0. Risk conflict/invalid/unverified blocks declared risk; legacy undeclared remains report-only. risk_base includes committed changes from merge-base in addition to pending changes |
| `handoff_validate` | optional root, purpose (plan_review/implementation_complete/rework), verify, verify_profile; completion requires source approval, rework accepts rejected review/security/qa outputs to backend without requiring passing tests |
| `plan_run` | PRD/TASK + API-SPEC + FLOW.drawio draft, API 변경 시 openapi.yaml (cli: auto\|codex) |
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
- 역할 wrapper 9종도 root에 ID/경로를 받는다. 요청 시작에 context를 고정하며 결과에 project_id/project_dir/verify_profile_id를 반환한다.
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

## Local Skill Packages

| Tool | Purpose |
|---|---|
| `skill_add(path)` | Import a local SKILL.md + skill.json package without running scripts |
| `skill_list(project_id=None)` | List managed packages and optional registered-project state |
| `skill_remove(skill_id)` | Remove unused, unmodified managed snapshots only |
| `skill_enable(skill_id, project_id)` | Materialize supported native copies in the registered project |
| `skill_disable(skill_id, project_id)` | Remove unchanged managed copies; report retained modifications |

See [skill management](skill-management.md) for ownership and failure handling.

## Local Observation

| Tool | Purpose |
|---|---|
| `run_start(task_id, role, backend=None, model=None, root=None)` | Record a direct session without launching an AI |
| `run_end(run_id, outcome)` | Record completed/failed/interrupted/cancelled, not artifact approval |
| `run_checkpoint(run_id, phase, next_action, decisions=None, unresolved=None, verification=None, artifacts=None)` | Store bounded metadata and current workspace identity |
| `run_heartbeat(run_id, pid)` | Record the actual execution PID without changing another live owner |
| `run_resume(run_id)` | Inspect process/checkpoint/differences and pending actions; never execute them |
| `review_result_record(...)` | Record an explicit reviewer decision with a caller-stable decision_id |
| `runs_list(project_id=None, since=None)` | Query local runs |
| `usage_summary(project_id=None, since=None)` | Query known usage, missingness and historical cost snapshots |
| `review_cycle_status(task_id, project_id, threshold=3)` | Query independent role rejection counters |

Raw prompts/source/stdout/stderr are not collected. Unknown usage stays null.

`feature_gate_check(..., evidence=True)` and `handoff_validate(..., evidence=True)`
report code/criterion/profile-bound acceptance evidence. Configuration may enforce
checks even when omitted. See [evidence gates](evidence-gates.md).

Fresh-session claims and external-action confirmation/execution are explicit CLI
operations (`state continue`, `state action-*`), not automatic MCP side effects.
See [run recovery](run-recovery.md) for limits and manual intervention procedures.

`plan_run`의 `prd`/`all`은 API-SPEC.md와 draw.io `FLOW.drawio`(front-matter 없음, `validate.py`로 검사)를 포함한다. `task`는 TASK.md만 갱신한다.
OpenAPI YAML에는 Markdown front-matter를 붙이지 않는다. `missing_artifacts`는 필수 Markdown
파일 누락만 보고하며 API/흐름 정합성, YAML 문법, 다이어그램 렌더링 검증과 승인은 별도다.

## Graph Inspection

- `graph_status(root=None)` / `graph status --root PATH_OR_ID`
- `graph_impact(paths, root=None, depth=3, limit=100)` / `graph impact PATH [PATH ...] --root PATH_OR_ID`
- Existing root resolution and allowlist apply, including explicit platform-root access. No active-project change.
- Only `graphify-out/graph.json` is loaded; no subprocess, remote AI, database write or approval change.
- Graph size limit: 32 MiB, 100,000 nodes, 500,000 edges. Snapshot source reads: 32 MiB/file and 128 MiB total.
- Paths: 1–100 normalized project-relative file paths; no traversal, absolute paths, symlinks, protected filenames,
  docs/PROMPT/local-state inputs. Deleted source paths are allowed and reported as missing.
- Depth: integer 1–10; result limit: integer 1–500. Boolean bounds are invalid.
- Invalid inputs/schema raise errors (CLI exit 1). Valid diagnostic responses, including missing/degraded, exit 0.
- `status`: missing / degraded / ready. `integrity`: unknown / degraded / valid.
  `freshness`: unknown / stale / current. Always `mode: advisory`.
- `counts` reports nodes, edges, source_files, duplicate_ids, dangling_edges, missing_sources and nodes_without_source.
- Impact returns changed_paths, affected, test_candidates, unmapped_paths, truncated and the same health report.
  Each affected row has path, distance, via, relation, confidence; one deterministic shortest file-level explanation
  is retained. Confidence describes that edge, not the entire chain. Follow via rows to inspect upstream uncertainty.
- Both raw nodes/edges and Graphify node-link nodes/links formats are supported.
- `traversal` is reverse-dependencies or undirected-neighbors. Explicit directed=false explores both directions;
  legacy graphs without a directed flag use source-to-target relation convention with a warning.
- Traversal accepts calls/imports/imports_from/references/uses; semantic rationale and containment are excluded.
  Source-less/dangling endpoints cannot be traversed. Duplicate IDs or foreign source_root disable traversal.
  Unknown/stale graphs may still return explicitly advisory candidates. No test candidate is a verified AC mapping.

Optional producer metadata in graph.json:

```json
{
  "source_root": "/absolute/project",
  "snapshot": {
    "source_hashes": {"src/app.py": "SHA256_HEX_FROM_EXTRACTION"}
  }
}
```

The value must be a 64-character lowercase hexadecimal SHA256, captured with the graph extraction.
The example is explanatory, not a runnable graph fixture. This feature does not create/stamp snapshots, and
standard Graphify output may omit them. Do not stamp current hashes onto an old graph to claim freshness.
All indexed source paths must be covered and source_root must match for freshness=current; differences yield
stale, missing provenance/coverage yields unknown. This is a consistency check of producer metadata, not
cryptographic attestation, approval, or proof of complete extraction. New files outside the manifest require rebuilding.


## Investment Research

`investment_run(feature, requirements, as_of, cli="auto", dry_run=False, timeout_sec=600, root=None)`
은 명시적 외부 CLI 위임 시 사용한다. `as_of`는 YYYY-MM-DD이며 빈 요구사항·잘못된 날짜는 실행 전에 거부한다.
기존 feature 작업 폴더가 필요하다(`feature_scaffold` 또는 직접 세션으로 생성).
Codex는 read-only sandbox에서 Markdown만 출력하고 wrapper가 target의
`INVESTMENT-REPORT.md`를 draft로 저장한다. dry_run은 파일과 CLI 실행을 만들지 않는다.
형식 오류·비정상 종료 결과는 artifact_invalid로 표시하고 원문을 보관하지 않는다.
이 검사는 금융 사실·시점·수익률의 자동 검증이 아니다. 직접 세션은 investment 역할 원본을 사용한다.
보고서는 선택적 입력이며 기존 개발 gate의 필수 산출물에 자동 추가하지 않는다.
`handoff investment planner`를 사용할 경우 기존 완료 인계의 보고서 승인·정책·증거 조건을 따른다.

### Quant / Investment Risk

`quant_run`과 `investment_risk_run`은 investment_run과 같은 입력·root 해석·dry-run·timeout 계약을 사용한다.
각각 QUANT-REPORT.md와 INVESTMENT-RISK.md를 draft로 저장한다. 전자는 전략·통계·백테스트 검토,
후자는 투자 노출·손실 시나리오·통제 검토다. 모두 read-only CLI와 기존 형식 검증·관측을 재사용한다.
보고서 간 자동 실행이나 개발 gate 필수 문서 추가는 없다. my-stock 연결은
[투자 역할 실행 절차](my-stock-investment-workflow.md)를 따른다.
