# Agent Platform

Claude Code Subagent 기반 팀 공통 개발 워크플로우 플랫폼.
기획 → 백엔드 개발 → QA → CI/CD 4개 역할의 Agent가 표준화된 산출물을 생성하고 핸드오프한다.

## 구성
```
agent-platform/
├── CLAUDE.md                  # 프로젝트 전역 지침 (Claude가 자동 로드)
├── .claude/agents/            # Subagent 정의 (핵심)
│   ├── orchestrator.md
│   ├── planner.md
│   ├── backend.md
│   ├── qa.md
│   └── cicd.md
├── standards/                 # 팀 공통 표준 (단일 진실 소스)
├── templates/                 # 산출물 템플릿
├── workflows/                 # Agent 간 핸드오프 플로우
└── docs/features/<name>/      # 실제 작업 산출물 저장소
```

## 요구사항
- Claude Code CLI 설치
- Claude Pro 또는 Max 구독 (API 키 불필요)
- macOS / Linux / Windows (WSL)

## 세팅

### 1. Claude Code 로그인
```bash
# API 키가 설정되어 있다면 먼저 제거 (Pro/Max 구독 사용을 위해)
unset ANTHROPIC_API_KEY

# 로그인
claude login
```

### 2. 프로젝트 클론/배치
```bash
git clone <this-repo> agent-platform
cd agent-platform
```

### 3. Claude Code 실행
```bash
claude
```
프로젝트 루트에서 실행하면 `CLAUDE.md`와 `.claude/agents/*` 가 자동 로드된다.

### 4. Subagent 등록 확인
Claude Code 세션 내에서:
```
/agents
```
`orchestrator`, `planner`, `backend`, `qa`, `cicd` 5개가 목록에 표시되어야 한다.

## 사용법

### 방식 1. 자동 오케스트레이션 (권장)
사용자는 요구사항만 던지고 Orchestrator가 전체 플로우를 관장한다.

```
> 회원 탈퇴 기능을 추가하고 싶어. 탈퇴 시 개인정보는 90일 후 완전 삭제되도록.
```

Orchestrator는 `workflows/feature-flow.md`에 따라:
1. **Planner** 호출 → `docs/features/user-withdraw/PRD.md`, `TASK.md` 생성
2. **Backend** 호출 → 코드 구현 + `API-SPEC.md`, `DECISIONS.md` 생성
3. **QA** 호출 → `TEST-PLAN.md` 작성 + 테스트 실행
4. **CICD** 호출 → PR 생성 + `RELEASE-NOTE.md`

### 방식 2. 직접 Agent 호출
특정 단계만 수행하거나 기존 산출물에 이어서 작업할 때.

```
> @planner 결제 취소 기능의 PRD 작성해줘
> @backend docs/features/payment-cancel/PRD.md 읽고 구현해줘
> @qa docs/features/payment-cancel/ 전체 테스트 계획 세워줘
> @cicd docs/features/payment-cancel/ PR 생성해줘
```

### 방식 3. 긴급 핫픽스
```
> @orchestrator 핫픽스: 로그인 시 NPE 발생. stack trace: ...
```
Orchestrator가 `workflows/hotfix-flow.md`로 우회해 Backend → QA → CICD 축소 플로우 실행.

## 산출물 구조
```
docs/features/user-withdraw/
├── PRD.md             # Planner 작성
├── TASK.md            # Planner 작성
├── DECISIONS.md       # Backend 작성 (아키텍처 결정 기록)
├── API-SPEC.md        # Backend 작성
├── TEST-PLAN.md       # QA 작성
└── RELEASE-NOTE.md    # CICD 작성
```

모든 문서는 상단 Front-matter로 상태(`draft` → `review` → `approved`)를 추적한다.

## 커스터마이징

### 기술 스택 변경
`standards/coding-style.md`, `standards/test-policy.md` 를 수정한다. Subagent들은 이 파일만 참조하므로 Agent 파일 직접 수정 불필요.

### 새 Agent 추가
1. `.claude/agents/<new-agent>.md` 작성 (공통 스키마 준수)
2. `workflows/*.md` 에 핸드오프 지점 추가
3. 필요 시 `templates/` 에 신규 산출물 템플릿 추가

### Agent 도구 권한 조정
각 Agent `.md` front-matter의 `tools:` 필드 편집.

## 확장 로드맵
- **2단계**: `standards/` 중 조건부 지식을 Skill로 분리
- **3단계**: 전체를 Plugin으로 패키징 (`/plugin install`로 타 레포 배포)
- **4단계**: Claude Agent SDK로 자동화 파이프라인 (CI 연동)

## 트러블슈팅

**Q. `/agents` 에 Subagent가 안 보여요**
- `.claude/agents/*.md` 의 Front-matter(`name`, `description`) 확인
- Claude Code 재시작 (`/clear` 후 재실행)

**Q. API 요금이 청구돼요**
- `echo $ANTHROPIC_API_KEY` 로 환경변수 확인. 있다면 `unset ANTHROPIC_API_KEY`
- Pro/Max 구독 상태로 로그인되었는지 `claude` 실행 시 표시되는 계정 확인

**Q. Agent가 템플릿을 안 따라요**
- 해당 Agent `.md` 의 "Outputs" 섹션에 템플릿 경로 명시 여부 확인
- 사용자 프롬프트에 `templates/PRD.md 형식으로` 명시적 지시 추가

## 라이선스
내부 사용. 팀 표준에 맞춰 수정/확장 자유.
