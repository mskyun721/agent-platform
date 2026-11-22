# Backend and model routing

A role wrapper can run Claude Code, Codex, Gemini CLI or Copilot CLI independently for each invocation.
This does not change the model/backend of an already running native session.
Use direct same-AI roles normally; wrappers are explicit delegated operations.

```bash
# Selection only: no model call, writes or automatic fallback
uv --directory mcp-server run agent-platform-agent route planner --root "$PWD"
uv --directory mcp-server run agent-platform-agent route reviewer --ai claude --model sonnet --root "$PWD"
# Explicit task execution (feature artifacts must already exist)
uv --directory mcp-server run agent-platform-agent run backend FEATURE --ai codex --model YOUR_CODEX_MODEL --root "$PWD" --dry-run
uv --directory mcp-server run agent-platform-agent run reviewer FEATURE --ai claude --model sonnet --root "$PWD" --dry-run
```

Remove `--dry-run` only when intending to invoke that backend. `--ai auto` is now
the standalone default. MCP role run tools use `cli` and optional `model`.
An `[AI: ...]` instruction must be passed by the calling agent as explicit `cli`;
raw requirement text is not scanned for routing tags.

Selection order:
- CLI: explicit → project role → common role → preferred_cli (legacy default Codex).
- Model for that CLI: explicit → project role models → common role models →
  cli_models → host_models[cli][role] → claude_models[role] for Claude →
  model_tiers[role_tiers[role]][cli] (`model_source: role_tier`) → CLI default.
- Backends: claude, codex, gemini, copilot (`agent_platform_mcp.backends.NAMES`).
- allowed_cli/allowed_models apply to every selection, including explicit overrides.
  A model allowlist requires a selected model; an unknown CLI default cannot bypass it.

Trusted policy lives only in the platform `.agent-config.json`. Project entries are
keyed by registered project ID or resolved absolute workspace path, with ID priority.
They do not modify active-project and are not read from arbitrary target configuration.
Malformed policy fails closed. This is wrapper policy, not enforcement over standalone
native sessions or a replacement for company-level vendor access controls.

Example configuration (replace model IDs with models available to your account):

```json
{
  "preferred_cli": "codex",
  "cli_models": {},
  "routing": {
    "allowed_cli": ["claude", "codex"],
    "allowed_models": {},
    "roles": {
      "planner": {"cli": "claude", "models": {"claude": "sonnet"}},
      "backend": {"cli": "codex"},
      "reviewer": {"cli": "claude"},
      "qa": {"cli": "claude", "models": {"claude": "haiku"}}
    },
    "projects": {
      "my-stock": {"reviewer": {"cli": "codex", "models": {"codex": "YOUR_CODEX_MODEL"}}}
    }
  }
}
```

These role choices are examples, not benchmark recommendations. Installed defaults
keep empty role/project routes and preserve preferred_cli. Claude native subagent and
Copilot custom agent frontmatter come from role_tiers × model_tiers (legacy claude_models
and host_models.copilot entries override per role); routing.models changes wrapper
invocations only. No automatic model ranking, difficulty classification,
retry, failover or cost-budget enforcement is included in this version.

## Role tiers and per-role models

| 역할 | 메인 스킬 | 보조 스킬(조건부) | tier | Claude | Copilot | Codex | Gemini |
|---|---|---|---|---|---|---|---|
| planner | brainstorming(불명확 시), writing-plans | graphify | high | opus | claude-opus-5.5 | CLI 기본값 | pro |
| backend | test-driven-development, systematic-debugging(버그) | executing-plans, graphify, drawio-skill, receiving-code-review, verification-before-completion | high | opus | claude-opus-5.5 | CLI 기본값 | pro |
| reviewer | reviewer.md 직접 리뷰 절차 | graphify, verification-before-completion, receiving-code-review | high | opus | claude-opus-5.5 | CLI 기본값 | pro |
| security | security.md 감사 절차 | security-scan, ai-red-team, app-pentest, graphify, verification-before-completion | high | opus | claude-opus-5.5 | CLI 기본값 | pro |
| dba | dba.md 스키마·쿼리 검토 | whodb-dba, graphify, verification-before-completion, systematic-debugging | high | opus | claude-opus-5.5 | CLI 기본값 | pro |
| investment | investment.md 근거·반대 근거 검토 | graphify, pdf-analyze, verification-before-completion | high | opus | claude-opus-5.5 | CLI 기본값 | pro |
| quant | quant.md 전문 검토 | graphify, pdf-analyze, verification-before-completion | high | opus | claude-opus-5.5 | CLI 기본값 | pro |
| investment-risk | investment-risk.md 전문 검토 | graphify, pdf-analyze, verification-before-completion | high | opus | claude-opus-5.5 | CLI 기본값 | pro |
| qa | verification-before-completion | systematic-debugging, graphify | mid | sonnet | claude-sonnet-5.5 | CLI 기본값 | flash |
| cicd | verification-before-completion | finishing-a-development-branch(점검 절차만) | mid | sonnet | claude-sonnet-5.5 | CLI 기본값 | flash |
| orchestrator | 공통 역할 라우팅(내장) | verification-before-completion | mid | sonnet | claude-sonnet-5.5 | CLI 기본값 | flash |

tier 정의(`.agent-config.json` `model_tiers`): high = opus / claude-opus-5.5 / pro, mid = sonnet / claude-sonnet-5.5 / flash,
low = haiku / claude-haiku-5.5 / flash-lite (현재 low 역할 없음). Codex 는 로컬 카탈로그에서 확인한 slug 가 없어 미지정이며
CLI 기본값(`~/.codex/config.toml` 의 `model`)을 쓴다. 스킬 원본은 `standards/reference/role-skills.md` 다.

- **직접 세션은 세션 모델을 따른다.** 대화 중인 세션이 역할을 직접 수행하면 그 세션의 모델로 실행된다. tier 는 Claude subagent(`.claude/agents` `model:`), Copilot custom agent(`.github/agents` `model:`), wrapper(`run`/`*_run`) 선택에만 적용된다.
- **최신 유지:** Claude(`opus`/`sonnet`/`haiku`)와 Gemini(`pro`/`flash`/`flash-lite`)는 별칭이라 CLI 가 최신 모델로 해석한다. Copilot 과 Codex 는 정확한 ID 가 필요하므로 `python3 scripts/models_refresh.py` 로 로컬 CLI 카탈로그(`copilot help config`, `codex debug models`)와 비교한다. 기본은 보고만 하며(AI 호출 없음, CLI 가 없으면 unavailable) `--write` 일 때만 `model_tiers` 의 copilot/codex 값을 바꾼다. 그 뒤 `python3 scripts/sync_claude_settings.py --agents-only` 로 adapter 를 갱신한다.
- 역할의 tier 를 바꾸려면 `role_tiers` 만 고친다. 특정 역할만 고정하려면 `host_models.<host>.<role>`(또는 Claude 의 legacy `claude_models.<role>`)을 쓴다. 명시 `--model` 이 항상 우선이다.

Malformed `model_tiers`/`role_tiers` (non-object, unknown backend or role, undefined tier,
invalid model ID) fail closed in routing, like the rest of the policy.

The selection response and run_started metadata include requested CLI/model,
selection sources, configuration hash and runtime_model_status=unverified. A requested
model/alias is not proof of the exact model used by the provider. Run detail displays
selection reasons. No full prompt or config contents are copied into selection metadata.

Claude uses `-p --output-format json --permission-mode dontAsk --strict-mcp-config`,
explicit tools and no permission bypass. Coding roles expose Read/Glob/Grep/Edit/Write/Bash;
only file operations are additionally allowed, while Bash still requires existing CLI
permission rules. A denied command must be reported as unverified work, not retried with
weaker permissions. Research roles expose only Read/Glob/Grep/WebSearch/WebFetch; no
shell, write or delegation tools. Codex retains workspace-write or research read-only
sandbox. These are different permission systems, not equivalent OS sandboxes. Existing
Claude hooks/settings may still execute; the wrapper is for trusted project workspaces.

Claude JSON result errors/malformed output mark the process failed even with exit code
zero. Available usage is projected; missing token fields stay unknown. Authentication,
model availability, native lifecycle and actual task quality require real CLI evaluation;
unit/dry-run tests do not establish them. No paid calls are needed for route preview.

Flags were checked against installed `claude --help` and the
[official CLI reference](https://code.claude.com/docs/en/cli-reference).
