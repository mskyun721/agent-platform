"""Notion block rendering of the shared Markdown parser output (no network)."""

from agent_platform_mcp import markdown_blocks, notion_blocks
from agent_platform_mcp.notion_blocks import MAX_CHILDREN, MAX_TEXT, render_notion, rich_text, split_block


def render(md: str) -> list[dict]:
    return render_notion(markdown_blocks.parse(md))


def plain(rich: list[dict]) -> str:
    return "".join(item["text"]["content"] for item in rich)


def test_headings_map_to_three_levels():
    blocks = render("# A\n## B\n### C\n#### D")
    assert [b["type"] for b in blocks] == ["heading_1", "heading_2", "heading_3", "heading_3"]
    assert plain(blocks[3]["heading_3"]["rich_text"]) == "D"


def test_paragraph_lines_join_with_newline_and_frontmatter_is_dropped():
    blocks = render("---\nagent: x\n---\nline one\nline two")
    assert len(blocks) == 1 and blocks[0]["type"] == "paragraph"
    assert plain(blocks[0]["paragraph"]["rich_text"]) == "line one\nline two"


def test_lists_and_tasks():
    blocks = render("- a\n- b\n\n1. one\n\n- [ ] todo\n- [x] done")
    kinds = [b["type"] for b in blocks]
    assert kinds == ["bulleted_list_item", "bulleted_list_item", "numbered_list_item", "to_do", "to_do"]
    assert blocks[3]["to_do"]["checked"] is False
    assert blocks[4]["to_do"]["checked"] is True


def test_code_language_mapping_keeps_mermaid_and_defaults_to_plain_text():
    blocks = render("```mermaid\nflowchart TD\n```\n```kt\nval x = 1\n```\n```weird\nx\n```\n```\ny\n```")
    langs = [b["code"]["language"] for b in blocks]
    assert langs == ["mermaid", "kotlin", "plain text", "plain text"]
    assert plain(blocks[0]["code"]["rich_text"]) == "flowchart TD"


def test_table_uses_header_width_and_pads_or_truncates_rows():
    blocks = render("| a | b |\n|---|---|\n| 1 |\n| 1 | 2 | 3 |")
    table = blocks[0]["table"]
    assert blocks[0]["type"] == "table"
    assert table["table_width"] == 2 and table["has_column_header"] is True
    rows = [r["table_row"]["cells"] for r in table["children"]]
    assert len(rows) == 3
    assert all(len(cells) == 2 for cells in rows)
    assert [plain(c) for c in rows[1]] == ["1", ""]
    assert [plain(c) for c in rows[2]] == ["1", "2"]


def test_header_only_table_has_one_row():
    table = render("| a |\n|---|")[0]["table"]
    assert table["table_width"] == 1 and len(table["children"]) == 1


def test_table_syntax_inside_code_block_stays_code():
    blocks = render("```\n| a | b |\n|---|---|\n```")
    assert [b["type"] for b in blocks] == ["code"]


def test_quote_and_divider():
    blocks = render("> one\n> two\n\n---")
    assert blocks[0]["type"] == "quote"
    assert plain(blocks[0]["quote"]["rich_text"]) == "one\ntwo"
    assert blocks[1]["type"] == "divider"


def test_inline_annotations_and_links():
    rich = rich_text("a **b** *c* `d_e` [site](https://x.dev) [rel](./PRD.md) ![img](a.png) snake_case")
    by_text = {item["text"]["content"]: item for item in rich}
    assert by_text["b"]["annotations"] == {"bold": True}
    assert by_text["c"]["annotations"] == {"italic": True}
    assert by_text["d_e"]["annotations"] == {"code": True}
    assert by_text["site"]["text"]["link"] == {"url": "https://x.dev"}
    assert "link" not in by_text["rel"]["text"]  # relative link keeps only its label
    assert "![img](a.png)" in by_text  # images are not uploaded (Q-4)
    assert "snake_case" in plain(rich)


def test_rich_text_splits_at_2000_chars():
    assert len(notion_blocks.text_items("x" * MAX_TEXT)) == 1
    items = notion_blocks.text_items("x" * (MAX_TEXT + 1))
    assert [len(i["text"]["content"]) for i in items] == [MAX_TEXT, 1]


def test_long_code_splits_into_blocks_of_at_most_100_rich_items():
    body = "y" * (MAX_TEXT * 101)
    blocks = render(f"```\n{body}\n```")
    assert [len(b["code"]["rich_text"]) for b in blocks] == [100, 1]
    assert sum(len(plain(b["code"]["rich_text"])) for b in blocks) == len(body)


def test_split_block_defers_table_rows_beyond_100():
    def table(n_rows: int) -> dict:
        md = "| h |\n|---|\n" + "".join(f"| {i} |\n" for i in range(n_rows))
        return render(md)[0]

    exactly = table(MAX_CHILDREN - 1)  # header + 99 = 100 rows
    assert split_block(exactly) == (exactly, [])
    over = table(MAX_CHILDREN)  # header + 100 = 101 rows
    sent, rest = split_block(over)
    assert len(sent["table"]["children"]) == MAX_CHILDREN and len(rest) == 1
    assert len(over["table"]["children"]) == MAX_CHILDREN + 1  # input not mutated


def test_split_block_defers_all_children_when_a_child_is_nested():
    inner = notion_blocks.block("bulleted_list_item", rich_text=[], children=[notion_blocks.block("divider")])
    outer = notion_blocks.block("toggle", rich_text=[], children=[inner])
    sent, rest = split_block(outer)
    assert "children" not in sent["toggle"] and rest == [inner]


def test_chunks_of_100():
    assert [len(c) for c in notion_blocks.chunks(list(range(100)))] == [100]
    assert [len(c) for c in notion_blocks.chunks(list(range(101)))] == [100, 1]
