# Confluence 연동 지침 (Planner Agent)

> 프로젝트별 게시 대상 선택(none/confluence/notion)과 `publish_feature` 는 [notion-integration.md](notion-integration.md) 에 있다.
> Confluence 를 기본 게시 대상으로 두려면 `agent-platform-agent project-publish-set <project_id> --target confluence --confluence-space-key PROJ --confluence-parent-title "Sprint 3"` 후 `agent-platform-agent publish <feature>` 를 쓴다(`confluence_sync_feature` 위임, create-only 그대로).

## 개요

`confluence_fetch_page` / `confluence_list_space` MCP 툴을 사용해 Confluence Cloud 문서를 PRD/TASK 생성 전에 참조할 수 있다.

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

4. 조합된 requirements를 `plan_run`의 `requirements` 파라미터로 전달 (`cli`는 codex)

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

### confluence_sync_feature

```
confluence_sync_feature(space_key, parent_title, feature_name, overview=True, attach_flow=True)
```

활성 target project(`TARGET_PROJECT_ROOT` 또는 `.active-project`)의 `docs/<type>/<feature_name>/` 를 Confluence 로 올린다. `feature_name`에 `/`가 포함되면 (`<type>/<name>`, 예: `fix/login-bug`) `docs/<feature_name>/`, 아니면 `docs/features/<feature_name>/`.
- `overview=True`(기본): `parent_title` 아래에 **feature 개요 페이지**(제목 = feature 이름)를 먼저 만든다. 내용은 PRD 의 `## 검토 요청` 표, `개요`·`범위`·`API 요약`·`처리 흐름` 절, FLOW.drawio 를 Mermaid 텍스트로 바꾼 코드 블록, 문서 목록이다 — 로컬 `REVIEW-VIEW.html` 과 같은 원본에서 나온다.
- 각 `.md` 는 `file.stem` 을 제목으로 개요 페이지의 **자식 페이지**가 된다 (`overview=False` 면 예전처럼 `parent_title` 바로 아래).
- `attach_flow=True`(기본): `FLOW.drawio` 를 개요 페이지에 **첨부**한다(REST v1 attachment). draw.io 매크로로 인라인 표시하려면 Confluence 에 draw.io 앱이 있어야 하며, 매크로 삽입은 자동화하지 않는다(아래 "필요한 것").
- 변환: 제목·문단·목록·코드 외에 **표 → Confluence 표**, **`- [ ]` → task list**, **인용 → blockquote** 가 지원된다. Mermaid 코드는 `language=mermaid` 코드 매크로(텍스트)로 들어간다.
- 개별 파일 실패 시에도 나머지 파일은 계속 처리. 개요 페이지 생성 실패 시 자식 페이지는 `parent_title` 아래로 간다.
- 보내지 않는 파일: 심링크이거나 feature 디렉터리 밖을 가리키는 `.md`/`FLOW.drawio`, 그리고 고신뢰 비밀 패턴(PEM private key 헤더, AWS access key, GitHub·Notion·Slack·Atlassian 토큰 형태)이 있는 파일. `results[]`(또는 `attachments[]`)에 `{"file", "status": "skipped", "error": "symlink or outside feature directory" | "secret pattern detected: <kind>, …"}` 로 남고 값은 어디에도 나오지 않는다. 비밀이 있는 `PRD.md` 는 개요에 `_PRD.md 제외 (비밀값 의심)_` 로, 그런 FLOW 는 흐름 절 없이 나온다. `publish --dry-run` 의 `skipped` 목록과 같다. 일반 파일 출력은 바뀌지 않는다. 일반 문장(`password: 8자 이상`, `Bearer <token>`, `ghp_xxx` 같은 예시)은 걸리지 않는다.
- `FLOW.drawio` 첨부는 검사할 수 없으면 보내지 않는다. UTF-8 이 아니거나 XML 이 아니거나 압축 페이지면 `attachments[]` 에 `skipped`(`cannot scan for secrets: not UTF-8 text` | `not draw.io XML` | `compressed diagram`)로 남는다. diagrams.net 에서 압축 해제 후 저장하면 첨부된다. `publish --dry-run` 결과의 `attachments`·`skipped_reasons` 로 미리 볼 수 있다.
- 게시할 수 있는 `.md` 가 하나도 없으면(전부 skipped) 원격 호출 없이 `{"feature", "results": [skipped…], "warning": "No publishable .md files in …"}` 를 돌려준다. feature 디렉터리가 심링크이거나 이름에 `..` 가 있으면 `{"error"}` 다. UTF-8 이 아닌 `.md` 는 그 파일만 `error` 다.
- 반환: `{"feature", "overview": {"title","status","page_id","url"|"error"}, "attachments": [{"file","status"}], "results": [{"file", "status":"created"|"error"|"skipped", "url"|"error"}]}`
- **생성 전용**이다. 같은 제목이 이미 있으면 400 으로 실패한다(갱신·덮어쓰기 없음). 재업로드는 기존 페이지를 지우거나 `parent_title` 을 바꿔서 한다.

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
| 중복 페이지 제목 | `{"error": "Confluence rejected page creation: ..."}` (400 상세 포함) |
| active project 미설정 | `{"error": "No active project. Run project_init or set TARGET_PROJECT_ROOT."}` |
| feature 디렉터리 없음 | `{"error": "Feature directory not found: ..."}` |
