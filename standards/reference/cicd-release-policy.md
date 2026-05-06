# CICD Release Policy

## Preconditions
- `feature_gate_check({ name, agent: "cicd" })` passes.
- PRD, API-SPEC, DECISIONS, REVIEW, SECURITY-AUDIT, TEST-PLAN are `approved`.
- P0/P1 bugs are zero.
- Target project git status and remote are checked.

## CI Check
Run the target project's equivalent of:
```bash
./gradlew ktlintCheck detekt test jacocoTestReport
```

For Java/Maven, use project-equivalent checkstyle/test commands.

## Release Artifacts
- `PR-BODY.md`: Conventional Commit title, summary, test plan, risk.
- `RELEASE-NOTE.md`: semantic version, breaking changes, migration, rollback.
- `DEPLOY-CHECKLIST.md`: canary, dashboard, alerts, rollback commands.

## External Actions
`git push`, `gh pr create`, merge, or deploy require explicit user confirmation.

## Required Review
- No hardcoded secret.
- Rollback is executable.
- DB migration has forward and rollback notes.
- Monitoring and alert thresholds are named.
