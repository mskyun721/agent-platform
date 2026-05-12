# Hexagonal Package Structure

## Layout

```text
{base-package}/
├── common/
│   ├── constant/
│   ├── enum/
│   ├── extension/     # [Kotlin] extension functions / [Java] utility classes
│   └── ...
├── config/
└── {domain}/
    ├── domain/                  # pure domain model — no infra dependency
    ├── application/
    │   ├── port/in/             # UseCase interfaces
    │   ├── port/out/            # Repository interfaces
    │   └── service/             # UseCase implementations
    └── adapter/
        ├── in/web/              # [Kotlin] coRouter Router + Handler / [Java] @RestController
        └── out/persistence/     # R2DBC Repository implementations
```

## Hexagonal Architecture Rules

- The `domain/` package must remain pure.
    - The domain layer must be independent of frameworks and infrastructure.

- Domain entities and persistence entities must be separate models.
    - Never use the same class as both a business model and a database model.

- Dependencies must always point inward:
    - `adapter` → `application` → `domain`
    - Inner layers must not know about outer layers.

---

### Allowed Dependency Direction

- `adapter.in.web` → `application.port.in`
    - Controllers, handlers, and routers call use case interfaces.

- `application.service` → `application.port.in`
    - Application services implement inbound use case interfaces.

- `application.service` → `application.port.out`
    - Application services depend on outbound port interfaces, not infrastructure implementations.

- `application.service` → `domain`
    - Application services use domain models and domain rules to execute use cases.

- `adapter.out.persistence` → `application.port.out`
    - Persistence adapters implement outbound port interfaces.

- `adapter.out.persistence` → `domain`
    - Persistence adapters map between domain models and persistence entities.

---

### Implementation Rules

- `application.service` implements inbound ports defined in `application.port.in`.
    - Inbound ports define what the application can do.

- `adapter.out.persistence` implements outbound ports defined in `application.port.out`.
    - Outbound ports define what the application needs from external systems.

---

### Forbidden Dependency Direction

- `application` → `adapter.in` ❌
    - Use cases must not know how they are triggered.

- `application` → `adapter.out` ❌
    - Use cases must not depend on concrete infrastructure implementations.

- `domain` → `application` ❌
    - Domain models must not know about use cases, ports, or application services.

- `domain` → `adapter` ❌
    - Domain models must not know about web, database, messaging, or external APIs.

- `domain` → Spring / JPA / R2DBC ❌
    - Domain models must not depend on framework-specific annotations or APIs.

- `adapter.in.web` → `adapter.out.persistence` ❌
    - Controllers, handlers, and routers must not directly access repositories or persistence adapters.

---

### Model Placement Rules

- Web request and response DTOs belong to `adapter.in.web`.
    - HTTP-specific models must not leak into the application or domain layer.

- Command and result models belong to `application.port.in`.
    - Application-level input and output models must not be tied to HTTP.

- Domain models belong to `domain`.
    - Domain models contain business concepts, invariants, and domain behavior.

- Persistence entities belong to `adapter.out.persistence`.
    - Database-specific models must be mapped to and from domain models.

- Repository interfaces for use cases belong to `application.port.out`.
    - The application defines the persistence needs as interfaces.

- Repository implementations belong to `adapter.out.persistence`.
    - Infrastructure adapters provide the actual database implementation.

---

### Recommended Call Flow

```text
HTTP Request
  → adapter.in.web
  → application.port.in
  → application.service
  → domain
  → application.port.out
  → adapter.out.persistence
  → DB
