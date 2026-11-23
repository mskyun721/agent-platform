"""High-confidence secret detection before publishing (SECURITY M-2, DECISIONS ADR-011).

Fixture tokens are assembled at runtime so this file itself never holds a token-shaped string.
"""

from __future__ import annotations

import pytest

from agent_platform_mcp import secret_scan

ALNUM = "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0Uv"  # 32 mixed characters

SAMPLES = {
    "private-key": "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEow\n",
    "aws-access-key": "AKIA" + "Q3XZ7P2M9K4L8N5R",
    "github-token": "ghp" + "_" + ALNUM + "wXyZ",
    "github-token-fine": "github" + "_pat_" + (ALNUM * 3)[:82],
    "notion-token": "ntn" + "_" + ALNUM + "abcdefghijklmn",
    "notion-legacy": "secret" + "_" + (ALNUM * 2)[:43],
    "slack-token": "xoxb" + "-123456789012-1234567890123-" + ALNUM[:24],
    "atlassian-token": "ATATT3" + "xFfGF0" + ALNUM + ALNUM,
    # Security 4b L-4
    "google-api-key": "AI" + "za" + (ALNUM + "Sy_-")[:35],
    "anthropic-key": "sk-" + "ant-api03-" + ALNUM,
    "openai-key": "sk-" + "proj-" + ALNUM,
    "openai-legacy": "sk-" + (ALNUM * 2)[:48],
    "stripe-key": "sk" + "_live_" + ALNUM[:24],
    "stripe-restricted": "rk" + "_test_" + ALNUM[:24],
    "gitlab-token": "gl" + "pat-" + ALNUM[:20],
    "jwt": "ey" + "JhbGciOiJIUzI1NiJ9." + "ey" + "JzdWIiOiIxMjM0In0." + ALNUM[:22],
    "url-credentials": "postgres" + "://app:" + "S3cr3tPw" + "@db.internal:5432/main",
}
KIND = {"github-token-fine": "github-token", "notion-legacy": "notion-token", "openai-legacy": "openai-key",
        "stripe-restricted": "stripe-key"}


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_each_high_confidence_shape_is_detected(name):
    text = f"설정 예시\n값: {SAMPLES[name]}\n끝"
    assert secret_scan.secret_kinds(text) == [KIND.get(name, name)]


def test_reason_names_kinds_only_never_the_value():
    text = SAMPLES["aws-access-key"] + " and " + SAMPLES["github-token"]
    reason = secret_scan.skip_reason(text)
    assert reason == "secret pattern detected: aws-access-key, github-token"
    for value in (SAMPLES["aws-access-key"], SAMPLES["github-token"]):
        assert value not in reason and value[4:12] not in reason


@pytest.mark.parametrize("text", [
    "password: 8자 이상, 영문·숫자 혼합",
    "api_key 는 env 로 주입한다. secret 은 저장하지 않는다.",
    "Authorization: Bearer <token>",
    "NOTION_TOKEN 은 ntn_ 또는 secret_ 접두를 가진다.",
    "Slack 토큰(xoxb-your-token-here)은 env 로만 받는다.",
    "GitHub 토큰 형식 ghp_xxx 는 커밋하지 않는다.",
    "AWS 키(AKIA…)와 PEM 헤더(-----BEGIN PUBLIC KEY-----)는 예시다.",
    "secret_key = os.environ['SECRET_KEY']",
    "sk-learn 과 xoxo 는 토큰이 아니다. ATATT 접두만으로는 걸리지 않는다.",
    "AKIA" + "Q3XZ7P2M9K4L8N5RX 는 21자라 경계에 걸리지 않는다.",
    "scikit 의 sk-learn-pipeline-builder-module 은 패키지 이름이다.",
    "DB 는 postgres://user:<password>@db:5432 또는 mysql://app:${DB_PASSWORD}@host 로 설정한다.",
    "URL https://github.com/acme/svc/pull/12 와 mailto:dev@example.com 은 비밀값이 아니다.",
    "Google 키는 AIza 로 시작하고 OpenAI 키는 sk- 로 시작한다. JWT 는 eyJ... 형식이다.",
])
def test_ordinary_prose_and_placeholders_are_not_flagged(text):
    assert secret_scan.secret_kinds(text) == []
    assert secret_scan.skip_reason(text) is None


def test_kinds_are_unique_and_in_declaration_order():
    text = SAMPLES["slack-token"] + SAMPLES["private-key"] + " " + SAMPLES["slack-token"]
    assert secret_scan.secret_kinds(text) == ["private-key", "slack-token"]
