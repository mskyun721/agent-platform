# harness2 기능 사용법

google-research/harness2 개념을 도입한 세 기능의 실사용 안내다.

| 기능 | 무엇을 하나 | 과금 |
|---|---|---|
| 호스트 동등 지원 | Claude Code·Gemini CLI·Copilot CLI 중 하나로 전체 흐름을 단독 수행 | 평소 사용과 같음 |
| 경험 라이브러리 | handoff 직전 근거 있는 교훈을 draft로 기록 → 승인한 것만 다음 작업에서 참고 | 없음 (파일 기록) |
| Propose–Probe–Compose (PPC) | 역할 지시문 개선 후보를 여러 개 만들고 fixture로 실행·비교해 하나로 합침 | **있음** (모델 호출) |

아래 `apa`는 다음 별칭이다.

```bash
alias apa='uv --directory /ABS/PATH/agent-platform/mcp-server run agent-platform-agent'
```

---

## 1. 호스트 선택 (Claude / Gemini / Copilot)

AI를 역할별로 섞지 않고, **한 AI로 기획→개발→리뷰→QA 전체 흐름**을 수행하는 방식이다.

### 1.1 준비

| 호스트 | 설치 | 인증 |
|---|---|---|
| Claude Code | `claude` | Claude 계정 |
| Gemini CLI | `npm i -g @google/gemini-cli` | 첫 실행 시 Google 로그인 또는 `GEMINI_API_KEY` 환경변수 |
| Copilot CLI | `npm i -g @github/copilot` | 첫 실행 시 `/login` (Copilot 구독이 있는 GitHub 계정) |

- 인증은 각 CLI가 직접 관리한다. 플랫폼은 인증 파일을 읽거나 저장하지 않는다.
- API 키는 셸 환경변수나 각 CLI의 사용자 설정(`~/.gemini/` 등, repo 밖)에만 둔다. repo 안 파일에 넣지 않는다.

설치 상태 확인:

```bash
apa doctor --root .        # hosts 섹션: 설치 여부·버전·adapter 파일·관측 지원
gemini mcp list            # agent-platform 이 Connected 인지
```

`doctor`는 파일 존재만 확인한다. 실제 로드 여부는 CLI 안에서 확인한다.

### 1.2 실행

플랫폼 루트에서 원하는 CLI를 연다.

```bash
cd /ABS/PATH/agent-platform
claude      # 또는 gemini, copilot
```

그 다음은 호스트와 무관하게 같은 방식으로 요청한다.

```text
> /new-feature payment-cancel
> planner 로 payment-cancel PRD/TASK 작성해줘
> backend 로 payment-cancel 구현해줘
> reviewer 로 payment-cancel 리뷰해줘
> /gate-check payment-cancel
> /handoff qa payment-cancel
```

| 호스트 | 공통 지시문 | MCP 서버 | 역할·커맨드 |
|---|---|---|---|
| Claude | `CLAUDE.md` → `AGENTS.md` | `.mcp.json` | `.claude/agents/`, `.claude/commands/` |
| Gemini | `GEMINI.md` → `@AGENTS.md` | `.gemini/settings.json` | `.gemini/commands/*.toml` (`/handoff`, `/gate-check` …) |
| Copilot | `AGENTS.md` | `.mcp.json` | `.github/agents/<role>.agent.md` (`/agent`로 선택) |

### 1.3 wrapper로 다른 AI에 위임

현재 세션은 그대로 두고 한 역할만 다른 CLI로 실행할 때 쓴다.

```bash
apa route reviewer --root . --ai gemini                      # 어떤 모델로 갈지 미리보기
apa run reviewer FEATURE --root "$PWD" --ai gemini --dry-run
apa run reviewer FEATURE --root "$PWD" --ai copilot
```

- Gemini/Copilot wrapper 산출물도 `status: draft`로 남는다.
- 리뷰 계열은 읽기 전용으로 실행된다. Gemini는 `plan` 모드이고, Copilot은 쓰기와 셸을 금지한다.
- Gemini/Copilot은 세션 관측(transcript 수집)과 hook을 지원하지 않는다. Copilot은 토큰 사용량도 `unavailable`로 기록된다.

### 1.4 호스트별 모델 고정

`.agent-config.json`:

```json
"host_models": {
  "gemini":  {"reviewer": "gemini-2.5-pro"},
  "copilot": {"backend": "<copilot 모델 ID>"}
}
```

라우팅 우선순위: 명시 `--model` > project_role > role > `cli_models` > `host_models` > `claude_models` > CLI 기본값.
Copilot은 이 값이 `.github/agents/<role>.agent.md`의 `model`에도 반영된다(아래 동기화 후).

### 1.5 adapter 동기화

`GEMINI.md`, `.gemini/`, `.github/agents/`는 생성 파일이라 직접 고치지 않는다.
원본(`standards/agents/*.md`, `.claude/commands/*.md`, `.mcp.json`, `.agent-config.json`)을 고친 뒤:

```bash
python3 scripts/sync_claude_settings.py --agents-only   # Claude adapter + 위 호스트 파일까지
python3 scripts/sync_hosts.py --check                   # drift 시 exit 1
```

---

## 2. 경험 라이브러리

역할이 작업 중 **근거 파일로 확인된** 교훈을 남기고, 사람이 승인한 것만 다음 작업의 같은 역할이 읽는다.

### 2.1 흐름

```text
역할 작업 → handoff 직전 experience_add (draft)
         → 사람이 list/show 로 검토 → approve 또는 reject
         → approved 만 docs/experience/<role>/INDEX.md 에 모임
         → 다음 작업에서 같은 역할이 시작할 때 INDEX.md 를 읽음
```

- 저장 위치: `{TARGET_PROJECT}/docs/experience/<role>/<type>__<name>__<n>.md`. Git으로 관리한다.
- 역할은 handoff 직전에 교훈 0~3개를 자동으로 기록한다(MCP `experience_add`).
- 근거가 없으면 기록하지 않는 것이 정상이다.
- `handoff_validate`는 기록이 없으면 `experience: none recorded for <role>` 경고만 남기고 handoff를 막지 않는다.

### 2.2 직접 기록

```bash
apa experience add --root . --role backend --feature fix/login-bug < lesson.json
```

`lesson.json`:

```json
{
  "cue": "토큰 만료 직후 재시도 요청이 들어오는 경우",
  "lesson": "만료 판정과 재발급을 같은 트랜잭션 경계에서 검증하는 테스트를 먼저 추가한다",
  "evidence_note": "리뷰 반려 사유가 경계 테스트 누락이었다",
  "evidence": ["docs/fix/login-bug/REVIEW.md"],
  "source_handoff": "reviewer->backend"
}
```

검증 규칙 (위반 시 거부):

| 항목 | 제한 |
|---|---|
| 크기 | 항목당 4KB 이하 |
| 승인 개수 | 역할당 approved 30개 이하 |
| 근거 | 프로젝트 안 실존 파일 1~10개. 절대경로·`..`·symlink 금지 |
| 내용 | 비밀값 패턴, `#` 헤딩, `---`, `evidence_note`의 목록 줄 금지 |

### 2.3 검토·승인

```bash
apa experience list --root . --status draft             # 메타데이터 목록
apa experience show backend/fix__login-bug__1 --root .  # 본문 확인
apa experience approve backend/fix__login-bug__1 --root .
apa experience reject  backend/fix__login-bug__2 --root . --reason "재현 안 됨"
```

자동 승인은 없다. 승인·반려는 사용자나 담당 역할이 명시적으로 결정한다.

### 2.4 플랫폼 지침으로 승격

서로 다른 프로젝트 2곳 이상에서 같은 교훈이 approved 되었을 때:

```bash
apa experience promote --root /ABS/PATH/agent-platform \
  --entry /path/service-a::backend/fix__x__1 /path/service-b::backend/features__y__2
```

promote는 플랫폼에 feedback 레코드를 만든다. 이후 기존 improvement 절차로 `standards/agents/<role>.md` 개선 후보를 만든다([improvement-workflow.md](improvement-workflow.md)).

---

## 3. Propose–Probe–Compose (PPC)

역할 지시문(`standards/agents/<role>.md`) 개선 후보를 자동으로 만든다. 실행 순서는 다음과 같다.

1. 현재 지시문으로 fixture를 실행한다.
2. 일반 개선(INV)과 도메인 개선(DOM) 후보를 만든다. DOM은 approved 경험을 근거로 쓴다.
3. 후보를 같은 fixture로 실행한다.
4. 실행 기록의 차이를 근거로 합성안을 만든다.
5. 합성안을 다시 실행한다.
6. 합성안과 원본 중 하나를 블라인드로 선택한다.

### 3.1 실행 전 확인

- **과금된다.** k=1이면 fixture 실행 4회, 모델 세션 4회(3k+1)다. k는 1~4다.
- 선택한 호스트 CLI가 설치·로그인되어 있어야 한다. 없으면 즉시 실패한다.
- DOM 후보의 품질은 approved 경험에 달려 있다. `--project`의 `docs/experience/<role>/INDEX.md`에 승인 항목이 있을 때 효과가 있다.
- Gemini는 API 과부하(503)로 실패한 이력이 있다. 먼저 `apa run reviewer … --ai gemini`로 연결을 확인한다.

### 3.2 실행

```bash
cd /ABS/PATH/agent-platform
uv --directory mcp-server run --locked --dev python ../evals/ppc.py \
  --host gemini --role backend --model <모델ID> \
  --k 1 --tasks seeded-bug --max-minutes 30 \
  --project /ABS/PATH/service-a
```

| 옵션 | 의미 |
|---|---|
| `--host` | `claude`, `codex`, `gemini`, `copilot` 중 하나. 전 과정이 이 호스트로만 실행된다 |
| `--role` | 개선할 역할 (fixture가 코딩 과제라 `backend`가 적합) |
| `--model` | 호스트의 모델 ID |
| `--k` | 병렬 폭 1~4 (기본 1) |
| `--tasks` | 쉼표 구분 fixture: `small-feature`, `seeded-bug`, `broken-test`, `api-add`, `skill-remove` |
| `--max-minutes` | 전체 시간 상한. 초과 시 `budget_exhausted` |
| `--project` | 경험 INDEX를 읽을 프로젝트 경로 또는 project_id |
| `--seed` | 블라인드 섞기 시드 (기본 0) |
| `--no-improvement` | 결과를 improvement draft로 등록하지 않음 |

### 3.3 결과 확인

결과 위치: `.local/ppc/<run-id>/`

| 파일 | 내용 |
|---|---|
| `result.json` | 상태, 선택 결과(`selection.chosen`, `why`), 등록된 feedback/candidate ID |
| `ledger.json` | 실행·세션 장부 (4k rollouts / 3k sessions 검증) |
| `candidates/*.md`, `finals/*.md` | 후보·합성 지시문 |
| `rollouts/*.json` | fixture 실행 기록 |

`status` 값:

| 값 | 의미 |
|---|---|
| `completed` | 정상 종료. `changed`가 true면 원본보다 나은 안이 선택됨 |
| `no_valid_proposals` | 모든 후보가 형식 오류 등으로 원본으로 돌아감 |
| `budget_exhausted` | 시간 초과. 부분 장부와 후보는 남음 |
| `registration_failed` | 선택은 됐으나 improvement 등록 실패 |
| `failed` | 그 외 오류 |

### 3.4 적용

원본보다 나은 안이 선택되면 improvement **draft**로만 등록된다. 적용 절차는 기존과 같다.

```bash
apa improvement show <candidate_id> --root "$PWD"
apa improvement evaluate <candidate_id> --root "$PWD" --baseline … --candidate … --hosts gemini
apa improvement review <candidate_id> --root "$PWD" --decision approved --reviewer <이름>
apa improvement apply <candidate_id> --root "$PWD" --dry-run
apa improvement apply <candidate_id> --root "$PWD"
```

- `--hosts gemini`로 지정하면 해당 호스트의 기록만으로 매칭 평가한다. 기본값은 claude와 codex다.
- PPC 실행 기록은 `instruction_mode=ppc`로 분리되어 회귀 기준선에 섞이지 않는다.

### 3.5 안전장치

- 후보는 `# ` 섹션 단위로만 편집한다. 생략한 섹션은 그대로 유지되고, 섹션 삭제는 불가하다.
- 정책 성격의 섹션(Rules, Security, Approval, Quality Gate, Boundaries, Completion 등)은 기존 줄을 지울 수 없고 추가만 가능하다.
- "규칙을 무시/우회하라"는 문구는 거부한다.
- 비밀값 패턴이 있거나 64KB를 넘는 후보는 거부한다.
- 합성·선택 단계의 모델은 fixture 채점 기준이나 정답을 보지 않는다.
- 자동 승인·자동 적용·자동 커밋은 없다.

### 3.6 알려진 한계

- k≥2이면 원본만 실행 기록이 k개라 블라인드 선택이 완전하지 않다.
- PPC rollout과 매칭 eval의 실행 조건(셸 허용, 지시문 위치)이 달라, 개선이 매칭 eval에서 그대로 재현되지 않을 수 있다.
- Ctrl-C나 파일 오류로 중단되면 `result.json`이 남지 않을 수 있다.
- fixture가 모두 코딩 과제다. reviewer 같은 비구현 역할에는 근거가 약하다.

---

## 4. 추천 순서

1. 사용할 호스트를 하나 정하고 `apa doctor --root .`로 확인한다.
2. 그 호스트로 실제 기능 몇 개를 끝까지 진행한다. handoff마다 `experience list --status draft`를 확인한다.
3. 근거가 확실한 교훈만 approve한다.
4. approved가 몇 개 쌓이면 `--k 1 --tasks seeded-bug`로 PPC를 한 번 실행한다.
5. 결과가 `changed: true`이면 improvement 절차로 평가·검토 후 적용한다.
