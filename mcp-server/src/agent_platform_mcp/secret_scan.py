"""High-confidence secret detection for documents that leave the machine (publish).

Only vendor-prefixed token shapes and PEM private-key headers count, so ordinary prose
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
}


def secret_kinds(text: str) -> list[str]:
    """Names of the patterns found in `text`, in declaration order."""
    return [name for name, pattern in PATTERNS.items() if pattern.search(text)]


def skip_reason(text: str) -> str | None:
    """`"secret pattern detected: <kinds>"` when `text` must not be published, else None."""
    kinds = secret_kinds(text)
    return f"secret pattern detected: {', '.join(kinds)}" if kinds else None
