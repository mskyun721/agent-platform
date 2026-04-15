---
argument-hint: "<project-name> <package-path> [java=N] [kotlin=X.Y.Z] [spring-boot=X.Y.Z] [gradle=X.Y.Z] [deps=id1,id2,...] [target=/path]"
---

Parse `$ARGUMENTS` and call the `project_init` MCP tool.

## Argument format

```
<project-name> <package-path> [key=value ...]
```

| Token | Maps to |
|---|---|
| 1st positional | `project_name` |
| 2nd positional | `package_path` |
| `java=N` | `java_version` (int) |
| `kotlin=X.Y.Z` | `kotlin_version` |
| `spring-boot=X.Y.Z` | `spring_boot_version` |
| `gradle=X.Y.Z` | `gradle_version` |
| `deps=id1,id2,...` | `dependencies` (split by comma) |
| `target=/path` | `target_dir` |

## Steps

1. Parse `$ARGUMENTS` to extract positional and keyword tokens.
2. Validate that at least two positional arguments are present; if not, explain the usage and stop.
3. Determine `target_dir`:
   - If `target=...` was provided in the arguments, use that value.
   - Otherwise, use the **parent of the current working directory** (i.e. run `pwd` via Bash, then take its parent). Pass this absolute path as `target_dir` explicitly — do NOT omit it, because the MCP server process may run from a different directory.
4. Call `mcp__agent-platform__project_init` with the parsed parameters including the resolved `target_dir`.
5. Report the result: destination path, detected values, and applied changes.

## Examples

```
/init-project my-service com.example.myservice
/init-project my-service com.example.myservice java=21 kotlin=2.1.20 spring-boot=3.4.5 gradle=8.13
/init-project my-service com.example.myservice deps=webflux,r2dbc,security,validation,actuator
/init-project my-service com.example.myservice target=/Users/me/Projects
```

## Allowed dependency IDs

`web`, `webflux`, `r2dbc`, `jpa`, `security`, `validation`, `actuator`, `cache`,
`redis`, `postgresql`, `r2dbc-postgresql`, `h2`, `flyway`, `kafka`,
`test`, `mockk`, `testcontainers`