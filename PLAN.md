# Agent Platform 개발 플랜 (옵션 A: Claude Code Subagent 방식)

## 목표
기획/백엔드/QA/CICD 4개 역할을 Claude Code Subagent로 구성하여 팀 공통 개발 워크플로우를 표준화한다. 모든 산출물(기획서/코드/테스트/배포)이 공통 템플릿과 표준을 따르도록 강제한다.

## 설계 원칙
- **확장성**: A방식으로 시작하되 Skill/Plugin/Agent SDK(C방식)로 무손실 확장 가능한 구조 유지
- **표준 단일 소스**: `standards/`를 유일한 진실 소스로 두고 모든 Agent가 참조
- **형식 강제**: `templates/` Front-matter(status, agent, date)로 산출물 형식 통일
- **Handoff 계약**: 각 Agent의 Quality Gate 통과 산출물만 다음 Agent가 수용
- **고정 경로**: 산출물은 `docs/features/<feature-name>/` 하위에 예측 가능한 이름으로 저장 (→ 나중 C방식에서 자동 파싱 용이)

## 기술 스택 전제
- Kotlin + Spring Boot + WebFlux + Coroutine (글로벌 스킬 정책 기반)
- Gradle Kotlin DSL, buildSrc 구조
- 테스트: JUnit5 + MockK + Testcontainers
- 이 전제는 `standards/coding-style.md`, `standards/test-policy.md`에 격리하여 추후 변경 용이

## 디렉토리 구조
```
agent-platform/
├── CLAUDE.md                      # 프로젝트 전역 지침 (모든 Agent 자동 참조)
├── README.md                      # 사용 방법 가이드
├── PLAN.md                        # 본 문서
├── claude_log.md                  # 작업 로그
├── .claude/
│   └── agents/                    # Claude Code Subagent 정의
│       ├── orchestrator.md
│       ├── planner.md
│       ├── backend.md
│       ├── qa.md
│       └── cicd.md
├── standards/                     # 팀 공통 표준 (단일 진실 소스)
│   ├── coding-style.md
│   ├── commit-convention.md
│   ├── api-contract.md
│   ├── test-policy.md
│   └── security-baseline.md
├── templates/                     # 산출물 템플릿
│   ├── PRD.md
│   ├── TASK.md
│   ├── DECISIONS.md
│   ├── API-SPEC.md
│   ├── TEST-PLAN.md
│   ├── BUG-REPORT.md
│   ├── RELEASE-NOTE.md
│   └── PR-TEMPLATE.md
├── workflows/                     # Agent 간 핸드오프 플로우
│   ├── feature-flow.md
│   └── hotfix-flow.md
└── docs/
    └── features/                  # 실제 작업 산출물 저장 위치
        └── <feature-name>/
```

## Agent 역할 정의
| Agent | 입력 | 출력 | Quality Gate |
|---|---|---|---|
| Orchestrator | 사용자 요청 | 작업 라우팅 | workflow 식별 완료 |
| Planner | 요구사항 | `PRD.md`, `TASK.md` | 성공 기준 정의, 스코프 명확 |
| Backend | PRD | 구현 코드, `API-SPEC.md`, `DECISIONS.md` | 빌드 성공, 단위 테스트 통과, 린트 통과 |
| QA | 코드 + API 명세 | `TEST-PLAN.md`, 통합 테스트 | 시나리오 커버리지, 회귀 테스트 통과 |
| CICD | 전체 산출물 | PR, 파이프라인 설정, `RELEASE-NOTE.md` | 자동화 검증, 롤백 절차 명시 |

## Subagent 공통 스키마
각 `.claude/agents/*.md`는 다음 구조 준수:
```yaml
---
name: <agent-name>
description: <호출 조건>
tools: <허용 도구 목록>
model: sonnet
---

# Role
# Inputs (누구로부터 무엇을)
# Outputs (필수 템플릿 링크)
# Workflow (단계별 절차)
# Reference Standards (참조 표준)
# Quality Gate (Handoff 전 체크리스트)
# Handoff (다음 Agent와 전달 내용)
```

## 산출물 Front-matter 규약
모든 산출물 상단에 필수 포함:
```yaml
---
agent: planner | backend | qa | cicd
feature: <feature-name>
status: draft | review | approved | rejected
created: YYYY-MM-DD
updated: YYYY-MM-DD
links:
  prd: docs/features/<name>/PRD.md
  api: docs/features/<name>/API-SPEC.md
---
```

## 개발 단계

### Phase 1: 기반 구조 (루트 파일)
- [ ] `CLAUDE.md` (프로젝트 전역 지침, 글로벌 CLAUDE.md 상속)
- [ ] `README.md` (사용 방법)
- [ ] `claude_log.md` (초기화)

### Phase 2: 공통 표준 (standards/)
- [ ] `coding-style.md` (Kotlin/Spring 코드 규칙)
- [ ] `commit-convention.md` (커밋/브랜치 규칙)
- [ ] `api-contract.md` (REST/OpenAPI 규칙)
- [ ] `test-policy.md` (테스트 정책, 커버리지 기준)
- [ ] `security-baseline.md` (보안 베이스라인)

### Phase 3: 산출물 템플릿 (templates/)
- [ ] `PRD.md`, `TASK.md`, `DECISIONS.md`
- [ ] `API-SPEC.md`, `TEST-PLAN.md`
- [ ] `BUG-REPORT.md`, `RELEASE-NOTE.md`, `PR-TEMPLATE.md`

### Phase 4: Subagent 정의 (.claude/agents/)
- [ ] `orchestrator.md` (라우팅/조율)
- [ ] `planner.md` (기획)
- [ ] `backend.md` (백엔드 개발)
- [ ] `qa.md` (품질 검증)
- [ ] `cicd.md` (배포)

### Phase 5: 워크플로우 (workflows/)
- [ ] `feature-flow.md` (기능 개발: 기획→개발→QA→배포)
- [ ] `hotfix-flow.md` (핫픽스 긴급 플로우)

### Phase 6: 검증
- [ ] 샘플 Feature로 end-to-end 실행 테스트
- [ ] 각 Agent 호출이 의도대로 동작하는지 확인
- [ ] 산출물 Front-matter 강제 여부 확인

## 사용 방법 (완성 후)
```
# 사용자가 Claude Code에서
> 회원 탈퇴 기능 만들어줘

# Orchestrator가 feature-flow.md 따라 자동 분배:
#   1. Planner → PRD/TASK 작성
#   2. Backend → 코드/API-SPEC 작성
#   3. QA → 테스트 계획/실행
#   4. CICD → PR 생성/파이프라인

# 또는 직접 호출
> @planner 회원 탈퇴 PRD 작성해줘
> @backend docs/features/withdraw/PRD.md 구현
```

## 확장 로드맵 (참고)
- **2단계**: `standards/` 중 조건부 지식을 Skill로 분리 (컨텍스트 효율화)
- **3단계**: 전체를 Plugin으로 패키징 (팀 간 배포)
- **4단계**: Claude Agent SDK(옵션 C)로 자동화 파이프라인 (Pro/Max 구독 유지, `ANTHROPIC_API_KEY` 미사용)

## 리스크 & 주의사항
- Subagent는 부모-자식 단방향 위임 구조. 협상형 멀티 Agent가 필요해지면 C방식 전환 필요
- Pro/Max 구독 rate limit: 병렬 Agent 호출 많으면 한계 체감 가능
- `CLAUDE.md` 글로벌 지침(특히 보안 규칙)을 프로젝트 레벨에서도 준수

## 승인 요청 항목
1. 디렉토리 구조 확정 여부
2. 기술 스택 전제(Kotlin+WebFlux) 유지 여부
3. 산출물 저장 경로(`docs/features/<name>/`) 확정 여부
4. Phase 1부터 순차 진행 여부 (또는 병렬 생성)
