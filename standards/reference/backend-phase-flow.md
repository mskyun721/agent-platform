# Backend Phase Flow

Backend uses Claude Code by default and works in target project root.

## Language Detection
| Signal | Language / build |
|---|---|
| `src/main/kotlin/` | Kotlin |
| `src/main/java/` | Java |
| `build.gradle.kts` | Gradle Kotlin DSL |
| `pom.xml` | Maven |

## Per-Phase Loop
Each phase follows this cycle before moving to the next:

1. `superpowers:test-driven-development` — write failing test first.
2. Implement the phase.
3. Run language-specific lint/test.
4. `superpowers:verification-before-completion` — confirm evidence before claiming done.
5. Update TASK checkbox, commit with phase scope, record commit hash in `commit:` field.
6. Dispatch `reviewer` agent scoped to this phase's commits (Codex + Gemini cross-review).
7. If HIGH issues found → fix and add fix commit, then re-run reviewer for the phase.
8. Only proceed to the next phase when reviewer reports no HIGH issues.

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
