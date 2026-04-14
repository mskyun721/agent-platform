---
agent: qa
feature: <feature-name>
status: open
created: YYYY-MM-DD
updated: YYYY-MM-DD
severity: P0 | P1 | P2 | P3
---

# BUG: <한 줄 제목>

## 요약
한 줄로 현상 요약

## 심각도
- **Severity**: P0 (서비스 중단) | P1 (주요 기능 장애) | P2 (우회 가능) | P3 (사소)
- **Priority**: Critical | High | Medium | Low
- **재현율**: 100% | 간헐적 (N/M) | 1회

## 환경
- 서비스 버전:
- 환경: local | dev | stage | prod
- DB/외부 시스템 상태:
- 사용자 조건 (해당 시):

## 재현 절차
1.
2.
3.

## 기대 결과
- 어떻게 동작해야 하는가

## 실제 결과
- 실제로 어떻게 동작하는가

## 증거 (Evidence)
### Request
```
POST /v1/xxx
...
```

### Response
```json
{ ... }
```

### Stack Trace
```
(전체 stack trace 첨부)
```

### 로그
```
(관련 로그 — PII 마스킹 필수)
```

### 메트릭/그래프 링크
- Grafana:
- Sentry:

## 영향 범위
- 영향받는 사용자:
- 영향받는 기능:
- 데이터 정합성 영향:

## 의심 원인 (Hypothesis)
- 가설 1:
- 가설 2:

## 임시 조치 (Workaround)
- 운영/사용자 레벨 우회 방법 (있다면)

## 관련 자료
- 관련 PR:
- 관련 티켓:
- 관련 AC: AC-N

## 재현용 테스트
```kotlin
@Test
fun `재현 테스트 코드 (실패 재현)`() {
    // 버그 수정 전까지 @Disabled 또는 expected failure
}
```

## 해결 기록
- **Fixed By**:
- **Fix PR**:
- **Fix Commit**:
- **검증 방법**:
- **회귀 테스트 추가**: [ ]
