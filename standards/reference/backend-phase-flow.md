# Backend Phase Flow

## Phases

| Phase | Scope | Review trigger |
|---|---|---|
| Phase 1: Domain | Schema, domain model, domain exceptions, domain unit tests | reviewer after Phase 1 |
| Phase 2: Application | Port interfaces, UseCase service, application unit tests (mock) | reviewer after Phase 2 |
| Phase 3: Adapters & Integration | Inbound/Outbound adapters, events, Testcontainers integration tests | reviewer after Phase 3 |
| Phase 4: Quality & Documentation | Observability, API-SPEC, DECISIONS | reviewer after Phase 4 → Security handoff |

## Models

Phase 별 모델은 여기서 정하지 않는다. 기본값은 `.agent-config.json` `claude_models.backend`
이며, orchestrator 가 특정 Phase 에 다른 모델이 필요하다고 판단하면 `Agent(model=...)` 로
override 한다. 근거는 handoff prompt 에 한 줄로 남긴다.
