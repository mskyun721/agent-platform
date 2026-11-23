"""High-confidence secret detection for documents that leave the machine (publish).

Only vendor-prefixed token shapes, JWTs, credentials inside URLs and PEM private-key headers count, so ordinary prose
("password: 8자 이상", "Bearer <token>", "ntn_ 접두") is not flagged. Results name the
pattern kind only; a matched value or any part of it is never returned (SECURITY M-2).
`stdout_artifacts._mask` is not reused: its `password=`/`secret:` keyword rule would flag
requirement documents (DECISIONS ADR-011).
"""

from __future__ import annotations

import re

PATTERNS: dict[str, re.Pattern[str]] = {
    "private-key": re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"),
    "aws-access-key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "github-token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b"),
    "notion-token": re.compile(r"\b(?:ntn_[A-Za-z0-9]{40,}|secret_[A-Za-z0-9]{43})\b"),
    "slack-token": re.compile(r"\bxox[abpr]-[0-9]{6,}-[A-Za-z0-9-]{8,}"),
    "atlassian-token": re.compile(r"\bATATT3[A-Za-z0-9_=-]{40,}"),
    # Security 4b L-4: more vendor prefixes, each with a length that ordinary prose does not reach.
    "google-api-key": re.compile(r"(?<![A-Za-z0-9_-])AIza[0-9A-Za-z_-]{35}(?![A-Za-z0-9_-])"),
    "anthropic-key": re.compile(r"(?<![A-Za-z0-9_-])sk-ant-[A-Za-z0-9_-]{20,}"),
    # `sk-` + 20 or more key characters with a digit (OpenAI style); `sk-learn` and slugs stay out.
    "openai-key": re.compile(r"(?<![A-Za-z0-9_-])sk-(?!ant-)(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{20,}"),
    "stripe-key": re.compile(r"\b(?:sk|rk)_(?:live|test)_[0-9A-Za-z]{16,}"),
    "gitlab-token": re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    # `scheme://user:password@host`; a placeholder password (`<pw>`, `${PW}`, `{pw}`, `***`) is not one.
    "url-credentials": re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://[^/\s:@]+:(?![<{$*])[^/\s@]+@"),
}


def secret_kinds(text: str) -> list[str]:
    """Names of the patterns found in `text`, in declaration order."""
    return [name for name, pattern in PATTERNS.items() if pattern.search(text)]


def skip_reason(text: str) -> str | None:
    """`"secret pattern detected: <kinds>"` when `text` must not be published, else None."""
    kinds = secret_kinds(text)
    return f"secret pattern detected: {', '.join(kinds)}" if kinds else None
