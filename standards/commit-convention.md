# Commit & Branch Convention

## 브랜치 네이밍
- `feat/<feature-name>` - 신규 기능
- `fix/<bug-name>` - 버그 수정
- `hotfix/<issue-name>` - 긴급 수정
- `refactor/<scope>` - 리팩토링
- `chore/<scope>` - 빌드/설정/문서
- `test/<scope>` - 테스트 추가

예: `feat/user-withdraw`, `hotfix/login-npe`

## 커밋 메시지 (Conventional Commits)
```
<type>(<scope>): <subject>

<body (optional)>

<footer (optional)>
```

### Type
- `feat`: 신규 기능
- `fix`: 버그 수정
- `refactor`: 리팩토링 (동작 변경 없음)
- `chore`: 빌드/설정/의존성
- `docs`: 문서
- `test`: 테스트
- `perf`: 성능 개선
- `style`: 포맷팅

### 규칙
- subject는 영어, 명령형 현재시제 (`add`, `fix`, `update`)
- subject 50자 이내, 마침표 없음
- body는 WHY 중심 (WHAT은 diff로 확인)
- Breaking change는 `!` 또는 footer `BREAKING CHANGE:`

### 예시
```
feat(user): add withdrawal endpoint

- soft-delete with 90-day grace period
- personal data masking on request

Refs: docs/features/user-withdraw/PRD.md
```

## PR 규칙
- 제목: 커밋 규칙 동일 형식
- 본문: `templates/PR-TEMPLATE.md` 사용
- 머지 전 lint/format/test 전부 통과
- Reviewer 최소 1명 승인
- Squash merge 기본 (커밋 히스토리 정리)

## 머지 금지 조건
- CI 실패
- 리뷰 미승인
- 컨플릭트 미해결
- `standards/` 위반
