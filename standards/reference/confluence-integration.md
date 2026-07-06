# Confluence 연동 지침 (Planner Agent)

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

4. 조합된 requirements를 `plan_run`의 `requirements` 파라미터로 전달 (`cli`로 codex/gemini 선택)

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
confluence_sync_feature(space_key, parent_title, feature_name)
```

활성 target project(`TARGET_PROJECT_ROOT` 또는 `.active-project`)의 `docs/<type>/<feature_name>/` 아래 모든 `.md` 파일을 Confluence 페이지로 일괄 업로드한다. `feature_name`에 `/`가 포함되면 (`<type>/<name>`, 예: `fix/login-bug`) `docs/<feature_name>/`, 아니면 `docs/features/<feature_name>/`.
- 각 파일은 `file.stem`(확장자 제외)을 페이지 제목으로 사용: `PRD.md` → `PRD` 페이지
- 개별 파일 실패 시에도 나머지 파일은 계속 처리
- 반환: `{"feature": name, "results": [{"file", "status":"created"|"error", "url"|"error"}]}`

### 결과 페이지 구조 예시

```
Sprint 3 (parent_title)
├── PRD
├── TASK
├── REVIEW
├── SECURITY-AUDIT
└── TEST-PLAN
```

### 에러 케이스 (Write)

| 조건 | 반환 |
|---|---|
| 부모 페이지 없음 | `{"error": "Page '{title}' not found in space ..."}` |
| 중복 페이지 제목 | `{"error": "Confluence rejected page creation: ..."}` (400 상세 포함) |
| active project 미설정 | `{"error": "No active project. Run project_init or set TARGET_PROJECT_ROOT."}` |
| feature 디렉터리 없음 | `{"error": "Feature directory not found: ..."}` |
