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

4. 조합된 requirements를 `plan_run_gemini` 또는 `plan_run_codex`의 `requirements` 파라미터로 전달

## 에러 처리

툴이 `{"error": "..."}` 를 반환하면:
- 환경변수 미설정 오류: 사용자에게 설정 방법 안내 후 진행 여부 질의
- 인증 실패: `CONFLUENCE_EMAIL` / `CONFLUENCE_API_TOKEN` 확인 요청
- 페이지/Space 없음: 올바른 ID/key 확인 요청
