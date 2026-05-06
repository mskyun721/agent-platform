# Backend Phase Flow

Backend uses Claude Code by default and works in target project root.

## Language Detection
| Signal | Language / build |
|---|---|
| `src/main/kotlin/` | Kotlin |
| `src/main/java/` | Java |
| `build.gradle.kts` | Gradle Kotlin DSL |
| `pom.xml` | Maven |

## Per-Phase Completion
1. Update TASK checkbox.
2. Run language-specific lint/test.
3. Commit with phase scope.
4. Record commit hash in TASK `commit:` field.

## Package Rule
```text
{base-package}
├── common/
│   ├── constant/
│   ├── enum/
│   ├── extension/     # [Kotlin] extension functions / [Java] utility classes
│   └── ...
├── config/
└── {domain}/
    ├── domain/
    ├── application/
    │   ├── port/in/
    │   ├── port/out/
    │   └── service/
    └── adapter/
        ├── in/web/
        └── out/persistence/


Domain must not import Spring/JPA/R2DBC or adapters. Domain entity and persistence entity are separate models.
