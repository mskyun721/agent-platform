# Backend Phase Flow

## Phases

| Phase | Scope | Model | Review trigger |
|---|---|---|---|
| Phase 1: Domain | Schema, domain model, domain exceptions, domain unit tests | sonnet | reviewer after Phase 1 |
| Phase 2: Application | Port interfaces, UseCase service, application unit tests (mock) | sonnet | reviewer after Phase 2 |
| Phase 3: Adapters & Integration | Inbound/Outbound adapters, events, Testcontainers integration tests | opus | reviewer after Phase 3 |
| Phase 4: Quality & Documentation | Observability, API-SPEC, DECISIONS | haiku | reviewer after Phase 4 → Security handoff |
