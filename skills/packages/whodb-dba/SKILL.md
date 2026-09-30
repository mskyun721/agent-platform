---
name: whodb-dba
description: dba 역할이 WhoDB MCP 서버(whodb mcp serve --read-only)로 스키마·인덱스를 읽고 EXPLAIN 을 실행해 쿼리 복잡도와 조회 1초 SLO 를 실측하는 절차. 운영 DB 금지, staging·Testcontainers 만.
---

# whodb-dba

WhoDB(https://github.com/clidey/whodb, Apache-2.0)의 MCP 서버를 dba 역할의 **실측 보조**로 쓴다.
판정·기록은 `standards/agents/dba.md` 절차가 하며, 이 스킬은 그 Workflow 3(실측)에서만 쓴다.

## 전제
- MCP 서버가 등록돼 있어야 한다: Claude 는 플랫폼 `.mcp.json` 의 `whodb`, Codex 는 `~/.codex/config.toml` 의 `[mcp_servers.whodb]`. 둘 다 `whodb mcp serve --read-only` 다.
- 연결 대상은 **staging 또는 Testcontainers PostgreSQL 뿐**이다. 운영 DB 프로필을 만들지 않는다.
- 접속 정보는 `WHODB_POSTGRES_1` 같은 환경 변수나 `whodb connect --name <alias>`(OS 키링)로만 준다. `.mcp.json`, config.toml, 산출물 문서에 비밀번호를 쓰지 않는다.
- `--read-only` 이므로 SELECT/SHOW/DESCRIBE/EXPLAIN 만 된다. 인덱스 추가 같은 DDL 은 실행하지 않고 권장 조치로 적는다.

## 절차
1. `whodb_connections` 로 연결된 프로필을 확인한다. 프로필이 없으면 실측 불가로 적고 문장 형태·인덱스 목록만으로 판정한다(H2 는 근거로 쓰지 않는다).
2. `whodb_schemas` → `whodb_tables` → `whodb_columns` 로 대상 테이블의 컬럼·인덱스를 읽어 `docs/db/DB-CATALOG.md` 와 맞춘다. 차이가 있으면 카탈로그를 고친다.
3. 검토 쿼리를 실제 SQL 형태로 만들어(jOOQ 는 `renderInlined()` 또는 로그) `whodb_explain` 으로 `EXPLAIN (ANALYZE, BUFFERS)` 를 받는다. 카탈로그의 3년 규모로 채운 DB 에서 재야 SLO 판정에 쓸 수 있다. 규모가 다르면 그 사실을 적는다.
4. `whodb_suggestions`/`whodb_audit` 의 인덱스·재작성 제안은 **후보**다. 제안대로 다시 EXPLAIN 해 전후 비교를 `DB-REVIEW.md` §2 표에 넣는다. 제안 텍스트를 그대로 결론으로 쓰지 않는다.
5. 결과(계획의 노드·loops·actual time, p95)를 DB-REVIEW 에 적고 Skill Usage 에 `whodb-dba` 를 used 로 기록한다. 연결 실패·권한 부족은 unavailable 과 사유로 남긴다.

## 하지 않는 것
- `--allow-write` 로 띄우지 않는다. 쓰기 확인 토큰(`whodb_confirm`)을 승인하지 않는다.
- 운영 접속 정보를 요청하거나 저장하지 않는다.
- 스킬 출력만으로 HIGH/LOW 를 정하지 않는다. 기준은 dba.md 의 SLO·차수 규칙이다.
