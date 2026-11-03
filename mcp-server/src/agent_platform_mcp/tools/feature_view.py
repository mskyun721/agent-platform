"""Render a feature's planning artifacts into one human review page (`REVIEW-VIEW.html`).

Layout (user decisions 2026-10-27): the PRD's `## 검토 요청` table first; then the service flow
drawn from FLOW.drawio as an inline SVG (same boxes, colours and orthogonal arrows as the
drawing, no CDN) beside a flow↔rule table, with a clickable node detail and a prose step list;
then API summary / state machine / error cases beside the business-rule and acceptance-
criteria tables; then overview/scope and the full documents folded. Rule codes (BR-n, AC-n,
D-n …) are linked everywhere to their full text, because the reader should not have to know
the abbreviations (user feedback 2026-10-27). The page is derived from the Markdown and is
regenerated on demand, so it is kept out of git (`docs/**/REVIEW-VIEW.html` is added to the
target's .gitignore).
"""

from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_platform_mcp import flow_svg, frontmatter, markdown_blocks
from agent_platform_mcp.config import docs_dir, resolve_project
from agent_platform_mcp.tools.feature import _safe_path, canonical_feature

OUTPUT_NAME = "REVIEW-VIEW.html"
GITIGNORE_PATTERN = "docs/**/REVIEW-VIEW.html"

_CHECKED_RE = re.compile(r"\[x\]", re.IGNORECASE)
_UNCHECKED_RE = re.compile(r"\[ \]")
CODE_RE = flow_svg.CODE_RE
CODE_PREFIX = flow_svg.CODE_PREFIX


# ---------------------------------------------------------------------------
# Review-request table (the one source gate, HTML and Confluence all read)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# FLOW.drawio → graph (geometry kept) → Mermaid text (PRD §6.0a) / step list
# ---------------------------------------------------------------------------

def drawio_to_graph(xml_text: str) -> list[dict[str, Any]]:
    """One graph per diagram page (see flow_svg.parse_drawio): nodes keep the drawing's
    geometry, kind and colours; edges keep labels; `compressed` marks an unreadable page."""
    return flow_svg.parse_drawio(xml_text)


def _mermaid_label(label: str) -> str:
    return (label.replace('"', "&quot;").replace("\n", "<br/>")) or " "


def _node_form(safe_id: str, label: str, kind: str) -> str:
    lbl = f'"{_mermaid_label(label)}"'
    if kind == "db":
        return f"{safe_id}[({lbl})]"
    if kind == "decision":
        return f"{safe_id}{{{lbl}}}"
    if kind == "terminal":
        return f"{safe_id}(({lbl}))"
    return f"{safe_id}[{lbl}]"


def graph_to_mermaid(graph: dict[str, Any], direction: str = "TD") -> str:
    if graph.get("compressed"):
        return "%% (compressed page — open FLOW.drawio in diagrams.net)"
    sid = {n["id"]: f"n{i}" for i, n in enumerate(graph["nodes"])}
    lines = [f"flowchart {direction}"]
    for node in graph["nodes"]:
        lines.append("    " + _node_form(sid[node["id"]], node["label"], node["kind"]))
    for edge in graph["edges"]:
        arrow = f'-->|"{_mermaid_label(edge["label"])}"|' if edge["label"] else "-->"
        lines.append(f"    {sid[edge['source']]} {arrow} {sid[edge['target']]}")
    return "\n".join(lines)


def drawio_to_mermaid(xml_text: str, direction: str = "TD") -> list[str]:
    """One `flowchart` per diagram page; a compressed page yields a comment line."""
    return [graph_to_mermaid(g, direction) for g in drawio_to_graph(xml_text)]


def _step_order(graph: dict[str, Any]) -> list[str]:
    """Reading order for the step list: depth-first from the start nodes (no incoming edge)
    following edge order, so a branch's legs come right after their decision. Nodes that every
    leg of a branch reaches (the join, e.g. "조건부 UPDATE" after ACTIVE/INVALID) are held back
    until all legs are listed, so the list reads leg, leg, then common continuation. Unreached
    nodes (cycles, islands) are appended in document order."""
    out: dict[str, list[str]] = {n["id"]: [] for n in graph["nodes"]}
    incoming = {n["id"]: 0 for n in graph["nodes"]}
    for e in graph["edges"]:
        out[e["source"]].append(e["target"])
        incoming[e["target"]] += 1

    reach: dict[str, set[str]] = {}

    def reachable(nid: str) -> set[str]:
        if nid not in reach:
            found: set[str] = set()
            stack = [nid]
            while stack:
                cur = stack.pop()
                for nxt in out[cur]:
                    if nxt not in found:
                        found.add(nxt)
                        stack.append(nxt)
            reach[nid] = found
        return reach[nid]

    order: list[str] = []
    seen: set[str] = set()

    def visit(nid: str, blocked: frozenset[str]) -> None:
        if nid in seen or nid in blocked:
            return
        seen.add(nid)
        order.append(nid)
        legs = [t for t in out[nid] if t not in seen]
        common: set[str] = set()
        if len(legs) > 1:
            common = set.intersection(*(reachable(t) | {t} for t in legs)) - seen
        start = len(order)
        for t in legs:
            visit(t, blocked | frozenset(common))
        for cur in list(order[start:]):
            for nxt in out[cur]:
                if nxt in common:
                    visit(nxt, blocked)

    for n in graph["nodes"]:
        if incoming[n["id"]] == 0:
            visit(n["id"], frozenset())
    for n in graph["nodes"]:
        visit(n["id"], frozenset())
    return order


# ---------------------------------------------------------------------------
# Rule / criterion codes → full text (so "BR-2" never stands alone)
# ---------------------------------------------------------------------------

def _plain(cell: str) -> str:
    return re.sub(r"[`*_]", "", cell).strip()


def code_definitions(texts: list[str]) -> dict[str, dict[str, str]]:
    """Scan every table in the given Markdown texts for rows whose first cell is a code
    (BR-1, AC-3, D-10 …) and keep the rest of the row as that code's description."""
    defs: dict[str, dict[str, str]] = {}
    heading_re = re.compile(r"^((?:BR|AC|NFR|D|Q|A|R)-\d+)[.:]?\s+(.+)$")
    for text in texts:
        blocks = markdown_blocks.parse(text)
        for i, block in enumerate(blocks):
            # Decision records are headings: "## D-8. 발행은 요청 밖에서 …" (+ first paragraph).
            if block["type"] == "heading":
                m = heading_re.match(_plain(block["text"]))
                if m and m.group(1) not in defs:
                    body = ""
                    if i + 1 < len(blocks) and blocks[i + 1]["type"] == "para":
                        body = " ".join(blocks[i + 1]["lines"])
                        body = body if len(body) <= 220 else body[:217] + "…"
                    prefix = CODE_PREFIX.get(m.group(1).split("-")[0], "")
                    defs[m.group(1)] = {"prefix": prefix, "text": m.group(2) + (f" — {body}" if body else "")}
                continue
            if block["type"] != "table":
                continue
            headers = [_plain(h) for h in block["header"]]
            for row in block["rows"]:
                if not row:
                    continue
                m = CODE_RE.fullmatch(_plain(row[0]))
                if not m or _plain(row[0]) in defs:
                    continue
                code = _plain(row[0])
                rest = []
                for h, cell in zip(headers[1:], row[1:]):
                    if cell.strip():
                        rest.append(f"{h}: {cell.strip()}" if len(row) > 2 and h else cell.strip())
                defs[code] = {"prefix": CODE_PREFIX.get(m.group(1), m.group(1)), "text": " · ".join(rest)}
    return defs


def link_codes(rendered: str, defs: dict[str, dict[str, str]]) -> str:
    """Wrap codes in already-rendered inline HTML with a link to their definition row."""
    def repl(m: re.Match[str]) -> str:
        code = m.group(0)
        d = defs.get(code)
        prefix = CODE_PREFIX.get(m.group(1), m.group(1))
        if not d:
            return f'<span class="code-ref" title="{html.escape(prefix)}">{code}</span>'
        tip = html.escape(f"{prefix} {code}: {_plain(d['text'])}", quote=True)
        return f'<a class="code-ref" href="#code-{code}" title="{tip}">{code}</a>'
    return CODE_RE.sub(repl, rendered)


# ---------------------------------------------------------------------------
# HTML fragments
# ---------------------------------------------------------------------------

def _table_html(block: dict[str, Any], defs: dict[str, dict[str, str]], *, rename: dict[str, str] | None = None, anchor_codes: bool = False) -> str:
    rename = rename or {}
    head = "".join(f"<th>{markdown_blocks.inline(rename.get(_plain(c), c))}</th>" for c in block["header"])
    rows = []
    for row in block["rows"]:
        cells = []
        for i, c in enumerate(row):
            rendered = link_codes(markdown_blocks.inline(c), defs)
            if anchor_codes and i == 0 and CODE_RE.fullmatch(_plain(c)):
                code = _plain(c)
                cells.append(f'<td id="code-{code}" class="code-cell"><b>{code}</b><br><small class="muted">{html.escape(CODE_PREFIX.get(code.split("-")[0], ""))}</small></td>')
            else:
                cells.append(f"<td>{rendered}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _section_html(blocks: list[dict[str, Any]], keyword: str, defs: dict[str, dict[str, str]], *, anchor_codes: bool = False) -> str:
    """A PRD section as HTML with rule codes linked. With anchor_codes, a table row whose first
    cell is a code (the review-request table's A-1/Q-1) becomes that code's anchor instead of a
    link to itself."""
    section = markdown_blocks.find_section(blocks, keyword)
    if not section:
        return ""
    if not anchor_codes:
        return link_codes(markdown_blocks.render_html(section["blocks"]), defs)
    out = []
    for block in section["blocks"]:
        if block["type"] == "table":
            out.append(_table_html(block, defs, anchor_codes=True))
        else:
            out.append(link_codes(markdown_blocks.render_html([block]), defs))
    return "".join(out)


def _first_table(blocks: list[dict[str, Any]], keyword: str) -> dict[str, Any] | None:
    section = markdown_blocks.find_section(blocks, keyword)
    if not section:
        return None
    for block in section["blocks"]:
        if block["type"] == "table":
            return block
    return None


def _code_blocks_html(blocks: list[dict[str, Any]], keyword: str) -> str:
    section = markdown_blocks.find_section(blocks, keyword)
    if not section:
        return ""
    return markdown_blocks.render_html([b for b in section["blocks"] if b["type"] == "code"])


def _mermaid_from_prd(blocks: list[dict[str, Any]]) -> str:
    for block in blocks:
        if block["type"] == "code" and block["lang"] == "mermaid":
            return block["body"]
    return ""


def _rule_lines(codes: list[str], defs: dict[str, dict[str, str]]) -> str:
    items = []
    for code in codes:
        d = defs.get(code)
        prefix = CODE_PREFIX.get(code.split("-")[0], "")
        if d:
            items.append(f'<li><a href="#code-{code}"><b>{prefix} {code}</b></a> — {link_codes(markdown_blocks.inline(d["text"]), defs)}</li>')
        else:
            items.append(f"<li><b>{prefix} {code}</b> — <span class='muted'>정의를 문서에서 찾지 못했습니다</span></li>")
    return f'<ul class="rules">{"".join(items)}</ul>' if items else ""


def steps_html(graph: dict[str, Any], defs: dict[str, dict[str, str]] | None = None) -> str:
    """Prose rendering of a flow page: a numbered step list where decisions list their
    branches, every jump links to its target step, and the rule codes on each step are
    spelled out in full."""
    defs = defs or {}
    if graph.get("compressed"):
        return '<p class="muted">압축된 draw.io 페이지입니다 — diagrams.net 에서 "압축 해제" 후 저장하세요.</p>'
    if not graph["nodes"]:
        return '<p class="muted">도형이 없습니다.</p>'
    nodes = {n["id"]: n for n in graph["nodes"]}
    order = _step_order(graph)
    num = {nid: i + 1 for i, nid in enumerate(order)}
    outgoing: dict[str, list[dict[str, str]]] = {nid: [] for nid in nodes}
    for e in graph["edges"]:
        outgoing[e["source"]].append(e)
    items = []
    for nid in order:
        node = nodes[nid]
        lines = [ln for ln in node["label"].split("\n") if ln.strip()]
        body_lines = [ln for ln in lines if not (flow_svg._CODES_LINE_RE.match(ln) and CODE_RE.search(ln))]
        title = html.escape(body_lines[0] if body_lines else lines[0])
        detail = "".join(f'<div class="step-sub">{html.escape(ln)}</div>' for ln in body_lines[1:])
        kind = flow_svg.KIND_LABEL.get(node["kind"], "")
        mark = f'<span class="pill">{kind}</span>' if node["kind"] != "step" else ""
        change = node.get("change")
        if change in ("new", "modified", "removed"):
            mark += f' <span class="pill change-{change}">이번 작업: {flow_svg.CHANGE_LABEL[change]}</span>'
        edges = outgoing[nid]
        nexts = []
        linear = len(edges) == 1 and not edges[0]["label"] and num[edges[0]["target"]] == num[nid] + 1
        if edges and not linear:
            for e in edges:
                tnum = num[e["target"]]
                tlabel = html.escape(nodes[e["target"]]["label"].split("\n")[0])
                lbl = f'<b>{html.escape(e["label"])}</b> → ' if e["label"] else "→ "
                nexts.append(f'<li>{lbl}<a href="#step-{tnum}">{tnum}. {tlabel}</a></li>')
        elif not edges and node["kind"] not in ("terminal", "done", "return"):
            nexts.append('<li class="muted">끝</li>')
        next_html = f'<ul class="step-next">{"".join(nexts)}</ul>' if nexts else ""
        rules = _rule_lines(flow_svg.codes_in(node["label"]), defs)
        chg_cls = f' step-change-{change}' if change in ("new", "modified", "removed") else ""
        items.append(
            f'<li id="step-{num[nid]}" class="step step-{node["kind"]}{chg_cls}"><span class="step-num">{num[nid]}</span>'
            f'<div class="step-body"><div class="step-title">{title} {mark}</div>{detail}{next_html}{rules}</div></li>'
        )
    return f'<ol class="steps">{"".join(items)}</ol>'


def _node_data(graph: dict[str, Any], defs: dict[str, dict[str, str]]) -> dict[str, Any]:
    """What the page script shows when a node is clicked."""
    nodes = {n["id"]: n for n in graph["nodes"]}
    data: dict[str, Any] = {}
    for n in graph["nodes"]:
        nexts = []
        for e in graph["edges"]:
            if e["source"] == n["id"]:
                nexts.append({"label": e["label"], "to": nodes[e["target"]]["label"].split("\n")[0], "toId": e["target"]})
        change = n.get("change")
        data[n["id"]] = {
            "label": n["label"],
            "kind": flow_svg.KIND_LABEL.get(n["kind"], n["kind"]),
            "change": change if change in ("new", "modified", "removed") else "",
            "changeLabel": flow_svg.CHANGE_LABEL.get(change or "", ""),
            "rules": _rule_lines(flow_svg.codes_in(n["label"]), defs),
            "next": nexts,
        }
    return data


_STYLE = """
:root{--bg:#f4f7fb;--panel:#fff;--ink:#132238;--muted:#536579;--line:#dce5ef;--accent:#2563eb;--head:#101d35;--warn-bg:#fff7e8;--warn:#9a5b00;--ok:#1d6b3a;--th:#eef3f9}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#0f1218;--panel:#161b24;--ink:#e6e9ef;--muted:#9aa3b2;--line:#2b3340;--accent:#7aa2ff;--head:#0b1222;--warn-bg:#2a1d05;--warn:#ffd58a;--ok:#8fe0ad;--th:#1d2431}}
:root[data-theme="dark"]{--bg:#0f1218;--panel:#161b24;--ink:#e6e9ef;--muted:#9aa3b2;--line:#2b3340;--accent:#7aa2ff;--head:#0b1222;--warn-bg:#2a1d05;--warn:#ffd58a;--ok:#8fe0ad;--th:#1d2431}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.65 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR","Segoe UI",sans-serif}
header.top{position:sticky;top:0;z-index:5;background:var(--head);color:#fff;padding:14px 24px;display:flex;flex-wrap:wrap;gap:8px 20px;align-items:center;justify-content:space-between}
header.top h1{font-size:20px;margin:0}header.top small{color:#b6c8e5;display:block;margin-top:2px}header.top nav a{color:#fff;margin-left:14px;text-decoration:none;font-size:13px}header.top nav a:hover{text-decoration:underline}
main{max-width:1440px;margin:0 auto;padding:16px 24px 40px}
.pill{font-size:11.5px;padding:2px 8px;border-radius:12px;border:1px solid var(--line);color:var(--muted);background:var(--panel);vertical-align:middle;white-space:nowrap;display:inline-block}
.pill.warn{background:var(--warn-bg);color:var(--warn);border-color:transparent}.pill.ok{color:var(--ok)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin-top:16px;min-width:0}
.panel h2{font-size:17px;margin:0 0 10px}.panel h3{font-size:14.5px;margin:16px 0 6px}.panel h3:first-child{margin-top:0}
.need{border-color:#d79b00}.need h2{color:var(--warn)}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:1000px){.two{grid-template-columns:1fr}}
.layout{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(320px,1fr);gap:16px;align-items:start}@media(max-width:1100px){.layout{grid-template-columns:1fr}}
table{width:100%;border-collapse:collapse;font-size:12.5px;margin:8px 0}td,th{border:1px solid var(--line);padding:7px 8px;text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:var(--th);font-weight:600}
td:target{background:var(--warn-bg)}
pre{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px;overflow:auto;font:12px/1.6 ui-monospace,Menlo,monospace;white-space:pre-wrap}
code{font-family:ui-monospace,Menlo,monospace;font-size:.92em}
details{margin-top:12px}summary{cursor:pointer;color:var(--accent);font-weight:600}
.doc{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:4px 18px 18px;margin-top:8px}
.muted{color:var(--muted);font-size:12.5px}ul.tasks{list-style:none;padding-left:4px}
a{color:var(--accent)}blockquote{border-left:3px solid var(--line);margin:8px 0;padding:2px 12px;color:var(--muted)}
a.code-ref,span.code-ref{font-family:ui-monospace,Menlo,monospace;font-size:.9em;padding:0 4px;border-radius:4px;background:var(--th);text-decoration:none;border-bottom:1px dotted var(--accent);white-space:nowrap}
td.code-cell{white-space:nowrap}td.code-cell small{font-weight:400}
.toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 8px}.toolbar button{font:inherit;font-size:12.5px;padding:4px 10px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--accent);cursor:pointer}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:12px;color:var(--muted);margin:4px 0 10px}.dot{width:11px;height:11px;display:inline-block;margin-right:4px;border:1px solid #888;vertical-align:-1px;border-radius:2px}.dash{width:18px;display:inline-block;border-top:2px dashed #5b6b82;vertical-align:3px;margin-right:4px}
.chart{overflow:auto;max-height:80vh;border:1px solid var(--line);border-radius:8px;background:#fff}.chart svg{display:block}
.flow-svg text{font-family:"Apple SD Gothic Neo","Noto Sans KR",sans-serif;fill:#132238}.flow-svg text.codes{fill:#536579}.flow-svg .node{cursor:pointer}.flow-svg .node:hover rect,.flow-svg .node:hover polygon,.flow-svg .node:hover path{stroke-width:2.2}.flow-svg .node.active rect,.flow-svg .node.active polygon,.flow-svg .node.active path{stroke:#2563eb;stroke-width:2.5}.flow-svg .edge.active{stroke:#2563eb;stroke-width:2.2}
.dot.ring{background:transparent;border-width:2px;border-style:dashed;border-radius:4px}
.pill.change-new{background:#2563eb;color:#fff;border-color:transparent}.pill.change-modified{background:#d97706;color:#fff;border-color:transparent}.pill.change-removed{background:#b91c1c;color:#fff;border-color:transparent}
.step-change-new{box-shadow:inset 0 0 0 1.5px #2563eb}.step-change-modified{box-shadow:inset 0 0 0 1.5px #d97706}.step-change-removed{box-shadow:inset 0 0 0 1.5px #b91c1c}
.flow-svg.dim .node:not([data-change="new"]):not([data-change="modified"]):not([data-change="removed"]){opacity:.3}.flow-svg.dim .edge:not([data-change]){opacity:.3}.flow-svg.dim .edge-label,.flow-svg.dim .edge-label+rect{opacity:.6}
#dim-toggle[aria-pressed="true"]{background:var(--accent);color:#fff;border-color:var(--accent)}
.detail{border:1px solid var(--line);border-radius:8px;padding:10px 12px;background:var(--bg);min-height:56px}.detail h4{margin:0 0 4px;font-size:14px}.detail ul{margin:6px 0 0;padding-left:18px}
ul.rules{margin:6px 0 0;padding-left:18px;font-size:12.5px}ul.rules li{margin:3px 0}
ol.steps{list-style:none;padding:0;margin:8px 0 0;display:grid;gap:6px}
.step{display:flex;gap:12px;padding:8px 12px;border:1px solid var(--line);border-radius:8px;background:var(--bg);scroll-margin-top:70px}
.step:target{border-color:var(--accent);box-shadow:0 0 0 2px var(--accent) inset}
.step-decision{border-left:4px solid #d6b656}.step-done{border-left:4px solid #82b366}.step-error{border-left:4px solid #b85450}.step-warn{border-left:4px solid #d79b00}.step-return,.step-terminal{border-left:4px solid #888}.step-external,.step-db{border-left:4px solid #9673a6}
.step-num{flex:0 0 28px;height:28px;border-radius:50%;background:var(--panel);border:1px solid var(--line);display:flex;align-items:center;justify-content:center;font-size:12.5px;font-weight:600;color:var(--muted)}
.step-body{flex:1;min-width:0}.step-title{font-weight:600;font-size:14px}.step-sub{color:var(--muted);font-size:13px}
ul.step-next{margin:6px 0 0;padding-left:0;list-style:none;display:flex;flex-wrap:wrap;gap:6px 16px;font-size:13px}
[id]{scroll-margin-top:70px}
"""


def build_html(
    *,
    feature: str,
    front: dict[str, Any],
    prd_text: str,
    api_text: str | None,
    flow_pages: list[dict[str, Any]],
    flow_source: str,
    other_docs: list[str],
    extra_texts: list[str] | None = None,
) -> tuple[str, dict[str, int]]:
    blocks = markdown_blocks.parse(prd_text)
    rows = review_request_rows(prd_text)
    pending = [r for r in rows if not r["resolved"]]
    counts = {"total": len(rows), "pending": len(pending)}
    defs = code_definitions([prd_text, api_text or ""] + list(extra_texts or []))

    review_html = _section_html(blocks, "검토 요청", defs, anchor_codes=True) or '<p class="muted">검토 요청 표가 없습니다 — PRD 상단에 추가하세요.</p>'
    overview_html = _section_html(blocks, "개요", defs)
    scope_html = _section_html(blocks, "범위", defs)
    api_table = _first_table(blocks, "API")
    state_html = _code_blocks_html(blocks, "상태 전이") or _code_blocks_html(blocks, "도메인")
    error_table = _first_table(blocks, "에러")
    link_table = _first_table(blocks, "흐름-규칙") or _first_table(blocks, "6.0")
    br_table = _first_table(blocks, "비즈니스 규칙") or _first_table(blocks, "Business Rules")
    ac_table = _first_table(blocks, "수락 기준") or _first_table(blocks, "Acceptance")

    status = str(front.get("status", "?"))
    status_pill = f'<span class="pill {"ok" if status == "approved" else ""}">PRD {html.escape(status)}</span>'
    pending_pill = f'<span class="pill warn">결정 대기 {counts["pending"]}</span>' if pending else '<span class="pill ok">결정 완료</span>'
    header = (
        f'<header class="top"><div><h1>{html.escape(feature)}</h1>'
        f'<small>{html.escape(str(front.get("agent", "")))} · {html.escape(str(front.get("updated", "")))} · 원본: PRD.md · API-SPEC.md · {html.escape(flow_source)}</small></div>'
        f'<div>{status_pill} {pending_pill}</div>'
        '<nav><a href="#review">검토 요청</a><a href="#flow">서비스 흐름</a><a href="#api">API</a><a href="#rules">규칙 · 기준</a><a href="#docs">전체 문서</a></nav></header>'
    )

    # --- flow panel -------------------------------------------------------
    pages = [p for p in flow_pages if not p.get("compressed") and p["nodes"]]
    node_data: dict[str, Any] = {}
    if pages:
        page = pages[0]
        svg, _size = flow_svg.render_svg(page)
        node_data = _node_data(page, defs)
        glossary = " · ".join(f"<b>{k}</b> = {v}" for k, v in CODE_PREFIX.items() if any(c.startswith(k + "-") for n in page["nodes"] for c in n["codes"]))
        changes = flow_svg.change_counts(page)
        change_summary = " · ".join(f"{flow_svg.CHANGE_LABEL[k]} {changes[k]}" for k in ("new", "modified", "removed") if changes.get(k))
        change_button = (
            f'<button type="button" id="dim-toggle" aria-pressed="false" title="이번 작업에서 바뀌는 부분만 진하게">변경 부분만 강조</button>'
            f'<span class="muted">이번 작업: {change_summary}</span>'
            if changes else '<span class="muted">변경 표식 없음 (FLOW.drawio 셀 style 에 change=new|modified 를 적으면 강조됩니다)</span>'
        )
        chart = (
            '<div class="toolbar"><button type="button" data-zoom="-">축소</button><button type="button" data-zoom="+">확대</button>'
            '<button type="button" data-zoom="1">100%</button><button type="button" data-zoom="fit">폭 맞춤</button>'
            f'{change_button}'
            f'<a href="FLOW.drawio">FLOW.drawio 열기</a><span class="muted">{html.escape(page["name"])}'
            + (f" · 페이지 {len(pages)}개 중 1" if len(pages) > 1 else "") + "</span></div>"
            + flow_svg.legend_html(page)
            + (f'<p class="muted" style="margin:0 0 8px">{glossary} · 노드를 클릭하면 전체 설명과 관련 규칙이 오른쪽에 나옵니다.</p>' if glossary else "")
            + f'<div class="chart" id="chart">{svg}</div>'
        )
        steps = "".join(steps_html(p, defs) for p in pages)
        flow_html = (
            f'<div class="layout"><div>{chart}</div><aside>'
            '<div class="detail" id="node-detail"><span class="muted">노드를 클릭하면 설명 · 관련 규칙 · 다음 단계가 여기에 나옵니다.</span></div>'
            + (f'<h3>흐름 ↔ 규칙 · 기준</h3>{_table_html(link_table, defs, rename={"BR": "업무 규칙 (BR)", "AC": "수락 기준 (AC)"})}' if link_table else "")
            + "</aside></div>"
            f'<details><summary>단계 목록 (글로 읽기)</summary>{steps}</details>'
        )
    else:
        prd_mermaid = _mermaid_from_prd(blocks)
        if any(p.get("compressed") for p in flow_pages):
            flow_html = '<p class="muted">FLOW.drawio 가 압축 저장되어 읽을 수 없습니다 — diagrams.net 에서 "압축 해제" 후 저장하세요.</p>'
        elif prd_mermaid:
            flow_html = f'<p class="muted">FLOW.drawio 가 없고 PRD 의 mermaid 텍스트만 있습니다.</p><pre>{html.escape(prd_mermaid)}</pre>'
        else:
            flow_html = '<p class="muted">FLOW.drawio 가 없고 PRD 에 mermaid 블록도 없습니다.</p>'
        if link_table:
            flow_html += f'<h3>흐름 ↔ 규칙 · 기준</h3>{_table_html(link_table, defs, rename={"BR": "업무 규칙 (BR)", "AC": "수락 기준 (AC)"})}'

    # --- api / rules ------------------------------------------------------
    api_html = _table_html(api_table, defs) if api_table else '<p class="muted">PRD §3 API 요약 표가 없습니다 (API 변경 없음이면 정상).</p>'
    api_panel = f"<h2>API 요약</h2>{api_html}"
    if state_html:
        api_panel += f"<h3>상태 전이</h3>{state_html}"
    if error_table:
        api_panel += f"<h3>에러 케이스</h3>{_table_html(error_table, defs)}"
    rules_panel = "<h2>업무 규칙 · 수락 기준</h2>"
    if br_table:
        rules_panel += f'<h3>업무 규칙 (BR) <span class="muted">PRD §5</span></h3>{_table_html(br_table, defs, anchor_codes=True)}'
    if ac_table:
        rules_panel += f'<h3>수락 기준 (AC) <span class="muted">PRD §12</span></h3>{_table_html(ac_table, defs, anchor_codes=True)}'
    if not (br_table or ac_table):
        rules_panel += '<p class="muted">PRD 에 규칙·수락 기준 표가 없습니다.</p>'

    api_full = link_codes(markdown_blocks.render_html(markdown_blocks.parse(api_text)), defs) if api_text else '<p class="muted">API-SPEC.md 없음</p>'
    links = "".join(f'<li><a href="{html.escape(name)}">{html.escape(name)}</a></li>' for name in other_docs)
    node_json = json.dumps(node_data, ensure_ascii=False).replace("</", "<\\/")

    page_html = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(feature)} 검토</title><style>{_STYLE}</style></head>
<body>
{header}
<main>
<section id="review" class="panel need"><h2>검토 요청 — 사람이 결정할 것</h2>{review_html}</section>
<section id="flow" class="panel"><h2>서비스 흐름</h2>{flow_html}</section>
<div class="two">
  <section id="api" class="panel">{api_panel}</section>
  <section id="rules" class="panel">{rules_panel}</section>
</div>
<section class="panel"><h2>개요 · 범위</h2>{overview_html}{scope_html}</section>
<section id="docs">
<details><summary>PRD 전체</summary><div class="doc">{link_codes(markdown_blocks.render_html(blocks), defs)}</div></details>
<details><summary>API-SPEC 전체</summary><div class="doc">{api_full}</div></details>
<details><summary>다른 문서</summary><div class="doc"><ul>{links or "<li class='muted'>없음</li>"}</ul></div></details>
</section>
<p class="muted">생성 {datetime.now().strftime("%Y-%m-%d %H:%M")} · agent-platform render_feature_view · 이 파일은 md 에서 재생성되는 파생물입니다 (git 제외). 외부 스크립트 없이 열립니다.</p>
</main>
<script id="node-data" type="application/json">{node_json}</script>
<script>
(function(){{
  var svg=document.querySelector('.flow-svg');if(!svg)return;
  var chart=document.getElementById('chart'),W=+svg.dataset.w,H=+svg.dataset.h,zoom=1;
  function apply(z){{zoom=Math.max(.3,Math.min(3,z));svg.setAttribute('width',Math.round(W*zoom));svg.setAttribute('height',Math.round(H*zoom));}}
  function fit(){{apply(Math.min(1,(chart.clientWidth-2)/W));}}
  document.querySelectorAll('.toolbar [data-zoom]').forEach(function(b){{b.addEventListener('click',function(){{var z=b.dataset.zoom;if(z==='+')apply(zoom*1.2);else if(z==='-')apply(zoom/1.2);else if(z==='fit')fit();else apply(1);}});}});
  fit();
  var dim=document.getElementById('dim-toggle');
  if(dim){{dim.addEventListener('click',function(){{var on=dim.getAttribute('aria-pressed')!=='true';dim.setAttribute('aria-pressed',String(on));svg.classList.toggle('dim',on);}});}}
  var data=JSON.parse(document.getElementById('node-data').textContent),detail=document.getElementById('node-detail');
  function esc(s){{return String(s).replace(/[&<>"]/g,function(c){{return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c];}});}}
  function select(id){{
    svg.querySelectorAll('.node.active,.edge.active').forEach(function(n){{n.classList.remove('active');}});
    var g=svg.querySelector('.node[data-id="'+CSS.escape(id)+'"]');if(!g)return;g.classList.add('active');
    svg.querySelectorAll('.edge[data-from="'+CSS.escape(id)+'"],.edge[data-to="'+CSS.escape(id)+'"]').forEach(function(e){{e.classList.add('active');}});
    var d=data[id];if(!d)return;
    var next=d.next.length?'<ul>'+d.next.map(function(n){{return '<li>'+(n.label?'<b>'+esc(n.label)+'</b> → ':'→ ')+'<a href="#" data-go="'+esc(n.toId)+'">'+esc(n.to)+'</a></li>';}}).join('')+'</ul>':'';
    detail.innerHTML='<h4>'+esc(d.label.split('\\n')[0])+' <span class="pill">'+esc(d.kind)+'</span>'+(d.change?' <span class="pill change-'+d.change+'">이번 작업: '+esc(d.changeLabel)+'</span>':'')+'</h4>'+d.label.split('\\n').slice(1).map(function(l){{return '<div class="muted">'+esc(l)+'</div>';}}).join('')+(d.rules||'<p class="muted" style="margin:6px 0 0">연결된 규칙 코드가 없습니다.</p>')+(next?'<div style="margin-top:8px"><b>다음</b>'+next+'</div>':'');
    detail.querySelectorAll('[data-go]').forEach(function(a){{a.addEventListener('click',function(ev){{ev.preventDefault();select(a.dataset.go);}});}});
  }}
  svg.querySelectorAll('.node').forEach(function(g){{g.addEventListener('click',function(){{select(g.dataset.id);}});g.addEventListener('keydown',function(ev){{if(ev.key==='Enter'||ev.key===' '){{ev.preventDefault();select(g.dataset.id);}}}});}});
}})();
</script>
</body></html>
"""
    return page_html, counts


def ensure_gitignore(project: Path, pattern: str = GITIGNORE_PATTERN) -> str:
    """Append `pattern` to the project's .gitignore when the project is a git checkout."""
    if not (project / ".git").exists():
        return "skipped (not a git checkout)"
    gitignore = project / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
    if any(line.strip() == pattern for line in existing.splitlines()):
        return "present"
    prefix = "" if existing.endswith("\n") or not existing else "\n"
    gitignore.write_text(f"{existing}{prefix}# agent-platform: derived review page, regenerated from md\n{pattern}\n", encoding="utf-8")
    return "added"


def render_view(name: str, root: str | Path | None = None, gitignore: bool = True) -> dict[str, Any]:
    """Write docs/<type>/<name>/REVIEW-VIEW.html and return where it went."""
    name = canonical_feature(name)
    context = resolve_project(root)
    project = context.path
    target = docs_dir(name, project_dir=project)
    _safe_path(target, project)
    if not target.is_dir():
        return {"error": f"Feature not found: {target}"}
    prd_path = target / "PRD.md"
    if not prd_path.is_file():
        return {"error": f"PRD.md not found in {target} (the review view is built from the PRD)"}

    prd_text = prd_path.read_text(encoding="utf-8")
    front = frontmatter.read(prd_path) or {}
    api_path = target / "API-SPEC.md"
    api_text = api_path.read_text(encoding="utf-8") if api_path.is_file() else None
    extra_texts = [p.read_text(encoding="utf-8") for p in (target / "DECISIONS.md", target / "TASK.md") if p.is_file()]
    # Markdown files the PRD links to (e.g. another feature's DECISIONS.md whose D-n the PRD cites)
    # also define codes, after the feature's own documents.
    docs_root = (project / "docs").resolve()
    linked: list[Path] = []
    for rel in dict.fromkeys(re.findall(r"\]\(([^)#\s]+\.md)(?:#[^)]*)?\)", prd_text)):
        candidate = (target / rel).resolve()
        if candidate.is_file() and candidate.is_relative_to(docs_root) and candidate.parent != target:
            linked.append(candidate)
    # …and the DECISIONS.md of sibling features the PRD names ("notification-publisher D-7").
    for sibling in sorted(target.parent.iterdir()) if target.parent.is_dir() else []:
        decisions = sibling / "DECISIONS.md"
        if sibling != target and decisions.is_file() and sibling.name in prd_text and decisions not in linked:
            linked.append(decisions)
    extra_texts.extend(p.read_text(encoding="utf-8") for p in linked)

    flow_path = target / "FLOW.drawio"
    flow_pages: list[dict[str, Any]] = []
    flow_source = "FLOW.drawio 없음"
    if flow_path.is_file():
        try:
            flow_pages = drawio_to_graph(flow_path.read_text(encoding="utf-8"))
            flow_source = "FLOW.drawio"
        except ET.ParseError as exc:
            flow_source = f"FLOW.drawio 파싱 실패 ({exc})"

    other_docs = sorted(
        p.name for p in target.iterdir()
        if p.is_file() and p.name not in {"PRD.md", "API-SPEC.md", OUTPUT_NAME} and p.suffix in {".md", ".drawio", ".yaml"}
    )
    page, counts = build_html(
        feature=name, front=front, prd_text=prd_text, api_text=api_text,
        flow_pages=flow_pages, flow_source=flow_source, other_docs=other_docs, extra_texts=extra_texts,
    )
    output = target / OUTPUT_NAME
    output.write_text(page, encoding="utf-8")
    return {
        "feature": name,
        "project_dir": str(project),
        "output": str(output),
        "review_requests": counts,
        "flow": flow_source,
        "flow_nodes": sum(len(p["nodes"]) for p in flow_pages),
        "gitignore": ensure_gitignore(project) if gitignore else "not requested",
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Render docs/<type>/<name>/REVIEW-VIEW.html from PRD, API-SPEC and FLOW.drawio.")
    parser.add_argument("--feature", required=True, help="<type>/<name> (bare name = features/<name>)")
    parser.add_argument("--root", help="project root or registered project_id (default: active project)")
    parser.add_argument("--no-gitignore", action="store_true", help="do not touch the target .gitignore")
    args = parser.parse_args(argv)
    result = render_view(args.feature, root=args.root, gitignore=not args.no_gitignore)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if "error" in result else 0
