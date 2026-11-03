"""Block-level Markdown parser shared by the Confluence converter and the local review view."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server" / "src"))

from agent_platform_mcp import markdown_blocks as mb  # noqa: E402


class TestParse(unittest.TestCase):
    def test_table_block(self) -> None:
        md = "| # | 항목 | 결정 |\n|---|---|---|\n| A-1 | 부분 취소 | [ ] 승인 |\n| Q-1 | 지연 | [x] 동의 |\n"
        blocks = mb.parse(md)
        self.assertEqual(len(blocks), 1)
        table = blocks[0]
        self.assertEqual(table["type"], "table")
        self.assertEqual(table["header"], ["#", "항목", "결정"])
        self.assertEqual(table["rows"], [["A-1", "부분 취소", "[ ] 승인"], ["Q-1", "지연", "[x] 동의"]])

    def test_table_cell_with_escaped_pipe(self) -> None:
        blocks = mb.parse("| a | b |\n|---|---|\n| x \\| y | z |\n")
        self.assertEqual(blocks[0]["rows"], [["x | y", "z"]])

    def test_task_list(self) -> None:
        blocks = mb.parse("- [ ] open item\n- [x] done item\n")
        self.assertEqual(blocks[0]["type"], "tasks")
        self.assertEqual(blocks[0]["items"], [(False, "open item"), (True, "done item")])

    def test_blockquote(self) -> None:
        blocks = mb.parse("> first\n> second\n")
        self.assertEqual(blocks[0], {"type": "quote", "lines": ["first", "second"]})

    def test_fenced_code_keeps_pipes_and_hashes(self) -> None:
        blocks = mb.parse("```mermaid\nflowchart TD\n  a --> b\n```\n")
        self.assertEqual(blocks[0], {"type": "code", "lang": "mermaid", "body": "flowchart TD\n  a --> b"})

    def test_frontmatter_stripped_and_sections(self) -> None:
        md = "---\nstatus: draft\n---\n# T\n\n## 1. 개요\ntext\n\n## 2. 범위\n- a\n"
        blocks = mb.parse(md)
        self.assertEqual(blocks[0], {"type": "heading", "level": 1, "text": "T"})
        sections = mb.sections(blocks)
        self.assertEqual([s["title"] for s in sections], ["T", "1. 개요", "2. 범위"])
        self.assertEqual(sections[1]["blocks"][0]["type"], "para")

    def test_section_lookup_by_keyword(self) -> None:
        blocks = mb.parse("## 검토 요청 (사람이 결정할 것)\n| a |\n|---|\n| b |\n\n## 1. 개요\nx\n")
        found = mb.find_section(blocks, "검토 요청")
        self.assertIsNotNone(found)
        self.assertEqual(found["blocks"][0]["type"], "table")
        self.assertIsNone(mb.find_section(blocks, "없는 제목"))


class TestRenderHtml(unittest.TestCase):
    def test_table_tasks_quote_code(self) -> None:
        md = "| a | b |\n|---|---|\n| 1 | **2** |\n\n- [x] done\n\n> note\n\n```kotlin\nval x = 1 < 2\n```\n"
        html = mb.render_html(mb.parse(md))
        self.assertIn("<table>", html)
        self.assertIn("<th>a</th>", html)
        self.assertIn("<td><strong>2</strong></td>", html)
        self.assertIn('<input type="checkbox" disabled checked>', html)
        self.assertIn("<blockquote><p>note</p></blockquote>", html)
        self.assertIn('<pre><code class="language-kotlin">val x = 1 &lt; 2</code></pre>', html)

    def test_mermaid_code_becomes_mermaid_pre(self) -> None:
        html = mb.render_html(mb.parse("```mermaid\nflowchart TD\n  a --> b\n```\n"))
        self.assertIn('<pre class="mermaid">flowchart TD\n  a --&gt; b</pre>', html)

    def test_headings_and_lists(self) -> None:
        html = mb.render_html(mb.parse("## H\n\n- one\n- two\n\n1. first\n"))
        self.assertIn("<h2>H</h2>", html)
        self.assertEqual(html.count("<li>"), 3)
        self.assertIn("<ol>", html)


if __name__ == "__main__":
    unittest.main()
