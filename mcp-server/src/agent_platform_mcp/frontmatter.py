"""Minimal YAML-ish Front-matter parser.

Only supports the small subset used by agent-platform templates:
scalar key/value pairs, plus a single nested `links:` block with
string values. Keeps the server dependency-free.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)


def parse(text: str) -> dict[str, Any] | None:
    match = FRONT_MATTER_RE.match(text)
    if not match:
        return None
    body = match.group(1)
    data: dict[str, Any] = {}
    current_block: str | None = None
    for raw_line in body.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.startswith("  ") and current_block:
            key, _, value = raw_line.strip().partition(":")
            if key:
                data[current_block][key.strip()] = value.strip().strip('"').strip("'")
            continue
        key, sep, value = raw_line.partition(":")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if value == "":
            data[key] = {}
            current_block = key
        else:
            data[key] = value.strip('"').strip("'")
            current_block = None
    return data


def read(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return parse(path.read_text(encoding="utf-8"))


_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")


def update(text: str, changes: dict[str, str | None]) -> str:
    """Set (str) or remove (None) top-level scalar keys; every other byte is kept.

    A new key is appended before the closing `---`. Raises ValueError when the
    front-matter is missing, a key is a nested block (e.g. `links:`), or a value
    would not read back unchanged through `parse` (newline, quotes, empty).
    """
    match = FRONT_MATTER_RE.match(text)
    if not match:
        raise ValueError("front-matter missing")
    for key, value in changes.items():
        if not _KEY_RE.fullmatch(key):
            raise ValueError(f"invalid front-matter key: {key!r}")
        if value is not None and (not isinstance(value, str) or "\n" in value or "\r" in value):
            raise ValueError(f"invalid front-matter value for '{key}'")
    pending, seen, out = dict(changes), set(), []
    for line in match.group(1).split("\n"):
        key, sep, rest = line.partition(":")
        key = key.strip() if sep and not line.startswith((" ", "\t")) else None
        if key in seen:
            continue  # a later duplicate would override the new value on read
        if key in pending:
            if rest.strip() == "":
                raise ValueError(f"front-matter key '{key}' is a block, not a scalar")
            seen.add(key)
            if (value := pending.pop(key)) is not None:
                out.append(f"{key}: {value}")
            continue
        out.append(line)
    out += [f"{key}: {value}" for key, value in pending.items() if value is not None]
    start, end = match.span(1)
    updated = text[:start] + "\n".join(out) + text[end:]
    parsed = parse(updated) or {}
    for key, value in changes.items():
        if (parsed.get(key) if value is not None else key in parsed) != (value if value is not None else False):
            raise ValueError(f"front-matter value for '{key}' does not round-trip")
    return updated
