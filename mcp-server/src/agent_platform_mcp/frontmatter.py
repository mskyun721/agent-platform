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
