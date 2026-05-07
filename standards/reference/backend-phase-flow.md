# Backend Phase Flow

Backend uses Claude Code by default and works in target project root.

## Language Detection
| Signal | Language / build |
|---|---|
| `src/main/kotlin/` | Kotlin |
| `src/main/java/` | Java |
| `build.gradle.kts` | Gradle Kotlin DSL |
| `pom.xml` | Maven |

## Phases

| Phase | Scope | Model | Review trigger |
|---|---|---|---|
| Phase 1: Domain | Schema, domain model, domain exceptions, domain unit tests | sonnet | reviewer after Phase 1 |
| Phase 2: Application | Port interfaces, UseCase service, application unit tests (mock) | sonnet | reviewer after Phase 2 |
| Phase 3: Adapters & Integration | Inbound/Outbound adapters, events, Testcontainers integration tests | opus | reviewer after Phase 3 |
| Phase 4: Quality & Documentation | Observability, API-SPEC, DECISIONS | haiku | reviewer after Phase 4 → Security handoff |

Orchestrator spawns Backend once per phase with the designated model.
Backend accepts `[PHASE:N]` prefix in the prompt to scope work to that phase only.

## Per-Phase Loop
Each phase follows this cycle:

1. `superpowers:test-driven-development` — write failing test first.
2. Implement the phase tasks.
3. Run language-specific lint/test.
4. `superpowers:verification-before-completion` — confirm evidence before claiming done.
5. Update TASK checkbox, commit with phase scope, record commit hash in `commit:` field.
6. Orchestrator dispatches `reviewer` agent for this phase.
7. If HIGH issues → backend fix commit → reviewer re-run.
8. Proceed to next phase only when reviewer reports no HIGH issues.

## Package Structure

→ `standards/reference/package-structure.md`
