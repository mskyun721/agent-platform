# MCP Tools Reference

The FastMCP entry point is `mcp-server/src/agent_platform_mcp/server.py`.

| Tool | Purpose |
|---|---|
| `hello` | smoke test |
| `graph_status` | read-only graph integrity and snapshot freshness |
| `graph_impact` | advisory reverse-dependency file/test candidates with explanations |
| `project_init` | Kotlin/Java Spring project creation |
| `feature_scaffold` | create PRD/TASK; optional root selects a validated project without changing the default target |
| `feature_list_artifacts` | list files/status in optional root; artifact symlinks rejected |
| `feature_gate_check` | canonical feature names, bounded links, empty-item failure and prerequisites; an existing `*.drawio` (FLOW.drawio) is validated structurally with drawio-skill `validate.py` (`files[].kind: drawio`, no approval status; not a prerequisite for any role); an `approved` artifact whose `## 검토 요청` table still has an undecided row (no `[x]` in the decision column) fails; optional root, verify, verify_profile, risk_base. `structure` reports whether the target root has `ARCHITECTURE.md` (present \| missing); backend/reviewer/security/dba/qa prerequisites require it. `track` is full \| light \| work. Requested verification not_run/error fails. Policy is advisory in P0. Risk conflict/invalid/unverified blocks declared risk; legacy undeclared remains report-only. risk_base includes committed changes from merge-base in addition to pending changes |
| `feature_render_view` | write `docs/<type>/<name>/REVIEW-VIEW.html` (PRD `## 검토 요청` table → an existing FLOW.drawio drawn as inline SVG with legend/zoom/node detail plus a prose step list (section omitted when absent) → API summary · state machine · errors beside the business-rule / acceptance-criteria tables → folded full docs; BR/AC/D codes link to their definitions, no external scripts); optional root; appends `docs/**/REVIEW-VIEW.html` to the target `.gitignore` unless gitignore=false. CLI: `scripts/render_feature_view.py` |
| `experience_add` | role, feature, cue, lesson, evidence_note, evidence (1..10 project files), source_handoff, explicit root; writes a draft to `docs/experience/<role>/`; approval is the separate CLI `experience approve` |
| `experience_list` | explicit root, optional role/status; metadata only — approved lessons are in `docs/experience/<role>/INDEX.md` |
| `handoff_validate` | optional root, purpose (plan_review/implementation_complete/rework), verify, verify_profile; adds `warnings` when the source role recorded no experience entry (never blocks); completion requires source approval, rework accepts rejected review/security/qa outputs to backend without requiring passing tests |
| `plan_run` | PRD/TASK + API-SPEC draft, API 변경 시 openapi.yaml, FLOW.drawio 없음 (cli: auto\|claude\|codex\|gemini\|copilot) |
| `backend_run` | backend implementation and API/decision artifacts (cli: auto\|claude\|codex\|gemini\|copilot) |
| `review_run` | REVIEW draft (cli: auto\|claude\|codex\|gemini\|copilot) |
| `audit_run` | SECURITY-AUDIT draft (cli: auto\|claude\|codex\|gemini\|copilot) |
| `qa_run` | TEST-PLAN / QA draft (cli: auto\|claude\|codex\|gemini\|copilot) |
| `release_run` | PR/release/checklist drafts (cli: auto\|claude\|codex\|gemini\|copilot) |
| `standards_read` | read whitelisted standard/template/workflow doc |
| `standards_list` | list whitelisted docs |
| `confluence_fetch_page` | fetch a Confluence page by ID and return as Markdown |
| `confluence_list_space` | list pages in a Confluence space by space key |
| `confluence_create_page` | create a single Confluence page from Markdown under a parent page |
| `confluence_attach_file` | attach a local file (.drawio/.png) to an existing page by ID (same name = new version) |
| `confluence_update_page` | replace an existing page/draft body by ID with Markdown (empty title keeps current; untitled draft needs one) |
| `confluence_sync_feature` | upload a feature to Confluence: overview page (검토 요청·개요·범위·API 요약·흐름 텍스트, FLOW.drawio attached) with one child page per .md; `overview=false` keeps the flat layout. Create-only — duplicate titles fail `root` = project path or registered ID (default: active target) |
| `notion_sync_feature` | publish a feature to Notion: overview page `<type>/<name>` under `parent_page_id` (default: project `publish.notion.parent_page_id`, no env default) with one child page per .md. Idempotent upsert (mapping in `.local/publish/`, then title lookup); `dry_run` makes no call. Env `NOTION_TOKEN` |
| `publish_feature` | publish a feature to the project's target set by CLI `project-publish-set` (none → skipped, confluence → `confluence_sync_feature`, notion → `notion_sync_feature`). Explicit call only; handoff never publishes. Returns `status` skipped\|planned\|published\|partial\|failed |
| `apidog_list_endpoints` | list summarized endpoints (method/path/summary) from an API Dog project |
| `apidog_export_openapi` | export full OpenAPI 3.0 spec from an API Dog project |
| `apidog_fetch_endpoint_detail` | fetch request/response detail for a single endpoint |

The `*_run` wrappers are for explicitly requested delegation to another AI; same-AI roles run directly in the current session (AGENTS.md "Direct CLI Agent Execution").

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

레지스트리는 `.agent-projects.json` 하나다(v2: `version`, `default`, `workspaces`, `projects`). 허용 경로는
플랫폼 루트 자신 ∪ workspace 하위 ∪ 등록 프로젝트 하위이며 심링크는 실제 경로로 판정한다.

- `project_register(path, project_id=None, verify_profile=None)`: UUID 기반 ID 등록, 중복 검사. **플랫폼 루트 또는 workspace 안의 경로만** 받는다(등록 경로 하위라도 workspace 밖이면 거부).
- `project_list()`: `version`, `default`, `workspaces`, `workspace_source`(registry/env/none), `legacy_active_project`, `active_path`, `active_targets`(name/path/default/project_id), `projects` 조회.
- `project_use(project_id)`: **등록된 프로젝트만**(ID·등록 폴더명·등록 경로) 기본 타겟(`default`)으로 전환. 미등록 경로와 플랫폼 자신은 거부.
- `root` 해석 순서: 등록 ID → 등록 경로의 폴더명 → 허용 범위 안 절대경로. 생략하면 `default`.
- `project_rebind(project_id, new_path)`: 이동 후 명시적 경로 재연결. 새 경로는 workspace 안이어야 한다.
- `project_unregister(project_id)`: 등록 메타데이터만 삭제(기본 타겟이면 `default` 를 비운다).
- `project_init(..., target_dir=None)`: `target_dir` 는 workspace 안(기본: 첫 workspace)이어야 하며, 만든 프로젝트를 등록하고 기본 타겟으로 정한다.
- workspace 추가·삭제, workspace 밖 경로 등록, git clone, 이전은 **MCP 도구가 없다**. 사람이 CLI 로만 한다:
  `project-workspace add|remove|list`, `project-add <path|git URL> [--project-id] [--default] [--into]`,
  `project-register`(workspace 밖 허용), `project-use`, `project-rebind`, `project-migrate [--dry-run]`.
- deprecated `AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS` 는 레지스트리에 workspace 가 없을 때만 fallback 이며, 이때는 등록 경로가 범위를 넓히지 않는다.
- scaffold/list/gate/handoff의 `root`에 ID 또는 경로를 전달한다. 결과에 project_id를 반환하고
  gate/handoff는 verify_profile_id도 반환한다. 명시적인 verify_profile이 등록 기본값보다 우선한다.
- worktree는 Git common directory로 ID만 공유하며 실행 경로를 등록 원본으로 치환하지 않는다.
- 역할 wrapper 9종도 root에 ID/경로를 받는다. 요청 시작에 context를 고정하며 결과에 project_id/project_dir/verify_profile_id를 반환한다.
- root 생략 시 기본 타겟(`default`; 이전 전에는 `.active-project` 첫 줄) fallback을 사용한다. 검증 프로필 메타데이터 반환이 wrapper 내부 자동 검증 실행을 뜻하지 않는다.

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

### Collector (token usage)

| Tool | CLI | Purpose |
|---|---|---|
| `observe_status(root)` | `observe status --root` | capture setting, `observe serve` heartbeat (`collector`), last one-shot collection (`last_collect`), latest stored turn per backend. `collection_scope: platform-and-registered-projects`. Read-only |
| `observe_efficiency(root)` | `observe efficiency --root` | bounded token summary of the latest sample; no inferred savings. Read-only |
| `usage_report(root, feature=None, by=None, since=None, include_incomplete=False)` | `observe usage --root [--feature type/name] [--by type\|role\|model] [--since YYYY-MM-DD] [--include-incomplete]` | feature: per-backend tokens (`total` only when one backend), per-role runs/reworks/missing, cost from recorded price snapshots (`missing_cost`), `quality` (rejections, review_cycles, first_pass_gates, bugs, human_interventions; missing source → `unknown`, no combined score). `by=type` (default): completed features only, per type × backend `n`/`missing_runs`/mean/median/max, `n<3` → `insufficient_sample`, empty → `no_data`, quality n/mean/median. `by=role`/`model`: per-run stats, all runs. Unmeasured usage (completeness != full) is missing, never zero; handoff/verification point runs excluded. Errors → `{"error"}` (`no runs or docs for feature: <key>`). Read-only |
| `observe_collect(root)` | `observe collect --root` | import Claude/Codex transcripts once, subagents included (Claude `subagents/agent-*.jsonl` → `role: subagent` + `agent_type`; Codex forked subagent → own turns only). Scope: capture-enabled platform root and registered project paths; sessions are attributed to that `project_id`. Capture off for root → `{"status": "skipped", "reason": "capture disabled"}` (CLI `--all-enabled`, used by the hooks, skips that check). ~10 s budget checked before each file: `truncated: true` only when files are left (rest on the next call), `over_budget: true` when only the time ran over. Commits per file; a concurrent run is `skipped` with `rerun_requested: true` and the holder collects once more. Never raises; CLI exits 0. Writes only the local content DB |
| `observe_capture(root, mode, confirm=false)` | `observe capture on\|off --root` | mode `on`\|`off`; result `{"workspace", "project_id", "capture_enabled", "retention_days": 7, "stores_content"}`. On stores prompt/response text locally for 7 days. MCP `on` without `confirm=true` changes nothing and returns `{"status": "confirmation_required", "stores", "retention_days": 7, …}`; call again with `confirm=true` only after the user agreed (Claude asks the user via the PreToolUse hook). `off` needs no confirmation |
| `doctor(root)` | `doctor --root` | CLI binaries, hook files (never executed), hosts, observation status |
| `otel_collector(action)` | `otel start\|stop\|status` | action `start`\|`stop`\|`status` only; runs exactly `docker compose -f scripts/otel/docker-compose.yml up -d` / `down` / `ps --format json`. No docker or daemon → `{"status": "unavailable", "reason": "docker not found\|daemon not running"}`; other failures → `error` with masked stderr tail |
| `otel_summary(since=None)` | `otel summary [--since YYYY-MM-DD]` | per session/model requests, tokens and CLI-reported cost from `scripts/otel/otel-data/*.jsonl` log events (Claude `api_request`, Codex `response.completed`); whitelisted attributes only, prompt/response never read; metrics/traces files skipped; 20 s budget → `truncated` |

Hooks: Claude `Stop`/`SessionEnd` (generated into `.claude/settings.json` by `scripts/sync_claude_settings.py`) and Codex `Stop` (`.codex/hooks.json`) run `scripts/hooks/observe_collect.py`, which detaches `observe collect --root <platform> --all-enabled` (every capture-enabled workspace, even with platform capture off) and returns at once. The Codex entry uses this checkout's absolute, quoted path written by the sync, so `.codex/hooks.json` is a local, gitignored file the sync creates when missing. `observe serve` polls under the same cross-process lock. `observe serve` and `purge-content` have no MCP tool (long-running server; irreversible delete).

`feature_gate_check(..., evidence=True)` and `handoff_validate(..., evidence=True)`
report code/criterion/profile-bound acceptance evidence. Configuration may enforce
checks even when omitted. See [evidence gates](evidence-gates.md).

Fresh-session claims and external-action confirmation/execution are explicit CLI
operations (`state continue`, `state action-*`), not automatic MCP side effects.
See [run recovery](run-recovery.md) for limits and manual intervention procedures.

`plan_run`의 `prd`/`all`은 API-SPEC.md(API 변경 시 openapi.yaml)를 작성하고 FLOW.drawio 는 만들지 않는다. 이미 있는 FLOW.drawio 는 gate 가 구조만 검사한다. `task`는 TASK.md만 갱신한다.
OpenAPI YAML에는 Markdown front-matter를 붙이지 않는다. `missing_artifacts`는 필수 Markdown
파일 누락만 보고하며 API/흐름 정합성, YAML 문법, 다이어그램 렌더링 검증과 승인은 별도다.

## Graph Inspection

- `graph_status(root=None)` / `graph status --root PATH_OR_ID`
- `graph_impact(paths, root=None, depth=3, limit=100)` / `graph impact PATH [PATH ...] --root PATH_OR_ID`
- Existing root resolution and allowlist apply, including explicit platform-root access. No default-target change.
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

All role run tools accept optional `model`. Role/project defaults and allowlists follow [backend/model routing](backend-model-routing.md). Explicit cli/model override defaults but never bypass allowlists.
