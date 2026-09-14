"""Validate CLI reports before persistence; never retain invalid raw output."""

import re

BANNER_PATTERNS = (
    re.compile(r"^\s*\[AI:\s*(?:claude|codex|gemini)\s*\]\s*$", re.I),
    re.compile(r"^\s*(?:OpenAI Codex|Claude Code|codex-cli) v?\d[^\n]*$", re.I),
)
SECTIONS = {
    "reviewer": ("## 1. Summary", "## 2. Findings", "## 3. Positive", "## 4. Action Items"),
    "security": ("## 1. Risk Level", "## 2. Findings", "## 3. Checklist", "## 4. Recommendations"),
}
TITLES = {"reviewer": "REVIEW", "security": "SECURITY AUDIT"}


def _mask(text: str) -> str:
    text = re.sub(r"-----BEGIN [^-\n]*PRIVATE KEY-----.*?-----END [^-\n]*PRIVATE KEY-----",
                  lambda match: "[REDACTED PRIVATE KEY]" + "\n" * match.group().count("\n"), text, flags=re.S)
    text = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{12,}|AKIA[A-Z0-9]{16})\b", "[REDACTED]", text)
    text = re.sub(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/-]+=*", r"\1[REDACTED]", text)
    return re.sub(r"(?i)(\b(?:api[_-]?key|password|secret|access[_-]?token)\s*[:=]\s*)(?:\"[^\"\n]*\"|'[^'\n]*'|[^\s,;]+)",
                  r"\1[REDACTED]", text)


def prepare(stdout: str, *, role: str, feature: str, exit_code: int) -> tuple[str, dict]:
    title = f"# {TITLES[role]}: {feature}"
    required = (title, *SECTIONS[role])
    lines = []
    headings = set()
    masked_lines = 0
    fence = None
    for line in stdout.splitlines():
        if any(pattern.fullmatch(line) for pattern in BANNER_PATTERNS):
            masked_lines += 1
            continue
        stripped = line.strip()
        marker = re.match(r"^(`{3,}|~{3,})(.*)$", stripped)
        if marker:
            run, rest = marker.groups()
            if fence is None:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence) and not rest.strip():
                fence = None
        elif fence is None:
            headings.add(line.rstrip())
        lines.append(line)
    reasons = [f"missing heading: {heading}" for heading in required if heading not in headings]
    if exit_code:
        reasons.append("CLI exited unsuccessfully")
    if fence is not None:
        reasons.append("unclosed code fence")
    content = "\n".join(lines).strip()
    if not content.startswith(title + "\n"):
        reasons.append("report must start with the required title")
    if reasons:
        body = title + "\n\nReport rejected by format validation. Raw output was not retained.\n"
    else:
        body = _mask(content) + "\n"
        masked_lines += sum(a != b for a, b in zip(content.splitlines(), body.splitlines()))
    return body, {"artifact_status": "invalid" if reasons else "draft",
                  "artifact_invalid": bool(reasons), "invalid_reason": "; ".join(reasons),
                  "masked_lines": masked_lines, "raw_stored": False}


def metadata_prefix(prefix: str, metadata: dict) -> str:
    # Only controlled validator strings enter the minimal front-matter format.
    extra = f"artifact_invalid: {str(metadata['artifact_invalid']).lower()}\n"
    extra += f"masked_lines: {metadata['masked_lines']}\n"
    if metadata["invalid_reason"]:
        extra += f"invalid_reason: '{metadata['invalid_reason']}'\n"
    return prefix.removesuffix("---\n\n") + extra + "---\n\n"
