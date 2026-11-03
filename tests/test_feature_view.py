"""REVIEW-VIEW.html rendering and the review-request table that gate, view and Confluence share."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server" / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from test_feature_tools import ActiveProjectTestCase  # noqa: E402

from agent_platform_mcp.tools import feature_view  # noqa: E402

PRD = """---
agent: planner
feature: demo
status: draft
created: 2026-10-27
updated: 2026-10-27
---

# PRD: 데모

## 🔶 검토 요청 (사람이 결정할 것)

| # | 항목 | 제안 | 결정 |
|---|---|---|---|
| A-1 | 부분 취소 허용 여부 | 불허 | [ ] 승인 |
| Q-1 | 지연 시 상태 | PENDING | [x] 동의 |

## 1. 개요
- **한 줄 요약**: 결제 취소

## 2. 범위
### In-Scope
- POST 취소

## 3. API 요약
| 메서드 | 경로 | 목적 |
|---|---|---|
| POST | `/v1/payments/{id}/cancel` | 취소 |

## 4. 도메인 모델
### 상태 전이 (State Machine)
```
PAID --> CANCELED
```

## 6. 처리 흐름 (Flow)
### 6.0 흐름-규칙 연결
| 노드 | BR |
|---|---|
| 검증 | BR-1 |
"""


class ReviewRequestTableTest(unittest.TestCase):
    def test_rows_and_unresolved(self) -> None:
        rows = feature_view.review_request_rows(PRD)
        self.assertEqual([r["id"] for r in rows], ["A-1", "Q-1"])
        self.assertEqual(feature_view.review_request_unresolved(PRD), ["A-1"])

    def test_review_table_with_two_checkboxes_resolved_by_one_mark(self) -> None:
        text = "## 검토 요청\n| # | 항목 | 결정 |\n|---|---|---|\n| R-1 | 인계 | [x] 승인 / [ ] 반려 |\n"
        self.assertEqual(feature_view.review_request_unresolved(text), [])

    def test_rows_without_checkbox_are_not_decisions(self) -> None:
        text = "## 검토 요청\n| # | 항목 | 결정 |\n|---|---|---|\n| - | 없음 | 해당 없음 |\n"
        self.assertEqual(feature_view.review_request_rows(text), [])

    def test_missing_section(self) -> None:
        self.assertEqual(feature_view.review_request_unresolved("# PRD\n\n## 1. 개요\n"), [])


class DrawioToMermaidTest(unittest.TestCase):
    def test_template_converts_to_flowchart_with_decisions_and_edge_labels(self) -> None:
        xml = (ROOT / "templates" / "FLOW.drawio").read_text(encoding="utf-8")
        graphs = feature_view.drawio_to_mermaid(xml)
        self.assertEqual(len(graphs), 1)
        graph = graphs[0]
        self.assertTrue(graph.startswith("flowchart TD"))
        self.assertIn("{", graph)  # rhombus → decision
        self.assertIn('-->|"아니오"|', graph)


BRANCH_GRAPH = {
    "compressed": False,
    "nodes": [
        {"id": "n0", "label": "시작", "kind": "step"},
        {"id": "n1", "label": "통과?\nBR-1", "kind": "decision"},
        {"id": "n2", "label": "ACTIVE", "kind": "step"},
        {"id": "n3", "label": "저장", "kind": "step"},  # join of both legs
        {"id": "n4", "label": "완료", "kind": "terminal"},
        {"id": "n5", "label": "INVALID", "kind": "step"},
    ],
    "edges": [
        {"source": "n0", "target": "n1", "label": ""},
        {"source": "n1", "target": "n2", "label": "예"},
        {"source": "n1", "target": "n5", "label": "아니오"},
        {"source": "n2", "target": "n3", "label": ""},
        {"source": "n5", "target": "n3", "label": ""},
        {"source": "n3", "target": "n4", "label": ""},
    ],
}


class StepListTest(unittest.TestCase):
    def test_drawio_graph_keeps_kinds_and_edge_labels(self) -> None:
        xml = (ROOT / "templates" / "FLOW.drawio").read_text(encoding="utf-8")
        graph = feature_view.drawio_to_graph(xml)[0]
        self.assertFalse(graph["compressed"])
        self.assertIn("decision", {n["kind"] for n in graph["nodes"]})
        self.assertIn("아니오", {e["label"] for e in graph["edges"]})
        self.assertEqual(feature_view.graph_to_mermaid(graph), feature_view.drawio_to_mermaid(xml)[0])

    def test_join_is_listed_after_both_legs(self) -> None:
        # 시작, 통과?, ACTIVE, INVALID, 저장, 완료 — not ACTIVE → 저장 → 완료 → INVALID
        self.assertEqual(feature_view._step_order(BRANCH_GRAPH), ["n0", "n1", "n2", "n5", "n3", "n4"])

    def test_steps_html_links_branches_and_spells_out_rules(self) -> None:
        defs = {"BR-1": {"prefix": "업무 규칙", "text": "통과 판정은 만료·폐기·신뢰 검사를 모두 지난 경우다"}}
        page = feature_view.steps_html(BRANCH_GRAPH, defs)
        self.assertIn('class="step step-decision"', page)
        self.assertIn('<b>예</b> → <a href="#step-3">3. ACTIVE</a>', page)
        self.assertIn('<b>아니오</b> → <a href="#step-4">4. INVALID</a>', page)
        # the bare code line is replaced by the rule's full text, linked to its definition row
        self.assertNotIn('<div class="step-sub">BR-1</div>', page)
        self.assertIn('<a href="#code-BR-1"><b>업무 규칙 BR-1</b></a> — 통과 판정은', page)
        # linear next step is implied, a jump to a non-adjacent step is linked
        self.assertNotIn('href="#step-2"', page)
        self.assertIn('<a href="#step-5">5. 저장</a>', page)

    def test_code_definitions_and_links(self) -> None:
        md = "## 5. 비즈니스 규칙\n| ID | 규칙 |\n|---|---|\n| BR-1 | 한 곳에서만 발행 |\n\n## 12. 수락 기준\n| ID | 조건 | 검증 방법 |\n|---|---|---|\n| AC-2 | 만료면 INVALID | Integration |\n"
        defs = feature_view.code_definitions([md])
        self.assertEqual(defs["BR-1"], {"prefix": "업무 규칙", "text": "한 곳에서만 발행"})
        self.assertEqual(defs["AC-2"]["text"], "조건: 만료면 INVALID · 검증 방법: Integration")
        decisions = "# DECISIONS\n\n## D-8. 발행은 요청 밖에서 한다\n워커가 순서대로 보낸다.\n두 번째 줄.\n\n## D-9: 다른 결정\n"
        ddefs = feature_view.code_definitions([decisions])
        self.assertEqual(ddefs["D-8"], {"prefix": "결정", "text": "발행은 요청 밖에서 한다 — 워커가 순서대로 보낸다. 두 번째 줄."})
        self.assertEqual(ddefs["D-9"]["text"], "다른 결정")
        linked = feature_view.link_codes("see BR-1 and AC-9", defs)
        self.assertIn('<a class="code-ref" href="#code-BR-1" title="업무 규칙 BR-1: 한 곳에서만 발행">BR-1</a>', linked)
        self.assertIn('<span class="code-ref" title="수락 기준">AC-9</span>', linked)


class CodeRangeTest(unittest.TestCase):
    def test_ranges_expand_and_order_is_kept(self) -> None:
        from agent_platform_mcp import flow_svg

        self.assertEqual(flow_svg.codes_in("예외 → Failed · BR-5~BR-8"), ["BR-5", "BR-6", "BR-7", "BR-8"])
        self.assertEqual(flow_svg.codes_in("완료 AC-1 ~ AC-3, BR-9"), ["AC-1", "AC-2", "AC-3", "BR-9"])
        self.assertEqual(flow_svg.codes_in("BR-2, BR-3"), ["BR-2", "BR-3"])


class FlowSvgTest(unittest.TestCase):
    def test_template_renders_shapes_edges_and_labels(self) -> None:
        from agent_platform_mcp import flow_svg

        xml = (ROOT / "templates" / "FLOW.drawio").read_text(encoding="utf-8")
        page = flow_svg.parse_drawio(xml)[0]
        svg, size = flow_svg.render_svg(page)
        self.assertGreater(size["width"], 0)
        self.assertIn('class="node kind-decision"', svg)
        self.assertIn("<polygon", svg)  # rhombus
        self.assertIn('class="edge"', svg)
        self.assertIn(">아니오</text>", svg)
        self.assertIn("<title>", svg)
        legend = flow_svg.legend_html(page)
        self.assertIn("분기", legend)
        self.assertIn("건너뜀 · 실패", legend)

    def test_change_marks_from_style_and_label(self) -> None:
        from agent_platform_mcp import flow_svg

        xml = (ROOT / "templates" / "FLOW.drawio").read_text(encoding="utf-8")
        xml = xml.replace('id="process" value="처리 수행', 'id="process" value="처리 수행 (변경)', 1)
        head = 'id="validate" value="입력·권한 유효?&#10;BR-&lt;n&gt;" style="rhombus;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;'
        self.assertIn(head, xml)
        xml = xml.replace(head, head + "change=new;", 1)
        page = flow_svg.parse_drawio(xml)[0]
        by_id = {n["id"]: n for n in page["nodes"]}
        self.assertEqual(by_id["process"]["change"], "modified")  # label marker fallback
        self.assertEqual(by_id["validate"]["change"], "new")  # style key
        self.assertIsNone(by_id["start"]["change"])
        self.assertEqual(flow_svg.change_counts(page), {"new": 1, "modified": 1})
        svg, _ = flow_svg.render_svg(page)
        self.assertIn('data-id="validate" data-change="new"', svg)
        self.assertIn('class="badge">신규</text>', svg)
        self.assertIn('class="badge">변경</text>', svg)
        self.assertIn("이번 작업에서 신규 (1)", flow_svg.legend_html(page))
        steps = feature_view.steps_html(page)
        self.assertIn('<span class="pill change-new">이번 작업: 신규</span>', steps)

    def test_compressed_page_notice(self) -> None:
        self.assertIn("압축", feature_view.steps_html({"compressed": True, "nodes": [], "edges": []}))


class RenderViewTest(ActiveProjectTestCase):
    def _write_feature(self) -> Path:
        fdir = self.resolved_target / "docs" / "features" / "demo"
        fdir.mkdir(parents=True, exist_ok=True)
        (fdir / "PRD.md").write_text(PRD, encoding="utf-8")
        (fdir / "API-SPEC.md").write_text("---\nagent: planner\nfeature: demo\nstatus: draft\ncreated: 2026-10-27\nupdated: 2026-10-27\n---\n# API-SPEC\n\n## Endpoint 1\n| a |\n|---|\n| b |\n", encoding="utf-8")
        (fdir / "TASK.md").write_text("---\nagent: planner\nfeature: demo\nstatus: draft\ncreated: 2026-10-27\nupdated: 2026-10-27\n---\n# TASK\n", encoding="utf-8")
        self.write_drawio("demo")
        (self.resolved_target / ".git").mkdir(exist_ok=True)
        return fdir

    def test_renders_layout_b_and_ignores_output_in_git(self) -> None:
        fdir = self._write_feature()
        result = feature_view.render_view("demo")
        self.assertNotIn("error", result)
        page = (fdir / "REVIEW-VIEW.html").read_text(encoding="utf-8")
        # review requests first, with the pending count in the bar
        self.assertIn("결정 대기 1", page)
        self.assertLess(page.index("검토 요청"), page.index("서비스 흐름"))
        self.assertIn("부분 취소 허용 여부", page)
        # flow from FLOW.drawio as inline SVG (no CDN) with a step list; API table from PRD §3, state machine, link table
        self.assertIn('<svg xmlns="http://www.w3.org/2000/svg" class="flow-svg"', page)
        self.assertIn('<ol class="steps">', page)
        self.assertNotIn("<script src=", page)
        # review-request ids are anchors (not links to themselves); BR/AC columns are spelled out
        self.assertIn('<td id="code-A-1" class="code-cell"><b>A-1</b>', page)
        self.assertIn("<th>업무 규칙 (BR)</th>", page)
        self.assertIn("/v1/payments/{id}/cancel", page)
        self.assertIn("PAID --&gt; CANCELED", page)
        self.assertIn("BR-1", page)
        # full docs folded, other docs linked
        self.assertIn("<summary>PRD 전체</summary>", page)
        self.assertIn('href="TASK.md"', page)
        self.assertEqual(result["review_requests"], {"total": 2, "pending": 1})
        self.assertEqual(result["gitignore"], "added")
        self.assertIn(feature_view.GITIGNORE_PATTERN, (self.resolved_target / ".gitignore").read_text(encoding="utf-8"))
        # second run: pattern already there, nothing duplicated
        self.assertEqual(feature_view.render_view("demo")["gitignore"], "present")
        self.assertEqual((self.resolved_target / ".gitignore").read_text(encoding="utf-8").count(feature_view.GITIGNORE_PATTERN), 1)

    def test_missing_flow_falls_back_to_prd_mermaid_or_notice(self) -> None:
        fdir = self._write_feature()
        (fdir / "FLOW.drawio").unlink()
        result = feature_view.render_view("demo", gitignore=False)
        page = (fdir / "REVIEW-VIEW.html").read_text(encoding="utf-8")
        self.assertEqual(result["flow"], "FLOW.drawio 없음")
        self.assertIn("FLOW.drawio 가 없고", page)
        self.assertEqual(result["gitignore"], "not requested")

    def test_missing_prd_is_an_error(self) -> None:
        fdir = self.resolved_target / "docs" / "features" / "empty"
        fdir.mkdir(parents=True)
        self.assertIn("error", feature_view.render_view("empty"))


if __name__ == "__main__":
    unittest.main()
