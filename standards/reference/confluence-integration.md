# Confluence 연동 지침

> 프로젝트별 게시 대상 선택(none/confluence/notion)과 `publish_feature` 는 [notion-integration.md](notion-integration.md) 에 있다.
> Confluence 를 기본 게시 대상으로 두려면 `agent-platform-agent project-publish-set <project_id> --target confluence --confluence-space-key PROJ --confluence-parent-title "Sprint 3"` 후 `agent-platform-agent publish <feature>` 를 쓴다(`confluence_sync_feature` 위임, create-only 그대로).

## 개요

`confluence_fetch_page` / `confluence_list_space` MCP 툴로 Confluence Cloud 문서를 PRD/TASK 생성 전에 참조하고(읽기), `confluence_create_page` / `confluence_update_page` / `confluence_attach_file` / `confluence_sync_feature` / `publish_feature` 로 산출물을 올린다(쓰기). 어느 역할도 자동으로 호출하지 않으며 사용자가 페이지·스페이스를 알려 주거나 게시를 요청할 때만 쓴다. 읽은 본문은 그대로 대화 컨텍스트에 들어가므로 필요한 페이지만 가져온다.

## 필수 환경변수

| 변수 | 설명 |
|---|---|
| `CONFLUENCE_URL` | Atlassian Cloud base URL (예: `https://myorg.atlassian.net`) |
| `CONFLUENCE_EMAIL` | Atlassian 계정 이메일 |
| `CONFLUENCE_API_TOKEN` | Atlassian API Token (Atlassian 계정 보안 설정에서 발급) |

## 사용 절차

사용자가 Confluence 페이지 ID 또는 Space key를 제공하면:

1. **페이지 ID가 있을 경우** — `confluence_fetch_page(page_id)` 호출
2. **Space key가 있을 경우** — `confluence_list_space(space_key)` 로 목록 확인 후 필요한 페이지를 `confluence_fetch_page`로 추가 fetch
3. **requirements 조합** — 아래 형식으로 Confluence 내용을 앞부분에 추가:

```
## Confluence 참고 자료

### {페이지 제목}
{body_markdown}

---

## 사용자 요구사항

{사용자가 입력한 원본 요구사항}
```

4. 조합된 requirements로 현재 세션에서 planner 역할을 수행한다. 사용자가 다른 AI 위임을 명시 요청한 경우에만 `plan_run(requirements=…, cli=…)` 으로 넘긴다.

## 에러 처리

툴이 `{"error": "..."}` 를 반환하면:
- 환경변수 미설정 오류: 사용자에게 설정 방법 안내 후 진행 여부 질의
- 인증 실패: `CONFLUENCE_EMAIL` / `CONFLUENCE_API_TOKEN` 확인 요청
- 페이지/Space 없음: 올바른 ID/key 확인 요청

---

## Write Operations (문서 작성)

### confluence_create_page

```
confluence_create_page(space_key, parent_title, title, body_markdown)
```

Markdown 텍스트를 Confluence storage format으로 자동 변환하여 단일 페이지를 생성한다.
- `parent_title` 은 대상 스페이스 내 **정확히 일치하는** 기존 페이지 제목이어야 한다 (대소문자 구분).
- 같은 제목의 페이지가 이미 존재하면 에러 반환 (덮어쓰지 않음).
- 성공 시 `{"title", "page_id", "url"}` 반환.

### confluence_update_page

```
confluence_update_page(page_id, body_markdown, title="")
```

기존 페이지(또는 draft) 본문을 Markdown 변환 결과로 **교체**한다. `title` 이 비어 있으면 현재 제목을 유지한다(제목 없는 draft 는 제목 필요). `confluence_sync_feature` 의 재게시를 대신하지는 않는다 — 페이지 ID 를 알고 있는 단일 페이지 갱신용이다.
- `page_id` 는 10진 숫자 Confluence ID 여야 한다. 형식이 다르면 호출 없이 `{"error": "invalid page id"}`.
- `current` 페이지와 draft 만 쓴다. 휴지통(`trashed`)·보관(`archived`) 등 그 밖의 상태는 갱신하면 복원되므로 거부하고 `{"error", "page_status"}` 를 돌려준다.
- 409(그 사이 다른 저장)는 페이지를 다시 읽어 **1회만** 재시도한다. 재시도는 그 사이의 편집을 덮어쓴다(버전 이력에는 남는다). `title` 이 비어 있으면 다시 읽은 제목을 쓴다. 두 번째 409 는 `{"error": "Confluence version conflict on <title>", "http_status": 409, "code": "confluence_conflict"}`.
- HTTP 오류는 `http_status` 를 함께 돌려준다(401/404 문구는 이전과 같다).

### confluence_attach_file

```
confluence_attach_file(page_id, file_path)
```

로컬 파일(.drawio/.png 등)을 기존 페이지에 첨부한다. 같은 이름이면 새 버전으로 올라간다.

### confluence_sync_feature

```
confluence_sync_feature(space_key, parent_title, feature_name, overview=True, attach_flow=True, root=None)
```

`root`(프로젝트 경로 또는 등록 ID, 생략 시 활성 target)의 `docs/<type>/<feature_name>/` 를 Confluence 로 올린다. `feature_name`에 `/`가 포함되면 (`<type>/<name>`, 예: `fix/login-bug`) `docs/<feature_name>/`, 아니면 `docs/features/<feature_name>/`.
- `overview=True`(기본): `parent_title` 아래에 **feature 개요 페이지**(제목 = feature 이름)를 먼저 만든다. 내용은 PRD 의 `## 검토 요청` 표, `개요`·`범위`·`API 요약`·`처리 흐름` 절, FLOW.drawio 를 Mermaid 텍스트로 바꾼 코드 블록, 문서 목록이다 — 로컬 `REVIEW-VIEW.html` 과 같은 원본에서 나온다.
- 각 `.md` 는 `file.stem` 을 제목으로 개요 페이지의 **자식 페이지**가 된다 (`overview=False` 면 예전처럼 `parent_title` 바로 아래).
- `attach_flow=True`(기본): `FLOW.drawio` 를 개요 페이지에 **첨부**한다(REST v1 attachment). draw.io 매크로로 인라인 표시하려면 Confluence 에 draw.io 앱이 있어야 하며, 매크로 삽입은 자동화하지 않는다(아래 "필요한 것").
- 변환: 제목·문단·목록·코드 외에 **표 → Confluence 표**, **`- [ ]` → task list**, **인용 → blockquote** 가 지원된다. Mermaid 코드는 `language=mermaid` 코드 매크로(텍스트)로 들어간다.
- 개별 파일 실패 시에도 나머지 파일은 계속 처리. 개요 페이지 생성 실패 시 자식 페이지는 `parent_title` 아래로 간다.
- 보내지 않는 파일: 심링크이거나 feature 디렉터리 밖을 가리키는 `.md`/`FLOW.drawio`, 그리고 고신뢰 비밀 패턴(PEM private key 헤더, AWS access key, GitHub·GitLab·Notion·Slack·Atlassian 토큰, Google API key, OpenAI·Anthropic `sk-` 키, Stripe 키, JWT, URL 안의 `user:pass@` 형태)이 있는 파일. `results[]`(또는 `attachments[]`)에 `{"file", "status": "skipped", "error": "symlink or outside feature directory" | "secret pattern detected: <kind>, …"}` 로 남고 값은 어디에도 나오지 않는다. 비밀이 있는 `PRD.md` 는 개요에 `_PRD.md 제외 (비밀값 의심)_` 로, 그런 FLOW 는 흐름 절 없이 나온다. `publish --dry-run` 의 `skipped` 목록과 같다. 일반 파일 출력은 바뀌지 않는다. 일반 문장(`password: 8자 이상`, `Bearer <token>`, `ghp_xxx`, `postgres://user:<password>@db` 같은 예시)은 걸리지 않는다.
- `FLOW.drawio` 첨부는 검사할 수 없으면 보내지 않는다. UTF-8 이 아니거나 XML 이 아니거나 압축 페이지면 `attachments[]` 에 `skipped`(`cannot scan for secrets: not UTF-8 text` | `not draw.io XML` | `compressed diagram`)로 남는다. diagrams.net 에서 압축 해제 후 저장하면 첨부된다. `publish --dry-run` 결과의 `attachments`·`skipped_reasons` 로 미리 볼 수 있다.
- 게시할 수 있는 `.md` 가 하나도 없으면(전부 skipped) 원격 호출 없이 `{"feature", "results": [skipped…], "warning": "No publishable .md files in …"}` 를 돌려준다. feature 디렉터리가 심링크이거나 이름에 `..` 가 있으면 `{"error"}` 다. UTF-8 이 아닌 `.md` 는 그 파일만 `error` 다.
- 반환: `{"feature", "overview": {"title","status","page_id","url"|"error"}, "attachments": [{"file","status"}], "results": [{"file", "status":"created"|"error"|"skipped", "url"|"error"}]}`
- **생성 전용**이다. 같은 제목이 이미 있으면 400 으로 실패한다(갱신·덮어쓰기 없음). 재업로드는 기존 페이지를 지우거나 `parent_title` 을 바꿔서 한다.

### publish_spec (SPEC·INDEX 페이지)

```
publish_spec(slug=None, index=False, allow_draft=False, dry_run=False, root=None, adopt_from=None, confirm=False)   # MCP
agent-platform-agent publish --spec <slug> [--allow-draft] [--adopt-from OLD_ID] [--dry-run] [--root R]  # CLI
agent-platform-agent publish --spec-index [--adopt-from OLD_ID] [--dry-run] [--root R]
```

- 프로젝트 `publish.target` 이 confluence 일 때 `publish.confluence.{space_key, parent_title}` 의 부모 페이지 **직계 자식**으로 SPEC 페이지(제목 = SPEC `title`) 또는 INDEX 페이지(`<project_id> 기능 목록`)를 만들거나 갱신한다. none·미등록 프로젝트는 원격 호출 없이 `skipped` 다. 위 `confluence_sync_feature` 와 달리 **upsert** 다.
- 소유 표시: 페이지 속성(content property) `agent-platform` = `{project_id, slug}` 와 탐색용 label `agent-platform-spec`. 판정은 속성 값으로만 한다. 소유 표시가 있는 페이지만 갱신(버전 +1, 409 는 재조회 후 1회 재시도)한다.
- 순서: PublishMap(`.local/publish/<project_id>.json` 의 `specs.<slug>`/`index`) 의 page_id → 부모 직계 자식의 같은 제목 → 생성. 같은 제목인데 소유 표시가 없으면 `failed`(`code: title_conflict`). 스페이스 다른 곳이나 휴지통에 같은 제목이 있으면 Confluence 가 생성을 거부해 `failed`(`code: duplicate_title`, `http_status: 400`)다. 휴지통 페이지는 복원하지 않고, 어떤 경우에도 기존 페이지를 덮어쓰지 않는다. 휴지통을 비우거나 SPEC `title` 을 바꾼 뒤 다시 게시한다.
- 매핑은 이 함수가 직접 읽고 쓴다(부모 페이지 id 를 알기 때문). 매핑이 없어도 소유 표시 검색으로 같은 페이지에 다시 연결된다.
- 업로드 직전에 SPEC.md 를 다시 읽고, 보낼 제목+본문 전체를 비밀 패턴 검사한다. 걸리면 원격 호출 0회로 `skipped`(`secret pattern detected: <kind>`)다. 심링크·경로 이탈 SPEC 은 `skipped`, approved 가 아닌 SPEC 은 `--allow-draft` 없이는 `skipped`(`spec is not approved`)다.
- 다른 project_id 의 같은 slug 표시는 사용자가 동의했을 때만 채택한다. 동의는 `--adopt-from <old_project_id>`(MCP `adopt_from`) 또는 현재 프로젝트 registry 레코드의 `previous_ids` 목록(읽기만 한다)이다. 채택하면 표시를 새 project_id 로 다시 쓰고 `result.adopted_from` 으로 알린다. 동의가 없으면 쓰지 않고 `failed`(`code: foreign_owner`, `result.found_project_id`)다. 이 기계 registry 에 없다는 것은 동의가 아니다(registry 는 기계마다 다르다). 같은 표시가 정확히 맞는 페이지가 있으면 그 페이지가 채택 후보보다 우선한다. dry-run 은 원격 호출을 하지 않으므로 title_conflict·foreign_owner·채택 여부를 보여 주지 못한다(`result.ownership`); 동의한 ID 만 `result.may_adopt` 로 보인다.
- SPEC 페이지 §6 변경 이력은 원격 INDEX 규칙을 따른다: fix/·hotfix/ 행은 `날짜 | (비공개)` 로 바꾸고 요약·PR 을 보내지 않는다. 다른 행의 PR 칸은 저장소 URL 없이 `#n` 만 보낸다. §6 제목은 있는데 표를 읽을 수 없으면 `skipped`(`code: history_unparsed`)다. 원격 INDEX 는 approved SPEC 만 싣는다(승인 전 SPEC 과 그 작업은 건수만 적는다).
- MCP `publish_spec` 은 dry-run 이 아니면 `confirm=true` 가 있어야 보낸다. 없으면 아무것도 보내지 않고 `status: confirmation_required` 와 계획(제목·대상·부모)을 돌려준다. `allow_draft` 는 dry-run 이어도 confirm 이 필요하다. CLI 는 사람이 직접 실행하므로 confirm 이 없다.
- exit code(`--spec`/`--spec-index`): `published`·`planned` 0, `skipped`(대상 none·draft·비밀값·없는 SPEC 등) 3, `failed`·`{"error"}` 1. `publish <feature>` 의 exit code 는 바뀌지 않았다(skipped 0).
- 결과: `{"feature": "specs/<slug>"|"specs/INDEX", "project_id", "target": "confluence", "status": "skipped"|"planned"|"published"|"failed", "reason", "result": {"page_id", "url", "action": "created"|"updated", "version"?, "warning"?, "adopted_from"?} | {"code"?, "http_status"?, "found_project_id"?}}` (MCP 는 `confirmation_required` 도 있다)

### 결과 페이지 구조

```
Sprint 3 (parent_title)
└── certificate-validation-notification   ← 개요: 검토 요청 · 개요 · 범위 · API 요약 · 흐름(Mermaid 텍스트) · 📎 FLOW.drawio
    ├── PRD
    ├── TASK
    ├── API-SPEC
    ├── REVIEW
    └── …
```

### Confluence 에 필요한 것 (체크리스트)

| 항목 | 필요 | 비고 |
|---|---|---|
| `CONFLUENCE_URL` / `CONFLUENCE_EMAIL` / `CONFLUENCE_API_TOKEN` | 필수 | Atlassian Cloud. 토큰은 계정 보안 설정에서 발급, `.env` 에만 둔다 |
| Space key 와 `parent_title` | 필수 | 부모 페이지는 **정확한 제목**으로 미리 존재해야 한다 (대소문자 구분) |
| 쓰기 권한 | 필수 | 해당 스페이스에 페이지 생성·첨부 업로드 권한 |
| feature 이름과 같은 제목의 페이지가 없을 것 | 필수 | 생성 전용이라 중복 제목은 실패 |
| draw.io for Confluence 앱 | 선택 | 첨부된 FLOW.drawio 를 페이지 안에서 그리려면 필요. 없으면 첨부 다운로드 + Mermaid 텍스트 뷰로 본다 |
| Mermaid 렌더링 앱 | 선택 | 없으면 Mermaid 는 코드 블록 텍스트로 보인다(설계상 허용) |
| HTML 매크로 | 불필요 | `REVIEW-VIEW.html` 은 Confluence 에 올리지 않는다. 같은 내용을 페이지로 변환한다 |

### 에러 케이스 (Write)

| 조건 | 반환 |
|---|---|
| 부모 페이지 없음 | `{"error": "Page '{title}' not found in space ..."}` |
| 중복 페이지 제목 | `{"error": "Confluence rejected page creation: ...", "http_status": 400, "code": "duplicate_title"}` (400 상세 포함. 제목 중복이 아닌 400 에는 `code` 가 없다) |
| active project 미설정 | `{"error": "No active project. Run project_init, project_use, or pass root."}` |
| feature 디렉터리 없음 | `{"error": "Feature directory not found: ..."}` |
