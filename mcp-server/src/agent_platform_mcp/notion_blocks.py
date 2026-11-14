"""Notion block renderer for `markdown_blocks.parse` output.

The parser is shared with the Confluence and HTML renderers so all three targets read a
document the same way; only the emitting differs. Notion API limits handled here:
2000 chars per rich_text item, 100 rich_text items per array, 100 children per request
(see `split_block`). Images are not uploaded: `![alt](src)` stays literal text.
"""

from __future__ import annotations

import re
from typing import Any

from agent_platform_mcp.markdown_blocks import Block

MAX_TEXT = 2000
MAX_RICH_ITEMS = 100
MAX_CHILDREN = 100

LANGUAGES = frozenset({
    "abap", "agda", "arduino", "assembly", "bash", "basic", "bnf", "c", "c#", "c++",
    "clojure", "coffeescript", "coq", "css", "dart", "dhall", "diff", "docker", "ebnf",
    "elixir", "elm", "erlang", "f#", "flow", "fortran", "gherkin", "glsl", "go", "graphql",
    "groovy", "haskell", "hcl", "html", "idris", "java", "javascript", "json", "julia",
    "kotlin", "latex", "less", "lisp", "livescript", "llvm ir", "lua", "makefile",
    "markdown", "markup", "matlab", "mathematica", "mermaid", "nix", "notion formula",
    "objective-c", "ocaml", "pascal", "perl", "php", "plain text", "powershell", "prolog",
    "protobuf", "purescript", "python", "r", "racket", "reason", "ruby", "rust", "sass",
    "scala", "scheme", "scss", "shell", "smalltalk", "solidity", "sql", "swift", "toml",
    "typescript", "vb.net", "verilog", "vhdl", "visual basic", "webassembly", "xml", "yaml",
})
LANGUAGE_ALIASES = {
    "kt": "kotlin", "kts": "kotlin", "py": "python", "js": "javascript", "ts": "typescript",
    "sh": "shell", "zsh": "shell", "console": "shell", "yml": "yaml", "md": "markdown",
    "dockerfile": "docker", "cs": "c#", "csharp": "c#", "cpp": "c++", "golang": "go",
    "rb": "ruby", "rs": "rust", "proto": "protobuf", "ps1": "powershell", "tf": "hcl",
    "gradle": "groovy", "jsonc": "json", "htm": "html", "objc": "objective-c",
}

# Images first so the `[..](..)` inside them is never read as a link.
_INLINE_RE = re.compile(
    r"(?P<image>!\[[^\]]*\]\([^)\s]+\))"
    r"|`(?P<code>[^`]+)`"
    r"|\[(?P<label>[^\]]+)\]\((?P<href>[^)]+)\)"
    r"|\*\*(?P<bold>.+?)\*\*|__(?P<bold2>.+?)__"
    r"|(?<!\*)\*(?!\*)(?P<italic>.+?)(?<!\*)\*(?!\*)"
    r"|(?<![\w_])_(?!_)(?P<italic2>\S(?:.*?\S)?)_(?![\w_])"
)
_HTTP_URL_RE = re.compile(r"^https?://\S+$")


def text_items(content: str, *, link: str | None = None, **annotations: Any) -> list[dict]:
    """Plain text → rich_text items, split at the 2000-char limit."""
    items = []
    for start in range(0, len(content), MAX_TEXT):
        text: dict[str, Any] = {"content": content[start:start + MAX_TEXT]}
        if link:
            text["link"] = {"url": link}
        item: dict[str, Any] = {"type": "text", "text": text}
        if annotations:
            item["annotations"] = annotations
        items.append(item)
    return items


def rich_text(text: str) -> list[dict]:
    """Inline Markdown (code, http(s) links, bold, italic) → rich_text. Relative links keep
    only their label; image references stay literal text (no upload)."""
    items: list[dict] = []
    pos = 0
    for m in _INLINE_RE.finditer(text):
        items += text_items(text[pos:m.start()])
        if m.group("image"):
            items += text_items(m.group("image"))
        elif m.group("code") is not None:
            items += text_items(m.group("code"), code=True)
        elif m.group("label") is not None:
            href = m.group("href").strip()
            items += text_items(m.group("label"), link=href if _HTTP_URL_RE.match(href) else None)
        elif m.group("bold") or m.group("bold2"):
            items += text_items(m.group("bold") or m.group("bold2"), bold=True)
        else:
            items += text_items(m.group("italic") or m.group("italic2"), italic=True)
        pos = m.end()
    items += text_items(text[pos:])
    return items


def _lines(lines: list[str]) -> list[dict]:
    rich: list[dict] = []
    for n, line in enumerate(lines):
        if n:
            rich += text_items("\n")
        rich += rich_text(line)
    return rich


def block(kind: str, **payload: Any) -> dict:
    return {"object": "block", "type": kind, kind: payload}


def _text_blocks(kind: str, rich: list[dict], **extra: Any) -> list[dict]:
    """One block per 100 rich_text items (Notion's array limit); never an empty list."""
    if not rich:
        return [block(kind, rich_text=[], **extra)]
    return [block(kind, rich_text=rich[i:i + MAX_RICH_ITEMS], **extra)
            for i in range(0, len(rich), MAX_RICH_ITEMS)]


def code_language(lang: str) -> str:
    lang = lang.strip().lower()
    lang = LANGUAGE_ALIASES.get(lang, lang)
    return lang if lang in LANGUAGES else "plain text"


def _table(header: list[str], rows: list[list[str]]) -> dict:
    width = max(1, len(header))

    def row(cells: list[str]) -> dict:
        cells = (cells + [""] * width)[:width]
        return block("table_row", cells=[rich_text(c)[:MAX_RICH_ITEMS] for c in cells])

    return block("table", table_width=width, has_column_header=True, has_row_header=False,
                 children=[row(header), *(row(r) for r in rows)])


def render_notion(blocks: list[Block]) -> list[dict]:
    """Parsed Markdown blocks → Notion block objects (children nested only in tables)."""
    out: list[dict] = []
    for item in blocks:
        kind = item["type"]
        if kind == "heading":
            out += _text_blocks(f"heading_{min(item['level'], 3)}", rich_text(item["text"]))
        elif kind == "para":
            out += _text_blocks("paragraph", _lines(item["lines"]))
        elif kind in ("ul", "ol"):
            name = "bulleted_list_item" if kind == "ul" else "numbered_list_item"
            for entry in item["items"]:
                out += _text_blocks(name, rich_text(entry))
        elif kind == "tasks":
            for done, entry in item["items"]:
                out += _text_blocks("to_do", rich_text(entry), checked=bool(done))
        elif kind == "code":
            out += _text_blocks("code", text_items(item["body"]), language=code_language(item["lang"]))
        elif kind == "table":
            out.append(_table(item["header"], item["rows"]))
        elif kind == "quote":
            out += _text_blocks("quote", _lines(item["lines"]))
        elif kind == "hr":
            out.append(block("divider"))
        else:  # unknown shape: keep its text rather than drop it
            out += _text_blocks("paragraph", text_items(str(item.get("text", ""))))
    return out


def split_block(item: dict) -> tuple[dict, list[dict]]:
    """Return (block to send now, children to append to it after it exists).

    One request may nest children two levels deep and carry 100 children per parent. When
    a child has children of its own, all children are deferred; otherwise children beyond
    the first 100 (long tables) are.
    """
    payload = item.get(item["type"])
    children = payload.get("children") if isinstance(payload, dict) else None
    if not children:
        return item, []
    if any(child.get(child["type"], {}).get("children") for child in children):
        keep, rest = [], children
    elif len(children) > MAX_CHILDREN:
        keep, rest = children[:MAX_CHILDREN], children[MAX_CHILDREN:]
    else:
        return item, []
    new_payload = dict(payload)
    if keep:
        new_payload["children"] = keep
    else:
        new_payload.pop("children")
    return {**item, item["type"]: new_payload}, rest


def needs_deferral(item: dict) -> bool:
    return bool(split_block(item)[1])


def chunks(items: list[dict], size: int = MAX_CHILDREN) -> list[list[dict]]:
    return [items[i:i + size] for i in range(0, len(items), size)]
