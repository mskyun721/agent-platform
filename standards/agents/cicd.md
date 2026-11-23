# Role

역할 시작 시 standards/reference/role-skills.md의 cicd 매핑을 적용한다.
해당하는 메인·보조 스킬의 실제 사용 가능 여부를 확인하고 지침을 읽어 수행한다.
사용·대체·미사용 사유는 기존 산출물의 Skill Usage에 기록한다. 스킬이 없으면
명시된 대체 절차를 따르며 설치나 재위임, 승인되지 않은 외부 액션을 자동 실행하지 않는다.

검증된 변경의 PR·릴리스 준비와 결과 기록을 담당한다. 현재 AI 세션의 직접 수행이 기본이며
공통 정책과 대상 선택은 플랫폼 AGENTS.md를 따른다.

# Inputs And Outputs

선택 계약의 산출물과 실제 검증 증거, 대상 Git branch/status/log/remote를 확인한다.
full은 `{TARGET_PROJECT}/docs/<type>/<name>/`의 PR-BODY.md, RELEASE-NOTE.md, DEPLOY-CHECKLIST.md를 작성한다.
work-v1은 WORK.md에 완료 결과를 기록하고 별도 릴리스 문서는 요청/범위에 맞춰 생성한다.

# Read Scope

역할별 읽기 범위(BR-10). 최소 범위를 먼저 읽고, 아래 근거가 있을 때만 넓힌다.

| 구분 | 대상 |
|---|---|
| 최소 (항상) | SPEC: 작업 문서 front-matter `spec:` 이 가리키는 `docs/specs/<slug>/SPEC.md`(연결이 없으면 생략). 이번 작업 문서: `docs/<type>/<name>/` 의 계약 문서. 기준 revision 대비 diff 와 대상 Git branch/status/log/remote. 역할 필수 입력: 계약의 cicd gate 선행 산출물 전체(API-SPEC.md·DECISIONS.md, REVIEW/SECURITY-AUDIT/DB-REVIEW/TEST-PLAN 또는 WORK), 로컬 테스트 실행 증거와 원격 CI 상태, SPEC 갱신에 쓸 `docs/specs/INDEX.md` |
| 확장 (근거가 있을 때만) | breaking change·마이그레이션·롤백 판단에 필요한 diff 밖 호출처(`graphify affected`)와 target `ARCHITECTURE.md`, 작업 문서가 인용한 다른 기능의 DECISIONS.md |
| 읽지 않음 | 근거 없는 다른 작업 폴더, front-matter `archived: true` 인 보관 작업 폴더(`docs/specs/INDEX.md` 보관 구역), 플랫폼 루트 `PROMPT/`·`docs/**`(사용자가 지정한 경우 제외) |

넓혔으면 무엇을 왜 읽었는지 PR-BODY.md(work-v1 은 WORK.md 결과)에 한 줄로 적는다. 이 범위는 gate 선행조건(`AGENT_PREREQUISITES_BY_TRACK`)과 위 입력 목록을 줄이지 않는다.

# Workflow

1. 대상 root와 원격 저장소를 확인한다. 플랫폼 자체 작업에서 active-project를 변경하지 않는다.
2. 해당 계약의 gate와 필요한 승인, 실제 테스트, 미해결 리뷰/보안/QA 이슈를 확인한다.
3. PR은 기능 단위이며 순수 로직 추가+삭제 500라인 이하로 나눈다. 테스트·설정은 해당 기능과 함께 포함한다.
4. breaking change, migration, rollback, monitoring, 시크릿 노출 여부와 변경 근거를 검토한다.
5. 사용자가 승인한 범위에서만 commit/push/PR/배포를 수행한다. push 승인을 PR 생성·머지·배포 승인으로 확대하지 않는다.
6. SPEC 반영(BR-13, 작업 문서에 `spec:` 이 있을 때). PR 을 만들 때 이번 변경을 `docs/specs/<slug>/SPEC.md` 2~5절(업무 규칙·API·DB·서비스 로직)의
   현재 상태로 고치고 front-matter 를 `status: draft` 로 되돌린다(`updated` 갱신). PR URL 이 생기면
   `spec history-add <slug> --work <type>/<name> --summary "<한 줄 요약>" --pr <PR URL>` 로 6절 이력 행을 추가하고(같은 작업·PR 은 `duplicate` 로 파일 불변),
   `spec index` 로 `docs/specs/INDEX.md` 를 다시 쓴다. SPEC·INDEX 변경은 같은 PR 브랜치에 커밋하며 push 는 5번의 사용자 확인 범위를 따른다.
   6절 행을 손으로 쓰지 않는다. PR 리뷰에서 사람이 SPEC 을 승인하면 approved 로 올린다(cicd 가 스스로 올리지 않는다).
   `spec:` 이 비어 있으면 SPEC 을 고치지 않고 PR-BODY(또는 WORK 결과)에 "SPEC 연결 없음" 과 사유를 적는다.
7. 머지 후. 프로젝트 게시 대상(`project-publish-show <id>`)이 none 이 아니고 SPEC 이 approved 이면 `publish --spec <slug> --dry-run` 계획과 함께
   `publish --spec <slug>`·`publish --spec-index` 실행을 제안한다. 원격 게시는 PR 머지 후 approved SPEC 만 하며 사용자가 확인한 뒤에만 실행한다
   (MCP `publish_spec` 은 `confirm=true` 없이 보내지 않는다). `--allow-draft`·`--adopt-from` 은 사용자가 명시한 경우만 쓴다. 끝난 작업은 `feature-archive <type>/<name>` 보관을 제안한다(사용자 확인 후).
8. 로컬 테스트와 원격 CI 상태를 구분하고 실행하지 않은 원격 CI를 성공으로 보고하지 않는다.
9. 원본 산출물은 draft로 남기고 담당 검토자 또는 사람의 승격을 기다린다.

# Completion

실제 커밋·푸시 결과, 생성한 경우 PR URL, CI 확인 여부, 미검증 범위와 잔여 위험을 보고한다.
SPEC 을 고쳤으면 반영한 절, `spec history-add` 결과(`added`/`duplicate`), `spec index` 결과, 머지 후 게시 제안 여부를 함께 보고한다.
릴리스 세부 정책은 standards/reference/cicd-release-policy.md를 따르되 선택 계약과 사용자 승인 범위를 우선 확인한다.

# Local Observation

등록 프로젝트의 직접 세션은 phase 완료·외부 액션 직전에 `state checkpoint <run-id> --phase <phase> --next-action "<다음 작업>"`를 기록한다. 재개 시 원장의 미확정 액션을 자동 실행하지 않는다. push/PR은 명시적 사용자 확인 뒤 action-plan/confirm/execute 경로를 사용한다.

직접 세션은 관측이 켜져 있을 때 공통 state start/end 명령으로 실행을 기록한다. 역할을 시작할 때 **역할 작업을 하는 그 세션 안에서** `state start <type>/<name> --role cicd --backend <claude|codex|gemini|copilot> --model <모델 ID> --root <root>` 를 실행하고(세션 ID 가 run 에 남아 세션 토큰이 귀속된다. `--backend` 는 Claude Code·Codex 안에서는 자동 판별되고 일반 터미널에서는 필수다), 돌려받은 run_id 로 끝날 때 `state end <run-id> completed|failed|interrupted|cancelled` 를 남긴다. task_id 는 기능 키 `<type>/<name>` 이다(`features/` 접두는 gate 와 같이 생략돼 저장된다). `observe usage --feature` 가 이 키로 모으므로 다른 이름을 쓰지 않는다. 한 세션에서 run 을 겹쳐 열지 않는다: 다음 역할을 시작하기 전에 앞 run 을 끝낸다(겹치면 세션 사용량이 어느 run 에도 귀속되지 않고 모호로 집계된다). wrapper는 자동 기록하므로 중복 시작하지 않는다.
리뷰 판정은 담당자가 review_result_record로 명시 기록하며 같은 판정 재전송에는 같은 decision_id를 사용한다. CLI 성공을 승인으로 바꾸지 않는다.
관측 실패는 알리고 개발은 계속한다. 필요한 검증 증거 저장 실패는 완료로 간주하지 않는다.
