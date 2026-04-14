# Claude Work Log

## 2026-04-13

### Session: Agent Platform 초기 설계 & 구축

**요구사항**
- 기획/백엔드/QA/CICD 4개 Agent 오케스트레이션 구조 설계
- 각 Agent별 기본 가이드(.md) 제공
- 팀 내 공통 사용 + 산출물 공통 형식 강제

**설계 방향**
- 옵션 A (Claude Code Subagent) 채택
  - 이유: Pro/Max 구독으로 추가 비용 없음, Skill/Plugin/SDK로 무손실 확장 가능
- 향후 C(Agent SDK) 전환 시에도 `ANTHROPIC_API_KEY` 미사용, Claude Code 로그인 세션 활용

**개념 정리**
- A방식(Subagent) = Plugin의 핵심 부품
- Skill/Plugin은 Claude Code 확장 레이어 (형제 관계)
- Agent SDK는 상위 호출 레이어

**Plan 작성 & 승인**
- `PLAN.md` 작성 완료
- 사용자 승인 → Phase 1~5 병렬 진행 결정

**구축 완료 산출물**

### Phase 1: 기반 파일
- `CLAUDE.md` (프로젝트 전역 지침)
- `README.md` (세팅/사용 방법)
- `claude_log.md` (작업 로그)
- `PLAN.md` (설계 문서)

### Phase 2: 공통 표준 (standards/)
- `coding-style.md` - Kotlin + Spring Boot + WebFlux + Hexagonal
- `commit-convention.md` - Conventional Commits + 브랜치 규칙
- `api-contract.md` - REST + OpenAPI + RFC 7807
- `test-policy.md` - 피라미드 + 커버리지 기준
- `security-baseline.md` - 인증/인가/PII/시크릿 관리

### Phase 3: 산출물 템플릿 (templates/)
- `PRD.md` (백엔드 서버 중심, 기술 명세 수준)
- `TASK.md` (Phase 1~7 분해)
- `DECISIONS.md` (ADR)
- `API-SPEC.md` (REST + 이벤트)
- `TEST-PLAN.md` (AC × Level 매트릭스)
- `BUG-REPORT.md`
- `RELEASE-NOTE.md`
- `PR-TEMPLATE.md`

### Phase 4: Subagent 정의 (.claude/agents/)
- `orchestrator.md` (model: sonnet) - 라우팅/조율
- `planner.md` (model: sonnet) - 기획/PRD 작성
- `backend.md` (model: sonnet) - Kotlin/Spring 구현
- `qa.md` (model: haiku) - 검증/테스트
- `cicd.md` (model: haiku) - PR/배포
  - 사용자가 qa/cicd model을 haiku로 변경 (비용 최적화)

### Phase 5: 워크플로우 (workflows/)
- `feature-flow.md` - 신규 기능 4-Phase 플로우
- `hotfix-flow.md` - 긴급 핫픽스 축약 플로우

**구조 특징**
- 모든 산출물은 Front-matter로 status 추적 (draft → review → approved)
- 각 Agent는 standards/ 를 단일 진실 소스로 참조
- Handoff는 Quality Gate 통과 산출물만 다음 Agent가 수용
- Hexagonal 아키텍처 전제 (Domain → Application → Adapter 순)

**다음 단계 (선택)**
- Phase 6: 샘플 Feature로 end-to-end 검증 테스트
- 확장 로드맵: standards 일부를 Skill로 분리 → Plugin 패키징 → Agent SDK 자동화

---
