"""FLOW.drawio → graph model (with the drawing's own geometry) → self-contained inline SVG.

No draw.io CLI, no CDN: the planner's `.drawio` already carries node positions, sizes, shapes
and colours (drawio-skill palette), so the review page draws the same boxes and orthogonal
arrows itself. Modelled on the target project's `all-api-service-flows/index.html` viewer
(user reference 2026-10-27): colour-coded node kinds with a legend, zoom buttons, a scrollable
chart and clickable nodes.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from typing import Any

# drawio-skill palette → node kind. Shape wins over fill (rhombus is always a decision).
KIND_BY_FILL = {
    "#dae8fc": "step",
    "#fff2cc": "decision",
    "#f8cecc": "error",
    "#d5e8d4": "done",
    "#ffe6cc": "warn",
    "#e1d5e7": "external",
    "#f5f5f5": "return",
}
KIND_LABEL = {
    "step": "처리",
    "decision": "분기",
    "external": "외부 호출 · 비동기",
    "db": "DB",
    "error": "건너뜀 · 실패",
    "warn": "주의 결과",
    "done": "정상 완료",
    "return": "반환",
    "terminal": "시작 · 종료",
}
KIND_COLORS = {
    "step": ("#dae8fc", "#6c8ebf"),
    "decision": ("#fff2cc", "#d6b656"),
    "external": ("#e1d5e7", "#9673a6"),
    "db": ("#e1d5e7", "#9673a6"),
    "error": ("#f8cecc", "#b85450"),
    "warn": ("#ffe6cc", "#d79b00"),
    "done": ("#d5e8d4", "#82b366"),
    "return": ("#f5f5f5", "#666666"),
    "terminal": ("#f5f5f5", "#666666"),
}

# Rule / criterion codes the planner writes into node labels (PRD §5 BR-n, §12 AC-n, DECISIONS D-n …).
CODE_RE = re.compile(r"\b(BR|AC|NFR|D|Q|A|R)-(\d+)\b")
CODE_PREFIX = {
    "BR": "업무 규칙",
    "AC": "수락 기준",
    "NFR": "비기능 요구",
    "D": "결정",
    "Q": "질문",
    "A": "승인 요청",
    "R": "리뷰 결정",
}
# A label line that is nothing but codes and separators ("AC-2, AC-6, BR-9", "AC-1 ~ AC-4").
_CODES_LINE_RE = re.compile(r"^(?:(?:BR|AC|NFR|D|Q|A|R)-\d+|[,·~/\s]|\(|\))+$")


def _clean_label(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"[ \t]+", " ", html.unescape(text)).strip()


def _style_map(style: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in style.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
        elif part.strip():
            out[part.strip()] = "1"
    return out


def _kind(style: dict[str, str]) -> str:
    if "rhombus" in style:
        return "decision"
    if style.get("shape") in ("cylinder", "cylinder3", "datastore"):
        return "db"
    if "ellipse" in style or style.get("shape") == "cloud":
        return "terminal"
    return KIND_BY_FILL.get(style.get("fillColor", "").lower(), "step")


_RANGE_RE = re.compile(r"\b(BR|AC|NFR|D|Q|A|R)-(\d+)\s*[~–]\s*(?:\1-)?(\d+)\b")


# What this feature changes in the flow. Planners set `change=new|modified|removed` in the cell
# style (draw.io keeps unknown style keys); label markers are the fallback for hand-drawn files.
CHANGE_LABEL = {"new": "신규", "modified": "변경", "removed": "제거", "existing": "기존"}
_CHANGE_MARKERS = {
    "new": ("(신규)", "[신규]", "(추가)", "[추가]", "(NEW)", "[NEW]"),
    "modified": ("(변경)", "[변경]", "(수정)", "[수정]"),
    "removed": ("(제거)", "[제거]", "(삭제)", "[삭제]"),
    "existing": ("(기존)", "[기존]"),
}


def change_of(style: dict[str, str], label: str = "") -> str | None:
    value = style.get("change", "").lower()
    if value in CHANGE_LABEL:
        return value
    for change, markers in _CHANGE_MARKERS.items():
        if any(m in label for m in markers):
            return change
    return None


def codes_in(text: str) -> list[str]:
    """Codes mentioned in a label, in order; "BR-5~BR-8" / "AC-1 ~ AC-4" ranges are expanded."""
    seen: list[str] = []

    def add(code: str) -> None:
        if code not in seen:
            seen.append(code)

    pos = 0
    for m in _RANGE_RE.finditer(text):
        for single in CODE_RE.finditer(text, pos, m.start()):
            add(f"{single.group(1)}-{single.group(2)}")
        lo, hi = int(m.group(2)), int(m.group(3))
        for n in range(lo, hi + 1) if lo <= hi else (lo,):
            add(f"{m.group(1)}-{n}")
        pos = m.end()
    for single in CODE_RE.finditer(text, pos):
        add(f"{single.group(1)}-{single.group(2)}")
    return seen


def parse_drawio(xml_text: str) -> list[dict[str, Any]]:
    """One page per <diagram>: {name, compressed, nodes, edges}. Nodes carry absolute geometry
    (container offsets applied), kind, fill/stroke. Containers and edge-label cells are dropped."""
    root = ET.fromstring(xml_text)
    pages = root.findall("diagram") or [root]
    out: list[dict[str, Any]] = []
    for index, page in enumerate(pages):
        name = page.get("name") or f"Page {index + 1}"
        model = page.find("mxGraphModel")
        cells_root = model.find("root") if model is not None else None
        if cells_root is None:
            out.append({"name": name, "compressed": True, "nodes": [], "edges": []})
            continue
        cells: list[tuple[ET.Element, str, str]] = []
        for child in cells_root:
            if child.tag == "mxCell":
                cells.append((child, child.get("id", ""), _clean_label(child.get("value"))))
            elif child.tag in ("UserObject", "object"):
                inner = child.find("mxCell")
                if inner is not None:
                    cells.append((inner, child.get("id", ""), _clean_label(child.get("label") or child.get("value"))))
        label = {cid: lbl for _, cid, lbl in cells}
        style = {cid: _style_map(c.get("style") or "") for c, cid, _ in cells}
        parent = {cid: c.get("parent") for c, cid, _ in cells}
        geom: dict[str, tuple[float, float, float, float]] = {}
        for c, cid, _ in cells:
            g = c.find("mxGeometry")
            if c.get("vertex") == "1" and g is not None:
                geom[cid] = (float(g.get("x") or 0), float(g.get("y") or 0), float(g.get("width") or 0), float(g.get("height") or 0))
        parents = {p for p in parent.values() if p}
        containers = {cid for cid in geom if cid in parents}
        leaves = [cid for c, cid, _ in cells if c.get("vertex") == "1" and cid in geom and cid not in containers and "edgeLabel" not in style[cid]]

        def absolute(cid: str) -> tuple[float, float]:
            x, y = geom[cid][0], geom[cid][1]
            p = parent.get(cid)
            while p and p in geom:
                x += geom[p][0]
                y += geom[p][1]
                p = parent.get(p)
            return x, y

        nodes = []
        for cid in leaves:
            x, y = absolute(cid)
            _, _, w, h = geom[cid]
            st = style[cid]
            kind = _kind(st)
            fill, stroke = KIND_COLORS[kind]
            nodes.append({
                "id": cid, "label": label.get(cid) or cid, "kind": kind,
                "x": x, "y": y, "w": w, "h": h,
                "fill": st.get("fillColor", fill), "stroke": st.get("strokeColor", stroke),
                "codes": codes_in(label.get(cid) or ""),
                "change": change_of(st, label.get(cid) or ""),
            })
        ids = {n["id"] for n in nodes}
        edges = []
        for c, cid, _ in cells:
            if c.get("edge") != "1":
                continue
            s, t = c.get("source"), c.get("target")
            if s in ids and t in ids:
                edges.append({
                    "id": cid, "source": s, "target": t, "label": _clean_label(c.get("value")),
                    "dashed": style[cid].get("dashed") == "1", "change": change_of(style[cid]),
                })
        out.append({"name": name, "compressed": False, "nodes": nodes, "edges": edges})
    return out


# ---------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------

def _text_width(text: str, font: float) -> float:
    width = 0.0
    for ch in text:
        o = ord(ch)
        if o >= 0x2E80:  # CJK / Hangul: full width
            width += font * 1.0
        elif ch.isupper() or ch in "@#%&mw":
            width += font * 0.68
        elif ch in "iljtf.,:;'|!I ":
            width += font * 0.32
        else:
            width += font * 0.55
    return width


def _wrap(text: str, max_width: float, font: float) -> list[str]:
    lines: list[str] = []
    for raw in text.split("\n"):
        words = raw.split(" ")
        cur = ""
        for word in words:
            cand = word if not cur else f"{cur} {word}"
            if _text_width(cand, font) <= max_width or not cur:
                cur = cand
                # a single word longer than the box: hard-break it
                while _text_width(cur, font) > max_width and len(cur) > 1:
                    cut = len(cur)
                    while cut > 1 and _text_width(cur[:cut], font) > max_width:
                        cut -= 1
                    lines.append(cur[:cut])
                    cur = cur[cut:]
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def _fit_lines(label: str, w: float, h: float) -> tuple[list[tuple[str, bool]], float]:
    """Wrap the label into the box, shrinking the font until it fits. Lines made only of
    rule codes are flagged so they can be drawn smaller/muted."""
    for font in (12.5, 11.5, 10.5, 9.5):
        lines = _wrap(label, w - 18, font)
        if len(lines) * (font + 3) <= h - 6 or font == 9.5:
            flagged = [(ln, bool(_CODES_LINE_RE.match(ln)) and bool(CODE_RE.search(ln))) for ln in lines]
            return flagged, font
    return [(label, False)], 9.5


def _shape(n: dict[str, Any]) -> str:
    x, y, w, h = n["x"], n["y"], n["w"], n["h"]
    fill, stroke = n["fill"], n["stroke"]
    if n["kind"] == "decision":
        pts = f"{x + w / 2},{y} {x + w},{y + h / 2} {x + w / 2},{y + h} {x},{y + h / 2}"
        return f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}"/>'
    if n["kind"] == "db":
        ry = min(10.0, h / 6)
        return (
            f'<path d="M{x},{y + ry} a{w / 2},{ry} 0 0 1 {w},0 v{h - 2 * ry} a{w / 2},{ry} 0 0 1 -{w},0 z" fill="{fill}" stroke="{stroke}"/>'
            f'<ellipse cx="{x + w / 2}" cy="{y + ry}" rx="{w / 2}" ry="{ry}" fill="{fill}" stroke="{stroke}"/>'
        )
    rx = h / 2 if n["kind"] == "terminal" else 8
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}"/>'


def _route(s: dict[str, Any], t: dict[str, Any]) -> list[tuple[float, float]]:
    """Orthogonal polyline from s to t: below → out of the bottom into the top; beside → out of
    the side; above/overlapping → around the right."""
    scx, scy = s["x"] + s["w"] / 2, s["y"] + s["h"] / 2
    tcx, tcy = t["x"] + t["w"] / 2, t["y"] + t["h"] / 2
    if t["y"] >= s["y"] + s["h"] - 1:
        x1, y1, x2, y2 = scx, s["y"] + s["h"], tcx, t["y"]
        if abs(x1 - x2) < 2:
            return [(x1, y1), (x2, y2)]
        my = (y1 + y2) / 2
        return [(x1, y1), (x1, my), (x2, my), (x2, y2)]
    if t["x"] >= s["x"] + s["w"] - 1:
        x1, y1, x2, y2 = s["x"] + s["w"], scy, t["x"], tcy
        if abs(y1 - y2) < 2:
            return [(x1, y1), (x2, y2)]
        mx = (x1 + x2) / 2
        return [(x1, y1), (mx, y1), (mx, y2), (x2, y2)]
    if t["x"] + t["w"] <= s["x"] + 1:
        x1, y1, x2, y2 = s["x"], scy, t["x"] + t["w"], tcy
        if abs(y1 - y2) < 2:
            return [(x1, y1), (x2, y2)]
        mx = (x1 + x2) / 2
        return [(x1, y1), (mx, y1), (mx, y2), (x2, y2)]
    xo = max(s["x"] + s["w"], t["x"] + t["w"]) + 30
    return [(s["x"] + s["w"], scy), (xo, scy), (xo, tcy), (t["x"] + t["w"], tcy)]


def render_svg(page: dict[str, Any], *, margin: float = 24.0) -> tuple[str, dict[str, float]]:
    """Inline SVG for one page plus its natural size. Nodes are `<g class="node" data-id>` so
    the page script can attach click handlers; every node has a <title> tooltip."""
    nodes = page["nodes"]
    if not nodes:
        return "", {"width": 0, "height": 0}
    by_id = {n["id"]: n for n in nodes}
    minx = min(n["x"] for n in nodes) - margin
    miny = min(n["y"] for n in nodes) - margin
    maxx = max(n["x"] + n["w"] for n in nodes) + margin + 60  # room for labels on side branches
    maxy = max(n["y"] + n["h"] for n in nodes) + margin
    width, height = maxx - minx, maxy - miny

    parts = [
        '<defs><marker id="fv-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M0,0 L10,5 L0,10 z" fill="#5b6b82"/></marker>'
        '<marker id="fv-arrow-new" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M0,0 L10,5 L0,10 z" fill="#2563eb"/></marker></defs>',
        f'<g transform="translate({-minx},{-miny})">',
    ]
    for e in page["edges"]:
        s, t = by_id.get(e["source"]), by_id.get(e["target"])
        if not s or not t:
            continue
        pts = _route(s, t)
        d = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        dash = ' stroke-dasharray="6 4"' if e["dashed"] else ""
        change = e.get("change")
        chg_attr = f' data-change="{change}"' if change else ""
        stroke, sw, marker = ("#2563eb", "2.2", "fv-arrow-new") if change in ("new", "modified") else ("#5b6b82", "1.4", "fv-arrow")
        parts.append(f'<polyline class="edge" data-from="{html.escape(s["id"])}" data-to="{html.escape(t["id"])}"{chg_attr} points="{d}" fill="none" stroke="{stroke}" stroke-width="{sw}"{dash} marker-end="url(#{marker})"/>')
        if e["label"]:
            font = 11.0
            tw = _text_width(e["label"], font) + 10
            (x1, y1), (x2, y2) = pts[0], pts[1]
            if abs(x1 - x2) < 2 and len(pts) == 4:
                # bottom exit that bends sideways: two branches leave the same point, so put
                # each label on its own horizontal segment instead of stacking them on the stem
                (x1, y1), (x2, y2) = pts[1], pts[2]
            if abs(x1 - x2) < 2:  # vertical segment: label to the right of the line
                lx, ly, anchor = x1 + 7, (y1 + y2) / 2 + 4, "start"
                bx = lx - 3
            else:  # horizontal segment: label above the middle
                lx, ly, anchor = (x1 + x2) / 2, y1 - 6, "middle"
                bx = lx - tw / 2
            parts.append(f'<rect x="{bx:.1f}" y="{ly - font - 1:.1f}" width="{tw:.1f}" height="{font + 5:.1f}" rx="3" fill="#fff" fill-opacity="0.92"/>')
            parts.append(f'<text class="edge-label" x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" font-size="{font}" fill="#3e4c5e">{html.escape(e["label"])}</text>')
    for n in nodes:
        lines, font = _fit_lines(n["label"], n["w"], n["h"])
        lh = font + 3
        total = len(lines) * lh
        y0 = n["y"] + n["h"] / 2 - total / 2 + font
        cx = n["x"] + n["w"] / 2
        text = []
        for i, (ln, is_codes) in enumerate(lines):
            cls = ' class="codes"' if is_codes else ""
            fs = font - 1.5 if is_codes else font
            text.append(f'<text{cls} x="{cx:.1f}" y="{y0 + i * lh:.1f}" text-anchor="middle" font-size="{fs}">{html.escape(ln)}</text>')
        change = n.get("change")
        badge = ""
        if change in ("new", "modified", "removed"):
            # highlight ring + a small badge at the top-right corner
            bx, by = n["x"] + n["w"] - 4, n["y"] - 9
            color = {"new": "#2563eb", "modified": "#d97706", "removed": "#b91c1c"}[change]
            ring = (
                f'<polygon points="{n["x"] + n["w"] / 2},{n["y"] - 4} {n["x"] + n["w"] + 4},{n["y"] + n["h"] / 2} {n["x"] + n["w"] / 2},{n["y"] + n["h"] + 4} {n["x"] - 4},{n["y"] + n["h"] / 2}"'
                if n["kind"] == "decision"
                else f'<rect x="{n["x"] - 4}" y="{n["y"] - 4}" width="{n["w"] + 8}" height="{n["h"] + 8}" rx="11"'
            ) + f' class="change-ring" fill="none" stroke="{color}" stroke-width="2" stroke-dasharray="5 3"/>'
            label = CHANGE_LABEL[change]
            bw = _text_width(label, 10.5) + 12
            badge = ring + (
                f'<rect x="{bx - bw:.1f}" y="{by:.1f}" width="{bw:.1f}" height="17" rx="8.5" fill="{color}"/>'
                f'<text x="{bx - bw / 2:.1f}" y="{by + 12.5:.1f}" text-anchor="middle" font-size="10.5" font-weight="600" fill="#fff" class="badge">{label}</text>'
            )
        chg_attr = f' data-change="{change}"' if change else ""
        parts.append(
            f'<g class="node kind-{n["kind"]}" data-id="{html.escape(n["id"])}"{chg_attr} tabindex="0" role="button">'
            f'<title>{html.escape(n["label"])}</title>{_shape(n)}{"".join(text)}{badge}</g>'
        )
    parts.append("</g>")
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" class="flow-svg" role="img" aria-label="{html.escape(page["name"])}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}" width="{width:.0f}" height="{height:.0f}" data-w="{width:.0f}" data-h="{height:.0f}">'
        + "".join(parts) + "</svg>"
    )
    return svg, {"width": width, "height": height}


def legend_html(page: dict[str, Any]) -> str:
    kinds: list[str] = []
    for n in page["nodes"]:
        if n["kind"] not in kinds:
            kinds.append(n["kind"])
    items = "".join(
        f'<span><i class="dot" style="background:{KIND_COLORS[k][0]};border-color:{KIND_COLORS[k][1]}"></i>{KIND_LABEL[k]}</span>'
        for k in kinds
    )
    dashed = any(e["dashed"] for e in page["edges"])
    if dashed:
        items += '<span><i class="dash"></i>즉시 반환 · 비동기 경계</span>'
    counts = change_counts(page)
    for change, color in (("new", "#2563eb"), ("modified", "#d97706"), ("removed", "#b91c1c")):
        if counts.get(change):
            items += f'<span><i class="dot ring" style="border-color:{color}"></i><b style="color:{color}">{CHANGE_LABEL[change]}</b> 이번 작업에서 {CHANGE_LABEL[change]} ({counts[change]})</span>'
    return f'<div class="legend">{items}</div>'


def change_counts(page: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in list(page["nodes"]) + list(page["edges"]):
        change = item.get("change")
        if change in ("new", "modified", "removed"):
            counts[change] = counts.get(change, 0) + 1
    return counts
