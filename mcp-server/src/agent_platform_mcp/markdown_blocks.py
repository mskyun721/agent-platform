"""Block-level Markdown parser with two renderers: Confluence storage format and plain HTML.

The platform's artifacts are Markdown with a small, fixed vocabulary — headings, paragraphs,
bullet/numbered lists, task lists (`- [ ]`), pipe tables, blockquotes, fenced code and rules.
One parser produces a block list; `render_storage` (Confluence) and `render_html` (the local
review view) emit from it, so a shape added here reaches both outputs.
"""

from __future__ import annotations

import html
import re
from typing import Any

Block = dict[str, Any]

_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n?", re.DOTALL)
_TABLE_SEP_RE = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_TASK_RE = re.compile(r"^[-*]\s+\[( |x|X)\]\s+(.*)")
_UL_RE = re.compile(r"^[-*]\s+(.*)")
_OL_RE = re.compile(r"^\d+\.\s+(.*)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)")
_FENCE_RE = re.compile(r"^```(\w*)\s*$")


def strip_frontmatter(text: str) -> str:
    """Remove a leading YAML front-matter block if present."""
    return _FRONTMATTER_RE.sub("", text, count=1).lstrip("\n")


def inline(text: str) -> str:
    """Inline Markdown → HTML for one line (escapes HTML first)."""
    result = html.escape(text)
    # Code spans are literal: lift them out before emphasis so `status_update` keeps its underscores.
    codes: list[str] = []

    def keep(m: re.Match[str]) -> str:
        codes.append(f"<code>{m.group(1)}</code>")
        return f"\x00{len(codes) - 1}\x00"

    result = re.sub(r"`([^`]+)`", keep, result)
    result = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", result)
    result = re.sub(r"__(.+?)__", r"<strong>\1</strong>", result)
    result = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", result)
    # `_` emphasis only at word edges, so snake_case identifiers outside backticks survive too.
    result = re.sub(r"(?<![\w_])_(?!_)(\S(?:.*?\S)?)_(?![\w_])", r"<em>\1</em>", result)
    # `![alt](attachment:file.png)` embeds a page attachment (Confluence storage format).
    result = re.sub(
        r"!\[[^\]]*\]\(attachment:([^)\s]+)\)",
        r'<ac:image ac:width="1200"><ri:attachment ri:filename="\1" /></ac:image>',
        result,
    )
    result = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', result)
    result = re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], result)
    return result


def _split_row(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    cells = re.split(r"(?<!\\)\|", body)
    return [c.replace("\\|", "|").strip() for c in cells]


def parse(md: str) -> list[Block]:
    """Parse Markdown into a flat block list (front-matter dropped)."""
    lines = strip_frontmatter(md).split("\n")
    blocks: list[Block] = []
    para: list[str] = []
    items: list[str] = []
    item_kind: str | None = None  # "ul" | "ol" | "tasks"
    quote: list[str] = []
    i = 0

    def flush_para() -> None:
        nonlocal para
        if para:
            blocks.append({"type": "para", "lines": para})
            para = []

    def flush_items() -> None:
        nonlocal items, item_kind
        if items:
            blocks.append({"type": item_kind, "items": items})
            items = []
            item_kind = None

    def flush_quote() -> None:
        nonlocal quote
        if quote:
            blocks.append({"type": "quote", "lines": quote})
            quote = []

    def flush_all() -> None:
        flush_para()
        flush_items()
        flush_quote()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        fence = _FENCE_RE.match(stripped)
        if fence:
            flush_all()
            lang = fence.group(1)
            body: list[str] = []
            i += 1
            while i < len(lines) and lines[i].strip() != "```":
                body.append(lines[i])
                i += 1
            blocks.append({"type": "code", "lang": lang, "body": "\n".join(body)})
            i += 1
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush_all()
            blocks.append({"type": "heading", "level": len(heading.group(1)), "text": heading.group(2).strip()})
            i += 1
            continue

        if stripped in ("---", "***", "___"):
            flush_all()
            blocks.append({"type": "hr"})
            i += 1
            continue

        if stripped.startswith("|") and i + 1 < len(lines) and _TABLE_SEP_RE.match(lines[i + 1].strip()):
            flush_all()
            header = _split_row(line)
            rows: list[list[str]] = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_split_row(lines[i]))
                i += 1
            blocks.append({"type": "table", "header": header, "rows": rows})
            continue

        if stripped.startswith(">"):
            flush_para()
            flush_items()
            quote.append(stripped[1:].strip())
            i += 1
            continue

        task = _TASK_RE.match(line)
        if task:
            flush_para()
            flush_quote()
            if item_kind != "tasks":
                flush_items()
                item_kind = "tasks"
            items.append((task.group(1).lower() == "x", task.group(2)))
            i += 1
            continue

        ul = _UL_RE.match(line)
        if ul:
            flush_para()
            flush_quote()
            if item_kind != "ul":
                flush_items()
                item_kind = "ul"
            items.append(ul.group(1))
            i += 1
            continue

        ol = _OL_RE.match(line)
        if ol:
            flush_para()
            flush_quote()
            if item_kind != "ol":
                flush_items()
                item_kind = "ol"
            items.append(ol.group(1))
            i += 1
            continue

        if stripped == "":
            flush_all()
            i += 1
            continue

        flush_items()
        flush_quote()
        para.append(line)
        i += 1

    flush_all()
    return blocks


def sections(blocks: list[Block]) -> list[Block]:
    """Group blocks under their nearest heading: [{title, level, blocks}]; a leading
    heading-less run gets title ''."""
    result: list[Block] = []
    current: Block = {"title": "", "level": 0, "blocks": []}
    for block in blocks:
        if block["type"] == "heading":
            if current["blocks"] or current["title"]:
                result.append(current)
            current = {"title": block["text"], "level": block["level"], "blocks": []}
        else:
            current["blocks"].append(block)
    if current["blocks"] or current["title"]:
        result.append(current)
    return result


def find_section(blocks: list[Block], keyword: str) -> Block | None:
    """First section whose heading contains `keyword`, with any deeper sub-sections folded in."""
    grouped = sections(blocks)
    for index, section in enumerate(grouped):
        if keyword in section["title"]:
            merged = {"title": section["title"], "level": section["level"], "blocks": list(section["blocks"])}
            for sub in grouped[index + 1:]:
                if sub["level"] <= section["level"]:
                    break
                merged["blocks"].append({"type": "heading", "level": sub["level"], "text": sub["title"]})
                merged["blocks"].extend(sub["blocks"])
            return merged
    return None


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def render_storage(blocks: list[Block]) -> str:
    """Confluence storage format (XHTML subset + ac: macros)."""
    parts: list[str] = []
    for block in blocks:
        kind = block["type"]
        if kind == "heading":
            parts.append(f"<h{block['level']}>{inline(block['text'])}</h{block['level']}>")
        elif kind == "para":
            parts.append(f"<p>{'<br />'.join(inline(l) for l in block['lines'])}</p>")
        elif kind in ("ul", "ol"):
            parts.append(f"<{kind}>")
            parts.extend(f"<li>{inline(item)}</li>" for item in block["items"])
            parts.append(f"</{kind}>")
        elif kind == "tasks":
            parts.append("<ac:task-list>")
            for done, text in block["items"]:
                status = "complete" if done else "incomplete"
                parts.append(
                    f"<ac:task><ac:task-status>{status}</ac:task-status>"
                    f"<ac:task-body>{inline(text)}</ac:task-body></ac:task>"
                )
            parts.append("</ac:task-list>")
        elif kind == "code":
            lang_param = (
                f'<ac:parameter ac:name="language">{html.escape(block["lang"])}</ac:parameter>' if block["lang"] else ""
            )
            parts.append(
                f'<ac:structured-macro ac:name="code">{lang_param}'
                f"<ac:plain-text-body><![CDATA[{block['body']}]]></ac:plain-text-body></ac:structured-macro>"
            )
        elif kind == "table":
            head = "".join(f"<th>{inline(c)}</th>" for c in block["header"])
            body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>" for row in block["rows"])
            parts.append(f"<table><tbody><tr>{head}</tr>{body}</tbody></table>")
        elif kind == "quote":
            parts.append(f"<blockquote><p>{'<br />'.join(inline(l) for l in block['lines'])}</p></blockquote>")
        elif kind == "hr":
            parts.append("<hr />")
    return "\n".join(parts)


def render_html(blocks: list[Block]) -> str:
    """Plain HTML for a browser; Mermaid fences become `<pre class="mermaid">` for mermaid.js."""
    parts: list[str] = []
    for block in blocks:
        kind = block["type"]
        if kind == "heading":
            parts.append(f"<h{block['level']}>{inline(block['text'])}</h{block['level']}>")
        elif kind == "para":
            parts.append(f"<p>{'<br>'.join(inline(l) for l in block['lines'])}</p>")
        elif kind in ("ul", "ol"):
            parts.append(f"<{kind}>" + "".join(f"<li>{inline(i)}</li>" for i in block["items"]) + f"</{kind}>")
        elif kind == "tasks":
            lis = "".join(
                f'<li><input type="checkbox" disabled{" checked" if done else ""}> {inline(text)}</li>'
                for done, text in block["items"]
            )
            parts.append(f'<ul class="tasks">{lis}</ul>')
        elif kind == "code":
            if block["lang"] == "mermaid":
                parts.append(f'<pre class="mermaid">{html.escape(block["body"])}</pre>')
            else:
                cls = f' class="language-{html.escape(block["lang"])}"' if block["lang"] else ""
                parts.append(f"<pre><code{cls}>{html.escape(block['body'])}</code></pre>")
        elif kind == "table":
            head = "".join(f"<th>{inline(c)}</th>" for c in block["header"])
            body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>" for row in block["rows"])
            parts.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")
        elif kind == "quote":
            parts.append(f"<blockquote><p>{'<br>'.join(inline(l) for l in block['lines'])}</p></blockquote>")
        elif kind == "hr":
            parts.append("<hr>")
    return "\n".join(parts)
