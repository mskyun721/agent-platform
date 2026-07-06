# Agent Platform — Gemini Guide

공통 규칙은 `AGENTS.md`를 따른다 (Core Policy, 산출물 계약, CLI 정책 포함).

## Gemini 전용
- 읽기 전용 role(plan/review/audit/qa)은 `--approval-mode plan`, release는 `auto_edit`로 실행된다.
- 모델 핀은 `.agent-config.json`의 `cli_models.gemini`.
