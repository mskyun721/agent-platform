---
agent: dba
feature: project
status: draft
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# DB CATALOG: <project>

> 프로젝트 단위 DB 현황. dba 역할이 feature 마다 갱신한다. 실제 DDL 은 마이그레이션이 진실이고, 이 문서는 **규모 가정과 보존 정책**을 들고 있다. 조회 API 1초 SLO 판정의 규모 기준이 여기서 나온다.

## 1. 규모 가정
- 기준일: YYYY-MM-DD
- 대표 테넌트: org N 개, project M 개, 인증서 K 개 (운영 관측값 또는 계획값, 출처 명시)
- 예상 기간: 3년

## 2. 테이블
| 테이블 | 역할 | PK / 유니크 | 인덱스 (마이그레이션) | 현재 행 수 | 증가 규칙 | 3년 예상 | 보존 정책 | 1초 SLO 에 걸리는 쿼리 |
|---|---|---|---|---|---|---|---|---|
| `certificate` | 인증서 본문·메타 | `id` / `(org_id, name)`, `(org_id, serial_number)` | `idx_…` (V4) | 1만 | 등록 1건/행 | 5만 | 삭제 시 hard delete | 목록 조회 (`findByOrgId`) |
| `certificate_schedule_history` | 스케줄 실행 이력 | `seq` | `(schedule_id)` (V14) | 7천 | 스케줄당 실행 1건/행 (DAILY 365/년) | 2만+ | **없음** | 목록의 최신 이력 조회 |

## 3. 인덱스 대비 쿼리
자주 도는 쿼리와 그것이 타는 인덱스. 새 쿼리를 추가할 때 여기 없는 접근 경로면 인덱스 추가를 검토한다.

| 쿼리 | 테이블 | WHERE / ORDER BY | 타는 인덱스 | 비고 |
|---|---|---|---|---|

## 4. 보존·정리
| 테이블 | 정책 | 실행 주체 | 상태 |
|---|---|---|---|
| `certificate_schedule_history` | (미정) | - | 후속 |

## 5. 변경 이력
| 날짜 | feature | 변경 | DB-REVIEW |
|---|---|---|---|
