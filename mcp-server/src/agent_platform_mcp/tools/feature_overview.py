"""Target-neutral feature overview Markdown, shared by the Confluence and Notion publishers."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from agent_platform_mcp import markdown_blocks, secret_scan
from agent_platform_mcp.config import docs_dir
from agent_platform_mcp.tools.feature import _ensure_safe_name, _safe_path

_FLOW_NOTE_ATTACHED = "원본 FLOW.drawio 는 이 페이지에 첨부된다. 편집은 draw.io 로."
_FLOW_NOTE_LOCAL = "원본은 feature 디렉터리의 FLOW.drawio 다. 편집은 draw.io 로."

# Sections of the PRD a reviewer reads first; everything else stays on the PRD child page.
_OVERVIEW_SECTION_KEYWORDS = ("검토 요청", "개요", "범위", "API 요약", "처리 흐름")


def _inside(path: Path, feature_dir: Path) -> bool:
    """A regular file that is not a symlink and resolves inside the feature directory (BR-12)."""
    return (not path.is_symlink() and path.is_file()
            and path.resolve().is_relative_to(feature_dir.resolve()))


OUTSIDE = "symlink or outside feature directory"


def blocked_reason(path: Path, feature_dir: Path) -> str | None:
    """Why `path` must not leave the machine: outside the feature directory (BR-12) or a
    high-confidence secret in it (SECURITY M-2). An unreadable file is not blocked here so
    the publisher reports its read error as before."""
    if not _inside(path, feature_dir):
        return OUTSIDE
    try:
        return secret_scan.skip_reason(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def feature_location(feature_name: str, project: Path) -> tuple[str, Path]:
    """`(<type>/<name>, feature directory)` for a safe name whose directory, and every parent up
    to `project`, is not a symlink and stays inside it. Raises ValueError otherwise; shared by
    every publisher entry point (SECURITY L-3)."""
    _ensure_safe_name(feature_name)
    key = feature_name if "/" in feature_name else f"features/{feature_name}"
    feature_dir = docs_dir(key, project_dir=project)
    _safe_path(feature_dir, project)
    return key, feature_dir


def attachment_blocked_reason(path: Path, feature_dir: Path) -> str | None:
    """Like `blocked_reason`, but fail-closed for a file sent as-is (FLOW.drawio attachment):
    one the secret scan cannot read — not UTF-8, unreadable, not XML or a compressed diagram
    page — is blocked too (SECURITY L-4)."""
    if not _inside(path, feature_dir):
        return OUTSIDE
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "cannot scan for secrets: not UTF-8 text"
    except OSError:
        return "cannot scan for secrets: unreadable"
    reason = secret_scan.skip_reason(text)
    if reason:
        return reason
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return "cannot scan for secrets: not draw.io XML"
    for page in root.iter("diagram"):
        if page.find("mxGraphModel") is None and (page.text or "").strip():
            return "cannot scan for secrets: compressed diagram"
    return None


def publishable_files(feature_dir: Path) -> tuple[list[Path], list[tuple[str, str]]]:
    """`*.md` to publish and `(file name, reason)` for the ones skipped, shared by every
    publisher and its dry-run so the plan and the real run agree (DECISIONS ADR-012)."""
    files: list[Path] = []
    skipped: list[tuple[str, str]] = []
    for path in sorted(feature_dir.glob("*.md")):
        reason = blocked_reason(path, feature_dir)
        if reason:
            skipped.append((path.name, reason))
        else:
            files.append(path)
    return files, skipped


def build_overview_markdown(feature_name: str, feature_dir: Path, attached_flow: bool = True,
                            documents: list[Path] | None = None) -> str:
    """Feature overview page: review requests, summary, scope, API summary, flow (Mermaid text
    from FLOW.drawio) and links to the document pages. Built from the PRD so the Confluence
    page and the local REVIEW-VIEW.html say the same thing. `attached_flow=False` (Notion,
    which gets no attachment) changes only the note under the flow heading. A symlinked or
    escaping PRD.md/FLOW.drawio is never read, and one holding a secret pattern is left out.
    `documents` lists the pages actually published (default: every `*.md`)."""
    from agent_platform_mcp.tools.feature_view import drawio_to_mermaid

    prd = feature_dir / "PRD.md"
    out: list[str] = [f"# {feature_name}", ""]
    prd_reason = blocked_reason(prd, feature_dir)
    if prd_reason and prd_reason != OUTSIDE:
        out.append("_PRD.md 제외 (비밀값 의심)_\n")
    elif not prd_reason:
        blocks = markdown_blocks.parse(prd.read_text(encoding="utf-8"))
        for section in markdown_blocks.sections(blocks):
            if section["level"] == 2 and any(k in section["title"] for k in _OVERVIEW_SECTION_KEYWORDS):
                out.append(f"## {section['title']}")
                out.append(_blocks_to_markdown(section["blocks"]))
                out.append("")
    else:
        out.append("_PRD.md 없음_\n")
    flow = feature_dir / "FLOW.drawio"
    if not blocked_reason(flow, feature_dir):
        try:
            graphs = drawio_to_mermaid(flow.read_text(encoding="utf-8"))
        except (ET.ParseError, UnicodeDecodeError):  # unreadable flow: section left out
            graphs = []
        if graphs:
            out.append("## 서비스 흐름 (FLOW.drawio 텍스트 뷰)")
            out.append(_FLOW_NOTE_ATTACHED if attached_flow else _FLOW_NOTE_LOCAL)
            out.extend(f"```mermaid\n{g}\n```" for g in graphs)
            out.append("")
    out.append("## 문서")
    names = documents if documents is not None else feature_dir.glob("*.md")
    out.extend(f"- {p.stem}" for p in sorted(names))
    out.append("")
    return "\n".join(out)


def _blocks_to_markdown(blocks: list[dict[str, Any]]) -> str:
    """Round-trip parsed blocks back to Markdown (enough for the PRD's own vocabulary)."""
    out: list[str] = []
    for block in blocks:
        kind = block["type"]
        if kind == "heading":
            out.append(f"{'#' * block['level']} {block['text']}")
        elif kind == "para":
            out.append("\n".join(block["lines"]))
        elif kind == "ul":
            out.extend(f"- {i}" for i in block["items"])
        elif kind == "ol":
            out.extend(f"{n}. {i}" for n, i in enumerate(block["items"], 1))
        elif kind == "tasks":
            out.extend(f"- [{'x' if d else ' '}] {t}" for d, t in block["items"])
        elif kind == "code":
            out.append(f"```{block['lang']}\n{block['body']}\n```")
        elif kind == "table":
            out.append("| " + " | ".join(block["header"]) + " |")
            out.append("|" + "---|" * len(block["header"]))
            out.extend("| " + " | ".join(c.replace("|", "\\|") for c in row) + " |" for row in block["rows"])
        elif kind == "quote":
            out.extend(f"> {l}" for l in block["lines"])
        elif kind == "hr":
            out.append("---")
        out.append("")
    return "\n".join(out).rstrip()
