"""Notion client and feature sync against an in-memory fake API (httpx is never real)."""

from __future__ import annotations

import json
import re
import uuid
from contextlib import contextmanager

import httpx
import pytest

from agent_platform_mcp import config
from agent_platform_mcp.tools import notion, projects
from agent_platform_mcp.tools.feature_overview import build_overview_markdown

TOKEN = "ntn_FAKEtoken0123456789abcdefSECRET"
PARENT = "1f2e3d4c-5b6a-7988-1726-354433221100"
PARENT_ID = PARENT.replace("-", "")


class FakeNotion:
    """Routes httpx.request for the endpoints notion.py uses; records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.blocks: dict[str, dict] = {PARENT_ID: {"type": "page", "children": [], "archived": False}}
        self.forced: list[tuple[str, str, httpx.Response]] = []  # (method, path regex, response) once each
        self.page_size = 2

    def force(self, method: str, pattern: str, response: httpx.Response, times: int = 1) -> None:
        self.forced += [(method, pattern, response)] * times

    def pages(self, title: str | None = None) -> list[str]:
        return [i for i, b in self.blocks.items() if b["type"] == "child_page" and not b["archived"]
                and (title is None or b["title"] == title)]

    def _new(self, parent: str, block: dict) -> str:
        block_id = str(uuid.uuid4())
        kind = block["type"]
        payload = dict(block.get(kind, {}))
        children = payload.pop("children", [])
        self.blocks[block_id] = {"type": kind, "payload": payload, "children": [], "archived": False,
                                 "parent": parent, "title": None}
        self.blocks[parent]["children"].append(block_id)
        for child in children:
            self._new(block_id, child)
        return block_id

    def __call__(self, method: str, url: str, **kwargs) -> httpx.Response:
        assert kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}"
        assert kwargs["timeout"] == 30
        path = url.removeprefix(notion.API_BASE)
        self.calls.append((method, path))
        for index, (m, pattern, response) in enumerate(self.forced):
            if m == method and re.fullmatch(pattern, path):
                del self.forced[index]
                if isinstance(response, Exception):
                    raise response
                return response
        body = kwargs.get("json")
        if method == "POST" and path == "/pages":
            parent = body["parent"]["page_id"]
            if parent not in self.blocks:
                return httpx.Response(404, json={"code": "object_not_found"})
            assert len(body["children"]) <= 100
            page_id = str(uuid.uuid4())
            title = body["properties"]["title"]["title"][0]["text"]["content"]
            self.blocks[page_id] = {"type": "child_page", "children": [], "archived": False,
                                    "parent": parent, "title": title}
            self.blocks[parent]["children"].append(page_id)
            for child in body["children"]:
                self._new(page_id, child)
            return httpx.Response(200, json={"id": page_id, "url": f"https://notion.test/{page_id}"})
        match = re.fullmatch(r"/pages/([\w-]+)", path)
        if method == "GET" and match:
            block = self.blocks.get(match.group(1))
            if block is None:
                return httpx.Response(404, json={"code": "object_not_found"})
            return httpx.Response(200, json={"id": match.group(1), "archived": block["archived"],
                                             "url": f"https://notion.test/{match.group(1)}"})
        match = re.fullmatch(r"/blocks/([\w-]+)/children", path)
        if match and match.group(1) not in self.blocks:
            return httpx.Response(404, json={"code": "object_not_found"})
        if method == "GET" and match:
            live = [c for c in self.blocks[match.group(1)]["children"] if not self.blocks[c]["archived"]]
            start = int(kwargs["params"].get("start_cursor") or 0)
            window = live[start:start + self.page_size]
            more = start + self.page_size < len(live)
            results = [{"id": c, "type": self.blocks[c]["type"],
                        **({"child_page": {"title": self.blocks[c]["title"]}} if self.blocks[c]["type"] == "child_page" else {})}
                       for c in window]
            return httpx.Response(200, json={"results": results, "has_more": more,
                                             "next_cursor": str(start + self.page_size) if more else None})
        if method == "PATCH" and match:
            assert len(body["children"]) <= 100
            ids = [self._new(match.group(1), child) for child in body["children"]]
            return httpx.Response(200, json={"results": [{"id": i} for i in ids]})
        match = re.fullmatch(r"/blocks/([\w-]+)", path)
        if method == "DELETE" and match:
            self.blocks[match.group(1)]["archived"] = True
            return httpx.Response(200, json={"id": match.group(1), "archived": True})
        raise AssertionError(f"unexpected call {method} {path}")

    def body_types(self, page_id: str) -> list[str]:
        return [self.blocks[c]["type"] for c in self.blocks[page_id]["children"] if not self.blocks[c]["archived"]]


@pytest.fixture
def project(tmp_path, monkeypatch):
    base = tmp_path / "projects"
    service = base / "svc"
    feature_dir = service / "docs" / "features" / "demo"
    feature_dir.mkdir(parents=True)
    (feature_dir / "PRD.md").write_text(
        "---\nstatus: draft\n---\n# PRD\n\n## 검토 요청\n| # | 항목 |\n|---|---|\n| A-1 | x |\n\n## 1. 개요\n- 요약\n",
        encoding="utf-8")
    (feature_dir / "TASK.md").write_text("# TASK\n- [ ] one\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS", str(base))
    projects.register(str(service), "demo-svc")
    projects.set_publish("demo-svc", "notion", notion_parent_page_id=PARENT)
    return {"root": "demo-svc", "dir": feature_dir, "path": service}


@pytest.fixture
def fake(monkeypatch):
    api = FakeNotion()
    monkeypatch.setattr(notion.httpx, "request", api)
    sleeps: list[float] = []
    monkeypatch.setattr(notion, "_sleep", sleeps.append)
    api.sleeps = sleeps
    return api


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", TOKEN)


def sync(project, **kwargs):
    return notion.sync_feature("demo", kwargs.pop("parent", PARENT), root=project["root"], **kwargs)


# --- configuration -----------------------------------------------------------

def test_missing_token_returns_error_without_any_call(project, fake):
    assert sync(project) == {"error": "Missing env var: NOTION_TOKEN"}
    assert fake.calls == []


def test_token_format_is_checked_without_echoing_the_value(project, fake, monkeypatch, capsys):
    monkeypatch.setenv("NOTION_TOKEN", "bogus SECRETVALUE")
    result = sync(project)
    assert result == {"error": "Invalid NOTION_TOKEN format"}
    assert "SECRETVALUE" not in json.dumps(result) + capsys.readouterr().err
    assert fake.calls == []


def test_notion_config_is_lazy(monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    with pytest.raises(config.ConfigError, match="Missing env var: NOTION_TOKEN"):
        config.notion_config()
    monkeypatch.setenv("NOTION_TOKEN", "secret_abc")
    assert config.notion_config() == {"token": "secret_abc"}


def test_parent_is_validated(project, fake, token):
    assert sync(project, parent="not-an-id") == {"error": "Invalid parent_page_id"}
    assert fake.calls == []


# --- publish target guard (SECURITY M-1, DECISIONS ADR-008) -------------------

@pytest.mark.parametrize("dry_run", [False, True])
def test_explicit_parent_is_refused_when_target_is_confluence(project, fake, token, dry_run):
    projects.set_publish("demo-svc", "confluence", confluence_space_key="PROJ", confluence_parent_title="Sprint")
    assert sync(project, dry_run=dry_run) == {"error": "project publish target is confluence; notion publish refused"}
    assert fake.calls == []
    assert not notion.MAP_DIR.exists()


def test_explicit_parent_is_refused_when_target_is_none_or_unset(project, fake, token):
    projects.set_publish("demo-svc", "none")
    assert sync(project) == {"error": "project publish target is none; notion publish refused"}
    data = json.loads(projects.REGISTRY_FILE.read_text(encoding="utf-8"))
    del data["projects"]["demo-svc"]["publish"]
    projects.REGISTRY_FILE.write_text(json.dumps(data), encoding="utf-8")
    assert sync(project) == {"error": "project publish target is none; notion publish refused"}
    assert fake.calls == []


def test_explicit_parent_is_refused_for_unregistered_target(project, fake, token):
    plain = project["path"].parent / "plain"
    (plain / "docs" / "features" / "demo").mkdir(parents=True)
    result = notion.sync_feature("demo", PARENT, root=str(plain))
    assert result == {"error": "project publish target is none; notion publish refused"}
    assert fake.calls == []


def test_damaged_settings_are_reported_before_publishing(project, fake, token):
    data = json.loads(projects.REGISTRY_FILE.read_text(encoding="utf-8"))
    data["projects"]["demo-svc"]["publish"] = {"target": "notion", "notion": {"parent_page_id": "TOPSECRET"}}
    projects.REGISTRY_FILE.write_text(json.dumps(data), encoding="utf-8")
    result = sync(project)
    assert "error" in result and "TOPSECRET" not in result["error"]
    assert fake.calls == []


def test_explicit_parent_may_differ_from_setting_when_target_is_notion(project, fake, token):
    other = "aaaabbbbccccddddeeeeffff00001111"
    fake.blocks[other] = {"type": "page", "children": [], "archived": False}
    result = sync(project, parent=other)
    assert result["parent_page_id"] == other and result["overview"]["status"] == "created"


def test_parent_comes_from_project_settings(project, fake, token):
    projects.set_publish("demo-svc", "notion", notion_parent_page_id=PARENT)
    result = notion.sync_feature("demo", root=project["root"])
    assert result["parent_page_id"] == PARENT_ID
    assert result["overview"]["status"] == "created"


# --- upsert ------------------------------------------------------------------

def test_first_run_creates_then_rerun_updates_without_new_pages(project, fake, token):
    first = sync(project)
    assert first["feature"] == "features/demo"
    assert first["overview"]["status"] == "created" and first["overview"]["title"] == "features/demo"
    assert [(r["file"], r["status"]) for r in first["results"]] == [("PRD.md", "created"), ("TASK.md", "created")]
    assert len(fake.pages()) == 3
    overview_id = first["overview"]["page_id"]
    assert set(fake.pages()) - {overview_id} == {r["page_id"] for r in first["results"]}

    second = sync(project)
    assert second["overview"] == {**first["overview"], "status": "updated"}
    assert [r["status"] for r in second["results"]] == ["updated", "updated"]
    assert len(fake.pages()) == 3
    assert sum(1 for m, p in fake.calls if (m, p) == ("POST", "/pages")) == 3  # no new page on rerun
    # the overview's child pages survive the body replacement
    assert fake.body_types(overview_id).count("child_page") == 2
    task = second["results"][1]["page_id"]
    assert fake.body_types(task) == ["heading_1", "to_do"]  # old body replaced, not appended


def test_deleted_mapping_recovers_by_title(project, fake, token):
    first = sync(project)
    for path in notion.MAP_DIR.glob("*.json"):
        path.unlink()
    second = sync(project)
    assert second["overview"]["status"] == "updated"
    assert second["overview"]["page_id"] == first["overview"]["page_id"]
    assert len(fake.pages()) == 3


def test_damaged_mapping_is_ignored(project, fake, token):
    notion.MAP_DIR.mkdir(parents=True)
    (notion.MAP_DIR / "demo-svc.json").write_text("{not json", encoding="utf-8")
    assert sync(project)["overview"]["status"] == "created"
    saved = json.loads((notion.MAP_DIR / "demo-svc.json").read_text(encoding="utf-8"))
    assert saved["features"]["features/demo"]["parent"] == PARENT_ID
    assert TOKEN not in json.dumps(saved)


def test_archived_mapped_page_falls_back_to_title_then_create(project, fake, token):
    first = sync(project)
    overview_id = first["overview"]["page_id"]
    fake.blocks[overview_id]["archived"] = True
    second = sync(project)
    assert second["overview"]["status"] == "created"
    assert second["overview"]["page_id"] != overview_id
    assert [r["status"] for r in second["results"]] == ["created", "created"]  # under the new overview
    assert len(fake.pages()) == 3 + 2  # archived overview's children are still there (unarchived)


def _add_page(fake, parent: str, title: str) -> str:
    page_id = str(uuid.uuid4())
    fake.blocks[page_id] = {"type": "child_page", "children": [], "archived": False, "parent": parent, "title": title}
    fake.blocks[parent]["children"].append(page_id)
    return page_id


def test_overview_found_again_by_title_drops_old_child_mapping(project, fake, token):
    """REVIEW MEDIUM-2: a different overview page (title match) must not keep the old child IDs."""
    first = sync(project)
    old_overview = first["overview"]["page_id"]
    old_children = {r["page_id"] for r in first["results"]}
    fake.blocks[old_overview]["archived"] = True  # its children stay alive (Notion trash semantics)
    other = _add_page(fake, PARENT_ID, "features/demo")  # e.g. a POST that timed out but landed
    fake.calls.clear()

    second = sync(project)
    assert second["overview"]["status"] == "updated" and second["overview"]["page_id"] == other
    assert [r["status"] for r in second["results"]] == ["created", "created"]
    assert {fake.blocks[r["page_id"]]["parent"] for r in second["results"]} == {other}
    assert fake.body_types(other).count("child_page") == 2
    touched = {p.split("/")[2] for m, p in fake.calls if m in ("PATCH", "DELETE") or p.startswith("/pages/")}
    assert not touched & old_children
    saved = json.loads((notion.MAP_DIR / "demo-svc.json").read_text(encoding="utf-8"))["features"]["features/demo"]
    assert saved["overview"] == other
    assert set(saved["files"].values()) == {r["page_id"] for r in second["results"]}


def test_same_overview_keeps_child_mapping(project, fake, token):
    first = sync(project)
    second = sync(project)
    assert [r["page_id"] for r in second["results"]] == [r["page_id"] for r in first["results"]]


def test_parent_change_drops_mapping_and_leaves_old_pages_alone(project, fake, token):
    """ADR-006: a mapping recorded under another parent is not reused."""
    first = sync(project)
    old_ids = {first["overview"]["page_id"], *(r["page_id"] for r in first["results"])}
    new_parent = "aaaabbbbccccddddeeeeffff00001111"
    fake.blocks[new_parent] = {"type": "page", "children": [], "archived": False}
    projects.set_publish("demo-svc", "notion", notion_parent_page_id=new_parent)
    fake.calls.clear()

    second = notion.sync_feature("demo", root=project["root"])
    assert second["overview"]["status"] == "created"
    assert fake.blocks[second["overview"]["page_id"]]["parent"] == new_parent
    assert [r["status"] for r in second["results"]] == ["created", "created"]
    assert not {p.split("/")[2] for _, p in fake.calls if p.count("/") >= 2} & old_ids
    assert all(not fake.blocks[i]["archived"] for i in old_ids)
    saved = json.loads((notion.MAP_DIR / "demo-svc.json").read_text(encoding="utf-8"))["features"]["features/demo"]
    assert saved["parent"] == new_parent and saved["overview"] == second["overview"]["page_id"]


def test_mapping_save_failure_is_a_warning_and_keeps_results(project, fake, token, monkeypatch, tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("", encoding="utf-8")
    monkeypatch.setattr(notion, "MAP_DIR", blocker / "publish")
    result = sync(project)
    assert result["warning"].startswith("publish map not saved: ")
    assert TOKEN not in result["warning"]
    assert result["overview"]["status"] == "created"
    assert [r["status"] for r in result["results"]] == ["created", "created"]
    # nothing was remembered, so the rerun finds the same pages by title (no duplicates)
    rerun = sync(project)
    assert rerun["overview"]["status"] == "updated" and len(fake.pages()) == 3


def test_mapping_lock_timeout_is_a_warning(project, fake, token, monkeypatch):
    @contextmanager
    def busy(path):
        raise TimeoutError("publish map is busy")
        yield  # pragma: no cover

    monkeypatch.setattr(notion, "_map_lock", busy)
    result = sync(project)
    assert result["warning"] == "publish map not saved: TimeoutError"
    assert result["overview"]["status"] == "created"


def test_dry_run_makes_no_call_and_needs_no_token(project, fake):
    result = sync(project, dry_run=True)
    assert result["dry_run"] is True
    assert result["overview"]["status"] == "planned_create"
    assert [r["status"] for r in result["results"]] == ["planned_create", "planned_create"]
    assert fake.calls == []


def test_dry_run_after_publish_plans_updates(project, fake, token):
    sync(project)
    fake.calls.clear()
    result = sync(project, dry_run=True)
    assert result["overview"]["status"] == "planned_update"
    assert [r["status"] for r in result["results"]] == ["planned_update", "planned_update"]
    assert fake.calls == []


def test_long_table_rows_are_appended_after_creation(project, fake, token):
    rows = "".join(f"| {i} |\n" for i in range(150))
    (project["dir"] / "TASK.md").write_text(f"| h |\n|---|\n{rows}", encoding="utf-8")
    result = sync(project)
    task = next(r for r in result["results"] if r["file"] == "TASK.md")
    table = fake.blocks[task["page_id"]]["children"][0]
    assert fake.blocks[table]["type"] == "table"
    assert len(fake.blocks[table]["children"]) == 151


# --- failures ----------------------------------------------------------------

def _no_token(result, capsys):
    assert TOKEN not in json.dumps(result, ensure_ascii=False)
    captured = capsys.readouterr()
    assert TOKEN not in captured.out + captured.err


@pytest.mark.parametrize("status, message", [
    (401, "Notion auth failed. Check NOTION_TOKEN"),
    (403, "Notion page not shared with integration or not found"),
    (404, "Notion page not shared with integration or not found"),
    (400, "Notion API error: HTTP 400 (validation_error)"),
])
def test_overview_error_stops_children_and_hides_token(project, fake, token, capsys, status, message):
    fake.force("GET", rf"/blocks/{PARENT_ID}/children",
               httpx.Response(status, json={"code": "validation_error", "message": f"bad {TOKEN}"},
                              headers={"x-echo": TOKEN}))
    result = sync(project)
    assert result["overview"]["status"] == "error"
    assert result["overview"]["error"] == message
    assert result["results"] == []
    assert not any(m == "POST" for m, _ in fake.calls)
    _no_token(result, capsys)


def test_timeout_is_reported_without_retry(project, fake, token, capsys):
    fake.force("GET", rf"/blocks/{PARENT_ID}/children", httpx.ReadTimeout(f"timeout {TOKEN}"))
    result = sync(project)
    assert result["overview"]["error"] == "Notion request timed out after 30s"
    assert len(fake.calls) == 1
    _no_token(result, capsys)


def test_429_honours_retry_after_with_cap(project, fake, token):
    fake.force("GET", rf"/blocks/{PARENT_ID}/children", httpx.Response(429, headers={"Retry-After": "2"}))
    fake.force("GET", rf"/blocks/{PARENT_ID}/children", httpx.Response(429, headers={"Retry-After": "99"}))
    fake.force("GET", rf"/blocks/{PARENT_ID}/children", httpx.Response(429))
    result = sync(project)
    assert result["overview"]["status"] == "created"
    assert fake.sleeps == [2.0, 10.0, 1.0]


def test_429_exhaustion_is_an_error(project, fake, token, capsys):
    fake.force("GET", rf"/blocks/{PARENT_ID}/children", httpx.Response(429, headers={"Retry-After": "0"}), times=4)
    result = sync(project)
    assert result["overview"]["error"] == "Notion rate limited after 3 retries"
    assert len(fake.sleeps) == 3
    _no_token(result, capsys)


def test_5xx_retries_get_but_never_post(project, fake, token, capsys):
    fake.force("GET", rf"/blocks/{PARENT_ID}/children", httpx.Response(503))
    fake.force("POST", r"/pages", httpx.Response(502, json={"message": TOKEN}))
    result = sync(project)
    assert result["overview"]["error"] == "Notion API error: HTTP 502"
    assert sum(1 for m, p in fake.calls if (m, p) == ("POST", "/pages")) == 1
    assert len(fake.sleeps) == 1
    _no_token(result, capsys)


def test_400_is_not_retried(project, fake, token):
    fake.force("POST", r"/pages", httpx.Response(400, json={"code": "validation_error"}))
    sync(project)
    assert fake.sleeps == []


def test_one_file_failing_does_not_stop_the_rest(project, fake, token, monkeypatch):
    original = fake.__call__

    def failing(method, url, **kwargs):
        body = kwargs.get("json") or {}
        title = (((body.get("properties") or {}).get("title") or {}).get("title") or [{}])[0]
        if method == "POST" and title.get("text", {}).get("content") == "PRD":
            fake.calls.append((method, url))
            return httpx.Response(500)
        return original(method, url, **kwargs)

    monkeypatch.setattr(notion.httpx, "request", failing)
    result = sync(project)
    statuses = {r["file"]: r["status"] for r in result["results"]}
    assert statuses == {"PRD.md": "error", "TASK.md": "created"}
    assert result["results"][0]["error"] == "Notion API error: HTTP 500"


# --- paths -------------------------------------------------------------------

def test_symlinked_md_is_skipped(project, fake, token, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("secret notes", encoding="utf-8")
    (project["dir"] / "LINK.md").symlink_to(outside)
    result = sync(project)
    link = next(r for r in result["results"] if r["file"] == "LINK.md")
    assert link["status"] == "skipped"
    assert "LINK" not in [fake.blocks[p]["title"] for p in fake.pages()]


_FLOW_TEMPLATE = (config.ROOT / "templates" / "FLOW.drawio").read_text(encoding="utf-8")


def _flow(label: str) -> str:
    return _FLOW_TEMPLATE.replace("처리 성공?", label, 1)


def _overview_text(fake, overview_id: str) -> str:
    return json.dumps([fake.blocks[c] for c in fake.blocks[overview_id]["children"]
                       if fake.blocks[c]["type"] != "child_page"], ensure_ascii=False)


def test_symlinked_prd_and_flow_are_not_read_into_the_overview(project, fake, token, tmp_path):
    """REVIEW MEDIUM-1 / SECURITY L-1 (BR-12)."""
    outside_prd = tmp_path / "outside.md"
    outside_prd.write_text("# x\n\n## 1. 개요\nOUTSIDE_SENTINEL\n", encoding="utf-8")
    outside_flow = tmp_path / "outside.drawio"
    outside_flow.write_text(_flow("FLOW_SENTINEL"), encoding="utf-8")
    (project["dir"] / "PRD.md").unlink()
    (project["dir"] / "PRD.md").symlink_to(outside_prd)
    (project["dir"] / "FLOW.drawio").symlink_to(outside_flow)
    (project["dir"] / "LINK.md").symlink_to(outside_prd)

    result = sync(project)
    statuses = {r["file"]: r["status"] for r in result["results"]}
    assert statuses == {"LINK.md": "skipped", "PRD.md": "skipped", "TASK.md": "created"}
    text = _overview_text(fake, result["overview"]["page_id"])
    assert "OUTSIDE_SENTINEL" not in text and "FLOW_SENTINEL" not in text
    assert "PRD.md 없음" in text
    # the document list names only what was published
    assert "TASK" in text and "LINK" not in text


def test_in_directory_flow_still_reaches_the_overview(project, fake, token):
    (project["dir"] / "FLOW.drawio").write_text(_flow("FLOW_INSIDE"), encoding="utf-8")
    result = sync(project)
    assert "FLOW_INSIDE" in _overview_text(fake, result["overview"]["page_id"])


def test_overview_builder_ignores_symlinks_for_every_publisher(tmp_path):
    feature_dir = tmp_path / "docs" / "features" / "x"
    feature_dir.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("## 1. 개요\nOUTSIDE_SENTINEL\n", encoding="utf-8")
    (feature_dir / "PRD.md").symlink_to(outside)
    md = build_overview_markdown("features/x", feature_dir)  # Confluence default arguments
    assert "OUTSIDE_SENTINEL" not in md and "_PRD.md 없음_" in md


def test_root_outside_allowlist_is_rejected(project, fake, token, tmp_path):
    other = tmp_path / "elsewhere"
    (other / "docs" / "features" / "demo").mkdir(parents=True)
    result = notion.sync_feature("demo", PARENT, root=str(other))
    assert "outside the allowed MCP roots" in result["error"]
    assert fake.calls == []


def test_unsafe_feature_name_and_missing_dir(project, fake, token):
    assert "Invalid feature name" in sync_name(project, "../../etc")["error"]
    assert sync_name(project, "nope")["error"].startswith("Feature directory not found:")
    assert fake.calls == []


def sync_name(project, name):
    return notion.sync_feature(name, PARENT, root=project["root"])


# --- secret scan before publishing (SECURITY M-2, DECISIONS ADR-011) ---------

AWS_KEY = "AKIA" + "Q3XZ7P2M9K4L8N5R"  # assembled so this file holds no token-shaped literal


def _sent(fake) -> str:
    return json.dumps(fake.blocks, ensure_ascii=False)


def test_document_with_a_secret_is_skipped_and_never_sent(project, fake, token):
    (project["dir"] / "TASK.md").write_text(f"# TASK\n- key {AWS_KEY}\n", encoding="utf-8")
    result = sync(project)
    task = next(r for r in result["results"] if r["file"] == "TASK.md")
    assert (task["status"], task["error"]) == ("skipped", "secret pattern detected: aws-access-key")
    assert next(r for r in result["results"] if r["file"] == "PRD.md")["status"] == "created"
    assert AWS_KEY not in _sent(fake) and AWS_KEY[4:12] not in json.dumps(result)
    assert "TASK" not in [fake.blocks[p]["title"] for p in fake.pages()]
    assert "- TASK" not in _overview_text(fake, result["overview"]["page_id"])


def test_prd_with_a_secret_is_left_out_of_the_overview(project, fake, token):
    (project["dir"] / "PRD.md").write_text(f"# PRD\n\n## 1. 개요\n- {AWS_KEY}\n", encoding="utf-8")
    result = sync(project)
    assert next(r for r in result["results"] if r["file"] == "PRD.md")["status"] == "skipped"
    text = _overview_text(fake, result["overview"]["page_id"])
    assert AWS_KEY not in _sent(fake)
    assert "PRD.md 제외" in text


def test_flow_with_a_secret_is_left_out_of_the_overview(project, fake, token):
    (project["dir"] / "FLOW.drawio").write_text(_flow(AWS_KEY), encoding="utf-8")
    result = sync(project)
    assert AWS_KEY not in _sent(fake)
    assert "서비스 흐름" not in _overview_text(fake, result["overview"]["page_id"])


def test_dry_run_reports_the_secret_skip_without_a_call(project, fake):
    (project["dir"] / "TASK.md").write_text(f"{AWS_KEY}\n", encoding="utf-8")
    result = sync(project, dry_run=True)
    task = next(r for r in result["results"] if r["file"] == "TASK.md")
    assert (task["status"], task["error"]) == ("skipped", "secret pattern detected: aws-access-key")
    assert fake.calls == []


def test_ordinary_security_prose_is_still_published(project, fake, token):
    (project["dir"] / "TASK.md").write_text(
        "# TASK\n- password: 8자 이상\n- NOTION_TOKEN 은 ntn_ 접두\n- Bearer <token>\n", encoding="utf-8")
    result = sync(project)
    assert [r["status"] for r in result["results"]] == ["created", "created"]


# --- round 3: REVIEW R3-1/R3-2 ------------------------------------------------

@pytest.mark.parametrize("dry_run", [True, False])
def test_no_publishable_md_makes_no_call(project, fake, token, dry_run):
    """R3-1: every .md skipped → no overview page; the dry-run says the same."""
    for name in ("PRD.md", "TASK.md"):
        (project["dir"] / name).write_text(f"{AWS_KEY}\n", encoding="utf-8")
    result = sync(project, dry_run=dry_run)
    assert fake.calls == []
    assert result["overview"] is None and result["warning"] == "No publishable .md files"
    assert [(r["file"], r["status"]) for r in result["results"]] == [("PRD.md", "skipped"), ("TASK.md", "skipped")]
    assert AWS_KEY not in json.dumps(result)


def test_md_changed_after_listing_is_rechecked_before_sending(project, fake, token, monkeypatch):
    """R3-2: the scan right before sending catches a change after the listing scan."""
    listed = notion.publishable_files

    def list_then_change(feature_dir):
        out = listed(feature_dir)
        (feature_dir / "TASK.md").write_text(f"# TASK\n{AWS_KEY}\n", encoding="utf-8")
        return out

    monkeypatch.setattr(notion, "publishable_files", list_then_change)
    result = sync(project)
    task = next(r for r in result["results"] if r["file"] == "TASK.md")
    assert (task["status"], task["error"]) == ("skipped", "secret pattern detected: aws-access-key")
    assert AWS_KEY not in _sent(fake)


def test_non_utf8_flow_only_drops_the_flow_section(project, fake, token):
    (project["dir"] / "FLOW.drawio").write_bytes(_FLOW_TEMPLATE.encode("utf-16"))
    result = sync(project)
    assert result["overview"]["status"] == "created"
    assert "서비스 흐름" not in _overview_text(fake, result["overview"]["page_id"])
