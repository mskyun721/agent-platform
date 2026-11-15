"""The PRD's `## 검토 요청` decision table, read by the gate (feature.py), the review page
(feature_view.py) and the publishers. Kept apart from feature_view so the gate does not
import the HTML renderer, which itself imports feature (import cycle)."""

from __future__ import annotations

import re
from typing import Any

from agent_platform_mcp import markdown_blocks

_CHECKED_RE = re.compile(r"\[x\]", re.IGNORECASE)
_UNCHECKED_RE = re.compile(r"\[ \]")


def review_request_rows(text: str) -> list[dict[str, Any]]:
    """Rows of the `## 검토 요청` table(s): {id, cells, resolved}. Rows without a checkbox
    in their last cell (e.g. "없음") are not decisions and are skipped."""
    section = markdown_blocks.find_section(markdown_blocks.parse(text), "검토 요청")
    if section is None:
        return []
    rows: list[dict[str, Any]] = []
    for block in section["blocks"]:
        if block["type"] != "table":
            continue
        for cells in block["rows"]:
            if not cells:
                continue
            decision = cells[-1]
            if not (_CHECKED_RE.search(decision) or _UNCHECKED_RE.search(decision)):
                continue
            rows.append({"id": cells[0], "cells": cells, "resolved": bool(_CHECKED_RE.search(decision))})
    return rows


def review_request_unresolved(text: str) -> list[str]:
    return [row["id"] for row in review_request_rows(text) if not row["resolved"]]
