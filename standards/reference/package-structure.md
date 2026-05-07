# Hexagonal Package Structure

Applies to all backend projects (Kotlin + Java).

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

## Rules

- `domain/` must not import Spring, JPA, R2DBC, or any adapter package.
- Domain entity and persistence entity are **separate** models — never share the same class.
- Dependency direction: `adapter` → `application` → `domain` (never reversed).
