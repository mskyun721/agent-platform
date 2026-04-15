---
description: 최근 완료된 feature 회고 문서 템플릿 생성
argument-hint: <feature-name>
allowed-tools:
  - Read
  - Write
  - Glob
  - Bash(date:*)
  - Bash(git:*)
---

`$ARGUMENTS` feature의 회고 문서를 생성하라.

## 절차
1. `docs/retrospectives/` 디렉터리가 없으면 생성
2. 파일명: `docs/retrospectives/$(오늘 날짜)-$ARGUMENTS.md`
3. 아래 템플릿으로 초기화:

```markdown
---
agent: orchestrator
feature: $ARGUMENTS
status: draft
created: <오늘 날짜>
updated: <오늘 날짜>
---

# Retrospective: $ARGUMENTS

## 1. 요약
- 기간:
- 참여 Agent: planner, backend, qa, cicd
- 최종 산출물: docs/features/$ARGUMENTS/

## 2. 잘 된 점 (Keep)

## 3. 문제 / 아쉬운 점 (Problem)

## 4. 개선 액션 (Try)
| 항목 | 대상 | 담당 Agent |
|---|---|---|

## 5. Agent별 관찰
### planner
### backend
### qa
### cicd

## 6. 표준/템플릿 개선 제안
- `standards/...`
- `templates/...`
```

4. 관련 git 커밋 요약(`git log --oneline` 최근 20개 중 feature 관련)을 `요약` 섹션에 자동 삽입
5. 사용자에게 편집 안내: "회고 초안 생성됨. 팀 리뷰 후 status: review로 전환하세요."
