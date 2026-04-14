---
agent: backend
feature: <feature-name>
status: draft
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# DECISIONS: <기능명>

> ADR(Architecture Decision Record). 구현 중 선택한 아키텍처/설계 결정과 근거를 기록한다.
> 단순 코드 스타일은 제외. **trade-off가 있었던 선택**만.

## ADR-001: <결정 제목>
- **Date**: YYYY-MM-DD
- **Status**: Proposed | Accepted | Deprecated | Superseded by ADR-NNN
- **Context**
  - 어떤 상황/제약이 있었는가
  - 어떤 문제를 해결해야 하는가
- **Decision**
  - 무엇을 선택했는가 (명확히)
- **Alternatives Considered**
  | 대안 | 장점 | 단점 | 기각 사유 |
  |---|---|---|---|
  | A안 (채택) | ... | ... | - |
  | B안 | ... | ... | ... |
  | C안 | ... | ... | ... |
- **Consequences**
  - 긍정적 영향
  - 부정적 영향 / 감수할 트레이드오프
  - 향후 재검토 조건

---

## ADR-002: <예시> 동시성 제어 방식으로 비관적 락 채택
- **Date**: 2026-04-13
- **Status**: Accepted
- **Context**
  - 탈퇴 요청은 동일 유저에 대해 중복 처리 위험이 있음
  - 외부 Order Service 호출 후 상태 변경까지 시간 간격 존재
- **Decision**
  - User 행에 `SELECT ... FOR UPDATE` 적용 (비관적 락)
- **Alternatives Considered**
  | 대안 | 장점 | 단점 | 기각 사유 |
  |---|---|---|---|
  | 비관적 락 (채택) | 정합성 확실, 구현 단순 | 동시 처리량 저하 | - |
  | 낙관적 락 (@Version) | 처리량 유리 | 재시도 로직 복잡, 실패율 상승 | 탈퇴는 저빈도 |
  | Redis 분산 락 | 멀티 노드 대응 | 인프라 의존 추가 | 오버엔지니어링 |
- **Consequences**
  - 탈퇴 트랜잭션 동안 동일 유저 다른 요청 대기 (체감 없음, 단건 처리)
  - 트랜잭션 길이 최소화 필요 (외부 호출은 락 전에 완료)

---

## Quality Gate
- [ ] Trade-off가 있었던 모든 결정 기록
- [ ] 각 ADR에 대안 비교표 포함
- [ ] Consequences의 부정적 영향도 명시
- [ ] status: `draft` → `approved`
