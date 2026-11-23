# Notion 게시와 프로젝트별 게시 대상

## 개요

feature 산출물(`docs/<type>/<name>/*.md`)을 Notion 페이지로 게시한다. 프로젝트마다 게시 대상을
`none`(기본) / `confluence` / `notion` 중에서 고른다. 회사 PC 는 confluence, 개인 PC 는 notion 처럼
머신별로 따로 둘 수 있다(설정은 ignored `.agent-projects.json`).

- 게시는 **명시 호출로만** 일어난다: MCP `publish_feature` / `notion_sync_feature`, CLI `publish`.
  handoff·gate·역할 wrapper 는 게시를 호출하지 않는다.
- 대상을 정하지 않은 프로젝트(미등록, `publish` 없음, `target=none`)는 `status: skipped` 이고 원격 호출이 없다.
- Notion 은 멱등 갱신(upsert)한다. 다시 실행하면 같은 페이지의 본문이 바뀐다. Confluence 는 기존과 같이
  생성만 한다(`confluence-integration.md`).

## 설정

1. Notion 에서 internal integration 을 만든다(Settings → Connections → Develop or manage integrations).
   발급된 secret(`ntn_…` 또는 `secret_…`)을 플랫폼 루트 `.env` 에 넣는다.

   ```bash
   NOTION_TOKEN="ntn_..."
   ```

   토큰은 env 로만 받는다. 도구 인자·설정 파일·결과·오류 메시지에 들어가지 않는다.
2. 게시할 부모 페이지를 열고 `…` → Connections 에서 그 integration 을 연결한다. 연결하지 않으면
   `Notion page not shared with integration or not found` 가 난다.
3. 부모 페이지 ID(URL 끝 32자 hex, 하이픈 허용)를 프로젝트에 설정한다. env 기본값은 없다
   (회사 프로젝트가 개인 Notion 으로 잘못 게시되지 않도록).

   ```bash
   agent-platform-agent project-register /path/to/service --project-id my-svc   # 등록 안 했으면
   agent-platform-agent project-publish-set my-svc --target notion --notion-parent-page-id 1f2e3d4c5b6a79881726354433221100
   agent-platform-agent project-publish-show my-svc
   ```

   Confluence 를 고를 때는 `--target confluence --confluence-space-key PROJ --confluence-parent-title "Sprint 3"`,
   끌 때는 `--target none`. `project-list` 에도 `publish` 가 보인다(ID 만).

등록하지 않은 타겟(`.active-project` 경로만 있는 경우)은 게시 대상이 none 이다. `publish` 는 skipped 이고
`notion_sync_feature` 는 `parent_page_id` 를 직접 줘도 거부한다(`project publish target is none; notion publish refused`).
대상이 confluence 인 프로젝트도 같다. Notion 에 게시하려면 `project-register` 로 등록하고 `--target notion` 으로 설정한다.
대상이 notion 이면 `parent_page_id` 인자로 설정과 다른 부모를 줄 수 있다. 플랫폼 자체 개선도 플랫폼 루트를 등록해 같은 방식으로 설정한다.

## 사용

```bash
agent-platform-agent publish payment-cancel --root my-svc --dry-run   # 원격 호출·토큰 없이 계획만
agent-platform-agent publish payment-cancel --root my-svc
```

- `publish` 는 stdout 에 JSON 을 쓰고 `status` 가 `skipped`/`planned`/`published` 면 exit 0, `partial`/`failed`
  또는 `{"error"}` 면 exit 1 이다.
- MCP: `publish_feature(feature, root=None, dry_run=False)`,
  `notion_sync_feature(feature_name, parent_page_id=None, root=None, dry_run=False)`.

## SPEC·INDEX 게시 (publish_spec)

```bash
agent-platform-agent publish --spec payment --root my-svc --dry-run   # 원격 호출·토큰 없이 계획만
agent-platform-agent publish --spec payment --root my-svc             # approved SPEC 만 (--allow-draft 로 draft 도)
agent-platform-agent publish --spec-index --root my-svc               # 원격 INDEX 페이지 "<project_id> 기능 목록"
```

- MCP: `publish_spec(slug=None, index=False, allow_draft=False, dry_run=False, root=None, adopt_from=None, confirm=False)` (slug 와 index 중 하나만). MCP `publish_spec` 은 dry-run 이 아니면 `confirm=true` 가 있어야 보낸다. 없으면 아무것도 보내지 않고 `status: confirmation_required` 와 계획(제목·대상·부모)을 돌려준다. `allow_draft` 는 dry-run 이어도 confirm 이 필요하다. CLI 는 사람이 직접 실행하므로 confirm 이 없다. `publish <feature>` 는 그대로다.
- 대상이 notion 이면 `publish.notion.parent_page_id` 의 **직계 자식**으로 SPEC 페이지(제목 = SPEC `title`, front-matter 는 보내지 않는다)나 INDEX 페이지를 upsert 한다. 원격 INDEX 는 fix/·hotfix/ 작업을 숨기고, 손으로 고친 날짜·PR 칸(YYYY-MM-DD, `[#n](https://…)`/`[PR](https://…)` 이 아닌 값)은 버리고, 남은 PR 칸도 `#n` 만 보낸다. SPEC 페이지 §6 변경 이력은 원격 INDEX 규칙을 따른다: fix/·hotfix/ 행은 `날짜 | (비공개)` 로 바꾸고 요약·PR 을 보내지 않는다. 다른 행의 PR 칸은 저장소 URL 없이 `#n` 만 보낸다. §6 제목은 있는데 표를 읽을 수 없으면 `skipped`(`code: history_unparsed`)다. 원격 INDEX 는 approved SPEC 만 싣는다(승인 전 SPEC 과 그 작업은 건수만 적는다).
- 소유 표시는 본문 첫 paragraph 블록 `agent-platform:<project_id>/<slug>` 다(갱신 후 사람이 둔 하위 페이지 뒤에 올 수 있다). 표시가 맞는 페이지만 본문을 교체하고 제목을 맞춘다(하위 페이지·DB 는 남는다). 같은 제목인데 표시가 없으면 `failed`(`code: title_conflict`)이고 그 페이지는 건드리지 않는다. 휴지통 페이지는 복원하지 않는다.
- 매핑 `.local/publish/<project_id>.json` 의 `specs.<slug>`/`index` 에 page_id(하이픈 없는 32 hex)를 저장한다. 매핑이 없거나 다른 부모를 가리키면 소유 표시 검색으로 다시 연결한다. 제목 PATCH 만 실패하면 `updated` 와 `warning` 이다.
- 보낼 제목+본문에 비밀 패턴이 있으면 원격 호출 0회로 `skipped`(`secret pattern detected: <kind>`, 값 비노출). 심링크·없는 SPEC·draft(플래그 없이) 도 호출 전에 `skipped` 다.
- 다른 project_id 의 같은 slug 표시는 사용자가 동의했을 때만 채택한다. 동의는 `--adopt-from <old_project_id>`(MCP `adopt_from`) 또는 현재 프로젝트 registry 레코드의 `previous_ids` 목록(읽기만 한다)이다. 채택하면 표시를 새 project_id 로 다시 쓰고 `result.adopted_from` 으로 알린다. 동의가 없으면 쓰지 않고 `failed`(`code: foreign_owner`, `result.found_project_id`)다. 이 기계 registry 에 없다는 것은 동의가 아니다(registry 는 기계마다 다르다). 같은 표시가 정확히 맞는 페이지가 있으면 그 페이지가 채택 후보보다 우선한다. dry-run 은 원격 호출을 하지 않으므로 title_conflict·foreign_owner·채택 여부를 보여 주지 못한다(`result.ownership`); 동의한 ID 만 `result.may_adopt` 로 보인다.
- exit code(`--spec`/`--spec-index`): `published`·`planned` 0, `skipped`(대상 none·draft·비밀값·없는 SPEC 등) 3, `failed`·`{"error"}` 1. `publish <feature>` 의 exit code 는 바뀌지 않았다(skipped 0).

## 결과 페이지 구조

```
부모 페이지
└── features/payment-cancel          (개요: PRD 의 검토 요청·개요·범위·API 요약·처리 흐름, FLOW.drawio 텍스트 뷰, 문서 목록)
    ├── API-SPEC                     (*.md 마다 자식 페이지, 제목은 파일명 stem)
    ├── PRD
    └── TASK
```

- 개요 제목은 `<type>/<name>` 전체라 `fix/x` 와 `features/x` 가 충돌하지 않는다. 개요 본문은 Confluence
  개요·REVIEW-VIEW 와 같은 `feature_overview.build_overview_markdown` 에서 나온다.
- 페이지 ID 는 `.local/publish/<project_id>.json`(ignored, 비밀값 없음)에 기억한다. 매핑이 없거나 손상됐거나
  페이지가 삭제(archived)됐으면 부모 아래 같은 제목의 페이지를 찾고, 없으면 새로 만든다. 부모 ID 를 바꾸면
  매핑은 쓰이지 않는다.
- 갱신은 기존 본문 블록을 모두 지운 뒤 새로 붙인다. 개요 페이지의 자식 페이지 블록은 지우지 않는다. Notion API 는
  블록을 앞에 끼울 수 없어서, 갱신된 개요 본문은 자식 페이지 목록 **아래**에 놓인다.

## 변환과 제한

변환은 `markdown_blocks.parse`(Confluence·REVIEW-VIEW 와 같은 파서) 결과를 `notion_blocks.render_notion` 으로 바꾼다.

| Markdown | Notion |
|---|---|
| `#`~`###` (4 이상은 3) | heading_1~3 |
| 문단 | paragraph (줄바꿈 유지) |
| `-` / `1.` | bulleted / numbered_list_item |
| `- [ ]` / `- [x]` | to_do (checked) |
| 펜스 코드 | code. language 를 Notion 목록으로 맞추고(`kt`→kotlin 등) 모르면 `plain text`. `mermaid` 는 그대로라 Notion 이 다이어그램으로 보여 준다 |
| 표 | table / table_row. 너비는 헤더 열 수, 짧은 행은 빈 칸으로 채우고 긴 행은 자른다 |
| `>` | quote |
| `---` | divider |
| `**b**` `*i*` `` `c` `` `[t](https://…)` | bold / italic / code / link. 상대 링크는 글자만 남는다 |
| `![alt](x.png)` | 글자 그대로(이미지 업로드 없음) |

- rich_text 는 항목당 2000자로 나누고, 한 블록에 100개를 넘으면 같은 종류의 블록을 이어 붙인다.
- 자식 블록은 요청당 100개씩 보낸다. 100행이 넘는 표는 표를 만든 뒤 나머지 행을 붙인다.
- front-matter 는 게시하지 않는다. 심링크이거나 feature 디렉터리 밖을 가리키는 `.md` 는 `skipped` 다. 개요도 그런
  `PRD.md`/`FLOW.drawio` 는 읽지 않고, 문서 목록에는 실제 게시한 `.md` 만 나온다.
- 게시 전 비밀값 검사: 고신뢰 패턴(PEM private key 헤더, AWS access key `AKIA`/`ASIA`, GitHub `ghp_`·`github_pat_` 등,
  Notion `ntn_`/`secret_`, Slack `xox[abpr]-`, Atlassian `ATATT3`)이 있는 `.md` 는 보내지 않고 `skipped`,
  `error: "secret pattern detected: <kind>, …"` 다(값·일부 문자열은 나오지 않는다). 그런 `PRD.md` 는 개요에서
  `_PRD.md 제외 (비밀값 의심)_`, 그런 `FLOW.drawio` 는 흐름 절이 빠진다. dry-run 도 같은 결과를 보여 준다. 접두만
  있는 예시(`ntn_ 접두`, `xoxb-your-token`)나 `password: …` 같은 일반 문장은 걸리지 않는다. Confluence 게시도 같다.
- 게시할 수 있는 `.md` 가 하나도 없으면(전부 skipped) 개요 페이지를 만들지 않는다. `overview: null`,
  `warning: "No publishable .md files"` 이고 원격 호출이 없다. `publish` 는 dry-run 여부와 상관없이
  `status: skipped`(`reason: "no publishable .md files"`, `.md` 자체가 없으면 `"no .md files to publish"`)다.
- FLOW.drawio 는 첨부하지 않는다(개요의 mermaid 텍스트 뷰만). SVG·이미지 업로드, 단계별 결정 페이지는 후속 범위다.

## 오류

API 호출은 timeout 30s, `Notion-Version: 2022-06-28`. 429 는 `Retry-After`(없으면 1s, 상한 10s)를 지켜 최대 3회
재시도한다. 5xx 는 GET/DELETE 만 재시도한다(POST/PATCH 는 이미 반영됐을 수 있어 다시 보내지 않는다).

| error | 원인 / 조치 |
|---|---|
| `Missing env var: NOTION_TOKEN` | `.env` 에 토큰 추가 |
| `Invalid NOTION_TOKEN format` | `ntn_`/`secret_` 로 시작하는 secret 인지 확인 |
| `Notion auth failed. Check NOTION_TOKEN` | 401. 토큰 만료·오타 |
| `Notion page not shared with integration or not found` | 403/404. 부모 페이지 Connections 에 integration 연결 |
| `Notion rate limited after 3 retries` | 잠시 후 재실행(upsert 라 중복 없음) |
| `Notion request timed out after 30s` | 네트워크 확인 후 재실행 |
| `Notion API error: HTTP <n> (<code>)` | 그 밖의 응답. 본문·헤더는 담지 않는다 |
| `project publish target is <none\|confluence>; notion publish refused` | `project-register` 후 `project-publish-set <id> --target notion --notion-parent-page-id …` |
| `Invalid parent_page_id` | 32자 hex ID 지정 |
| `Invalid publish settings: <field>` | 레지스트리 `publish` 손상. `project-publish-set` 으로 다시 저장 |

파일 하나가 실패해도 나머지는 계속하고 `results[].error` 에 남긴다(`status: partial`). 개요가 실패하면 자식
페이지를 만들지 않는다(`status: failed`).

## Confluence 와의 차이

| | Notion | Confluence |
|---|---|---|
| 재실행 | 같은 페이지 갱신(upsert) | 생성만. 같은 제목이면 실패 |
| 개요 제목 | `<type>/<name>` | 마지막 세그먼트(`name`) |
| FLOW.drawio | 첨부 없음(텍스트 뷰만) | 개요 페이지에 첨부(심링크·비밀 패턴이면 `skipped`) |
| 비밀값 | `NOTION_TOKEN` | `CONFLUENCE_URL`·`CONFLUENCE_EMAIL`·`CONFLUENCE_API_TOKEN` |
| 위치 설정 | 프로젝트 `publish.notion.parent_page_id` | 프로젝트 `publish.confluence.{space_key,parent_title}` 또는 도구 인자 |
