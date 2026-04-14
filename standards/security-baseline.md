# Security Baseline

## 절대 규칙 (글로벌 CLAUDE.md 상속)
- `.env`, `.pem`, `.key`, `credentials`, `secret*` 파일 읽기/쓰기 금지
- API 키, 비밀번호, 토큰 **코드 하드코딩 금지**
- 발견 즉시 경고 + 제거 후 환경변수 또는 Secret Manager로 이전

## 인증 (Authentication)
- JWT: RS256, 만료 시간 짧게 (access 15m, refresh 14d)
- 비밀번호: BCrypt (cost ≥ 12) 또는 Argon2
- 세션 토큰은 HttpOnly + Secure + SameSite=Strict 쿠키

## 인가 (Authorization)
- 최소 권한 원칙
- 엔드포인트 기본값: **인증 필요**, 공개는 `@PermitAll` 명시
- 리소스 소유권 검증 (타인의 데이터 접근 차단)

## 입력 검증
- 모든 외부 입력 검증 (Bean Validation)
- SQL Injection: 파라미터 바인딩만 사용 (문자열 concat 금지)
- XSS: 응답은 JSON 기본, HTML 반환 시 이스케이프
- Path Traversal: 파일 경로 입력 시 `Path.normalize()` + whitelist

## 민감정보 로깅 금지
- 비밀번호, 토큰, 주민번호, 카드번호 로그 출력 금지
- 마스킹 유틸 사용: `"010-****-1234"`, `"abc***@gmail.com"`
- 로그 레벨 정책: PII는 DEBUG에도 출력 금지

## HTTPS / TLS
- 모든 운영 엔드포인트는 HTTPS 강제
- HSTS 헤더 활성화
- TLS 1.2+ 만 허용

## Secret 관리
- 개발: `.env.local` (gitignore)
- 운영: AWS Secrets Manager / Vault / K8s Secret
- 커밋 전 `git-secrets` 또는 `trufflehog` 스캔

## 의존성 보안
- Dependabot / Renovate 자동 업데이트
- `./gradlew dependencyCheckAnalyze` 주기 실행
- Critical/High CVE 발견 시 즉시 패치

## CORS
- 운영: `Access-Control-Allow-Origin` 화이트리스트
- 개발 전용 `*` 설정은 프로파일 분리

## Rate Limiting
- 공개 API는 IP + 사용자 기준 rate limit
- Bucket4j 또는 Redis 기반
- 로그인/회원가입은 특히 엄격하게

## 개인정보
- 수집 시 동의 + 목적 명시
- 탈퇴 시 개인정보 파기 정책 준수 (법정 보존 기간 예외)
- PII 필드는 DB 레벨 암호화 고려

## 보안 체크리스트 (PR 머지 전)
- [ ] 하드코딩된 시크릿 없음
- [ ] 입력 검증 추가됨
- [ ] 인증/인가 체크 구현
- [ ] 민감정보 로깅 없음
- [ ] OWASP Top 10 해당 사항 검토
