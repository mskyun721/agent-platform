# Backend Capability Evidence

Checked: 2026-09-13. Installed Claude Code 2.1.269, codex-cli 0.154.0.
`python3 scripts/check_capabilities.py` reports version/help observations without starting an AI task.
supported below means the specified evidence exists, not that an authenticated end-to-end task passed.
An additional independent two-CLI fixture smoke passed on 2026-09-14; see
[P2 execution evidence](p2-execution-evidence.md) for scope, retries and limits.

| Capability | Claude direct | Codex direct | Codex wrapper | Evidence / remaining validation |
|---|---|---|---|---|
| Canonical role connection | supported: generated adapters | supported: AGENTS routing | supported: prompt injection | Repository tests and explicit-policy seeded-bug smoke on both CLIs; broad parity unverified |
| Project skill enable/disable | supported: .claude/skills | supported: .agents/skills | expected state only | P3 fresh-session activation/disable/removal smoke passed 2026-09-14; plugin/global discovery partial |
| Usage collection by platform | unverified | unverified | unsupported currently | P4 collection adapters not implemented |
| Permission/sandbox options | supported: --permission-mode in help | supported: --sandbox in help | supported: workspace-write argv | Behavioral isolation and deployment overrides unverified |
| Structured output option | supported: --output-format in help | supported: --json / --output-schema in help | unsupported currently | Wrapper uses final Markdown; does not parse JSONL yet |
| Native resume | supported: --resume in help | supported: exec resume in help | unsupported currently | Actual resumed session and P6 reconciliation unverified |
| Legacy --full-auto | not applicable | unsupported on 0.154.0 | removed | `codex exec --full-auto --help` returned exit 2 |

The wrapper now uses `--sandbox workspace-write`; it does not add approval bypass or danger-full-access.
This is a compatibility correction, not a grant of remote-action permission.
Official reference: [OpenAI CLI developer commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli).
Local version/help output is the flag evidence. The later smoke demonstrated access for that run only;
actual model identities were not collected and account availability is not a lasting guarantee.
