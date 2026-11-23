"""publish_spec / publish --spec / --spec-index (BR-6, BR-7, BR-8, AC-6, AC-7, AC-8, AC-12, AC-18).

Notion and Confluence are the in-memory HTTP fakes of the owned-upsert tests; no test reaches the network.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from agent_platform_mcp import cli
from agent_platform_mcp.tools import confluence, notion, projects, spec, spec_publish
from agent_platform_mcp.tools import spec_publish_map as pmap
from test_confluence_owned import BASE, PARENT_ID as CONF_PARENT, PARENT_TITLE, SPACE_KEY, FakeConfluence
from test_notion import PARENT, PARENT_ID, TOKEN, _add_page
from test_notion_owned import OwnedFakeNotion

GH_TOKEN = "ghp_" + "A1b2C3d4" * 5  # a github-token shape, never a real one


def write_spec(path, slug: str, title: str = "결제", status: str = "approved", body: str = "규칙 본문") -> None:
    spec_dir = path / "docs" / "specs" / slug
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "SPEC.md").write_text(
        f"---\nspec: {slug}\ntitle: {title}\nstatus: {status}\nupdated: 2026-11-23\n---\n# SPEC: {title}\n\n{body}\n\n"
        "## 6. 변경 이력\n| 날짜 | 작업 | 요약 | PR |\n|---|---|---|---|\n", encoding="utf-8")


@pytest.fixture
def project(tmp_path, monkeypatch):
    base = tmp_path / "projects"
    service = base / "svc"
    service.mkdir(parents=True)
    write_spec(service, "pay")
    monkeypatch.setenv("AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS", str(base))
    projects.register(str(service), "demo-svc")
    return {"root": "demo-svc", "path": service, "base": base}


@pytest.fixture
def no_network(monkeypatch):
    calls = []

    def refuse(*args, **kwargs):
        calls.append(args)
        raise AssertionError("network call attempted")

    for name in ("request", "get", "post", "put"):
        monkeypatch.setattr(httpx, name, refuse)
    return calls


@pytest.fixture
def notion_api(project, monkeypatch):
    projects.set_publish("demo-svc", "notion", notion_parent_page_id=PARENT)
    api = OwnedFakeNotion()
    monkeypatch.setattr(notion.httpx, "request", api)
    monkeypatch.setattr(notion, "_sleep", lambda _: None)
    monkeypatch.setenv("NOTION_TOKEN", TOKEN)
    return api


@pytest.fixture
def conf_api(project, monkeypatch):
    projects.set_publish("demo-svc", "confluence", confluence_space_key=SPACE_KEY, confluence_parent_title=PARENT_TITLE)
    monkeypatch.setenv("CONFLUENCE_URL", BASE)
    monkeypatch.setenv("CONFLUENCE_EMAIL", "user@example.com")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "fake-token-SECRET")
    api = FakeConfluence()
    for method in ("get", "post", "put"):
        monkeypatch.setattr(confluence.httpx, method, lambda url, _m=method.upper(), **kw: api.handle(_m, url, **kw))
    return api


def publish(**kwargs):
    return spec_publish.publish_spec(root="demo-svc", **kwargs)


def page_text(api: OwnedFakeNotion, page_id: str) -> str:
    key = api.key(page_id)
    texts = []
    for child in api.blocks[key]["children"]:
        block = api.blocks[child]
        if not block["archived"]:
            texts += [r.get("text", {}).get("content", "") for r in (block.get("payload") or {}).get("rich_text", [])]
    return "\n".join(texts)


# --- arguments, target none, guards (no remote call) -------------------------

@pytest.mark.parametrize("kwargs, code", [
    ({}, "invalid_arguments"), ({"slug": "pay", "index": True}, "invalid_arguments"),
    ({"index": True, "allow_draft": True}, "invalid_arguments"), ({"slug": "../x"}, "invalid_spec_slug"),
])
def test_bad_arguments_are_errors_without_calls(project, no_network, kwargs, code):
    assert publish(**kwargs)["code"] == code
    assert no_network == []


@pytest.mark.parametrize("kwargs, key", [({"slug": "pay"}, "specs/pay"), ({"index": True}, "specs/INDEX")])
def test_target_none_is_skipped_without_calls(project, no_network, kwargs, key):
    assert publish(**kwargs) == {"feature": key, "project_id": "demo-svc", "target": "none", "status": "skipped",
                                 "reason": "publish target is none", "result": None}
    other = project["base"] / "plain"
    write_spec(other, "pay")
    result = spec_publish.publish_spec(root=str(other), **kwargs)  # unregistered → none (BR-6)
    assert (result["project_id"], result["status"]) == (None, "skipped")
    assert no_network == []


def test_target_none_reads_no_document(project, no_network, monkeypatch):
    """Review 4b L-1 (mutation M6): target none returns before the SPEC or INDEX is read."""
    def refuse(*args, **kwargs):
        raise AssertionError("document read for target none")

    monkeypatch.setattr(spec_publish, "_spec_document", refuse)
    monkeypatch.setattr(spec, "index_markdown", refuse)
    for kwargs in ({"slug": "pay"}, {"index": True}):
        assert publish(**kwargs)["status"] == "skipped"
    assert no_network == []


def test_draft_is_skipped_unless_allowed(project, notion_api):
    write_spec(project["path"], "pay", status="draft")
    notion_api.calls.clear()
    result = publish(slug="pay")
    assert (result["status"], result["reason"], result["result"]) == ("skipped", "spec is not approved",
                                                                      {"code": "publish_draft"})
    assert notion_api.calls == []
    assert publish(slug="pay", allow_draft=True)["status"] == "published"


@pytest.mark.parametrize("where", ["body", "title"])
def test_secret_is_skipped_with_kind_only_and_no_calls(project, notion_api, where):
    write_spec(project["path"], "pay", **({"body": f"token {GH_TOKEN}"} if where == "body" else {"title": GH_TOKEN}))
    path = project["path"] / "docs/specs/pay/SPEC.md"
    path.write_text(path.read_text(encoding="utf-8").replace(f"# SPEC: {GH_TOKEN}", "# SPEC"), encoding="utf-8")
    notion_api.calls.clear()
    for dry_run in (False, True):
        result = publish(slug="pay", dry_run=dry_run)
        assert result["status"] == "skipped" and result["reason"] == "secret pattern detected: github-token"
        assert result["result"] == {"code": "secret_detected"} and "A1b2" not in json.dumps(result)
    assert notion_api.calls == []


def test_secret_in_index_makes_no_call(project, notion_api):
    write_spec(project["path"], "pay", title=GH_TOKEN)
    notion_api.calls.clear()
    assert publish(index=True)["reason"] == "secret pattern detected: github-token"
    assert notion_api.calls == []


def test_symlinked_or_missing_spec_is_skipped(project, notion_api, tmp_path):
    outside = tmp_path / "outside"
    write_spec(outside, "evil")
    (project["path"] / "docs/specs/link").symlink_to(outside / "docs/specs/evil")
    (project["path"] / "docs/specs/pay/SPEC.md").unlink()
    (project["path"] / "docs/specs/pay/SPEC.md").symlink_to(outside / "docs/specs/evil/SPEC.md")
    notion_api.calls.clear()
    assert publish(slug="link")["reason"] == spec_publish.OUTSIDE
    assert publish(slug="pay")["reason"] == spec_publish.OUTSIDE
    missing = publish(slug="nope")
    assert (missing["status"], missing["result"]) == ("skipped", {"code": "spec_not_found"})
    assert notion_api.calls == []


def test_dry_run_plans_without_calls(project, notion_api):
    notion_api.calls.clear()
    result = publish(slug="pay", dry_run=True)
    assert result["status"] == "planned"
    assert result["result"] == {"title": "결제", "dry_run": True, "parent_page_id": PARENT_ID,
                                "ownership": spec_publish.OWNERSHIP_UNCHECKED}
    planned = publish(slug="pay", dry_run=True, adopt_from="old-svc")["result"]
    assert planned["may_adopt"] == ["old-svc"]  # the opt-in is shown; the remote outcome is not knowable
    assert notion_api.calls == []


@pytest.mark.parametrize("head", ["--- \n", "---\t\n", "\ufeff---\n"])
def test_front_matter_variants_are_never_published(project, notion_api, head):
    """Security 4b L-1: the strip uses the parse boundary (`--- `, tab, BOM)."""
    path = project["path"] / "docs/specs/pay/SPEC.md"
    path.write_text(path.read_text(encoding="utf-8").replace("---\n", head, 1), encoding="utf-8")
    result = publish(slug="pay")
    assert result["status"] == "published"
    text = page_text(notion_api, result["result"]["page_id"])
    assert "status: approved" not in text and "spec: pay" not in text and "규칙 본문" in text


def test_published_spec_hides_defect_history_rows(project, notion_api, monkeypatch):
    """Review 4b M-1: the SPEC page follows the remote INDEX rule for fix/·hotfix/ rows."""
    spec.spec_history_add("pay", "features/pay-x", "결제 확장", pr="https://github.com/a/b/pull/3",
                          date="2026-11-22", root="demo-svc")
    spec.spec_history_add("pay", "hotfix/leak-1", "token leak fix", pr="https://github.com/a/b/pull/9",
                          date="2026-11-23", root="demo-svc")
    sent = []
    real = notion.upsert_owned_page
    monkeypatch.setattr(notion, "upsert_owned_page", lambda parent, title, md, *a, **kw: (
        sent.append(md), real(parent, title, md, *a, **kw))[1])
    assert publish(slug="pay")["status"] == "published"
    text = sent[0]
    assert "| 2026-11-23 | (비공개) | - | - |" in text and "| 2026-11-22 | features/pay-x | 결제 확장 | #3 |" in text
    assert "2026-11-23" in text and "(비공개)" in text and "features/pay-x" in text and "#3" in text
    for leaked in ("leak-1", "token leak fix", "#9", "github.com"):
        assert leaked not in text, leaked
    assert "hotfix/leak-1" in (project["path"] / "docs/specs/pay/SPEC.md").read_text(encoding="utf-8")


# --- Notion ------------------------------------------------------------------

def test_notion_created_then_updated_through_the_map(project, notion_api):
    first = publish(slug="pay")
    assert first["status"] == "published" and first["result"]["action"] == "created"
    page_id = first["result"]["page_id"]
    assert pmap.load_page_id("demo-svc", "pay", target="notion", parent=PARENT_ID) == page_id
    assert page_text(notion_api, page_id).startswith("agent-platform:demo-svc/pay")
    assert "status: approved" not in page_text(notion_api, page_id)  # front-matter is not published
    second = publish(slug="pay")
    assert second["result"]["action"] == "updated" and second["result"]["page_id"] == page_id
    assert len(notion_api.pages("결제")) == 1


def test_notion_lost_map_reconnects_by_owner_search(project, notion_api):
    page_id = publish(slug="pay")["result"]["page_id"]
    for path in notion.MAP_DIR.glob("*.json"):
        path.unlink()
    result = publish(slug="pay")
    assert result["result"]["action"] == "updated" and result["result"]["page_id"] == page_id


def test_notion_adoption_with_opt_in_rewrites_the_marker(project, notion_api):
    """Review 4b L-2: a Notion adoption the user opted in to replaces the marker and reports it."""
    page = _add_page(notion_api, PARENT_ID, "결제")
    notion_api.mark(page, {"project_id": "old-svc", "slug": "pay"})
    result = publish(slug="pay", adopt_from="old-svc")
    assert result["status"] == "published" and result["result"]["adopted_from"] == "old-svc"
    assert notion_api.key(result["result"]["page_id"]) == page
    assert notion_api.first_text(page) == "agent-platform:demo-svc/pay"
    again = publish(slug="pay")  # now the exact marker: no opt-in needed, nothing adopted
    assert again["status"] == "published" and "adopted_from" not in again["result"]


def test_notion_exact_owner_wins_over_an_adoptable_page(project, notion_api):
    """Review 4b L-6: with the map lost, the exact marker is chosen even when an adoptable page is first."""
    adoptable = _add_page(notion_api, PARENT_ID, "결제")
    notion_api.mark(adoptable, {"project_id": "old-svc", "slug": "pay"})
    exact = _add_page(notion_api, PARENT_ID, "결제")
    notion_api.mark(exact, {"project_id": "demo-svc", "slug": "pay"})
    result = publish(slug="pay", adopt_from="old-svc")
    assert notion_api.key(result["result"]["page_id"]) == exact and "adopted_from" not in result["result"]
    assert notion_api.first_text(adoptable) == "agent-platform:old-svc/pay"


def test_notion_human_page_with_the_same_title_is_title_conflict(project, notion_api):
    human = _add_page(notion_api, PARENT_ID, "결제")
    result = publish(slug="pay")
    assert (result["status"], result["result"]["code"]) == ("failed", "title_conflict")
    assert result["reason"] == "page '결제' exists and is not owned by agent-platform"
    assert notion_api.blocks[human]["children"] == []


def test_notion_401_is_failed_without_the_token(project, notion_api):
    notion_api.force("GET", r"/blocks/.*", httpx.Response(401, json={}))
    result = publish(slug="pay")
    assert result["status"] == "failed" and result["result"] == {"http_status": 401}
    assert TOKEN not in json.dumps(result)


def test_index_page_is_owned_titled_and_hides_defect_work(project, notion_api):
    for key in ("features/pay-x", "fix/leak-1"):
        item = project["path"] / "docs" / key
        item.mkdir(parents=True)
        (item / "PRD.md").write_text("---\nstatus: draft\nspec: pay\n---\n# PRD\n", encoding="utf-8")
    result = publish(index=True)
    assert result["feature"] == "specs/INDEX" and result["result"]["action"] == "created"
    page_id = result["result"]["page_id"]
    assert notion_api.blocks[notion_api.key(page_id)]["title"] == "demo-svc 기능 목록"
    text = page_text(notion_api, page_id)
    assert text.startswith("agent-platform:demo-svc/INDEX")
    assert "leak-1" not in text and spec.INDEX_MARK not in text
    assert pmap.load_page_id("demo-svc", None, target="notion", parent=PARENT_ID) == page_id


# --- Confluence ----------------------------------------------------------------

def test_confluence_created_then_updated_with_version_bump(project, conf_api):
    first = publish(slug="pay")
    assert first["status"] == "published" and first["result"]["action"] == "created"
    page_id = first["result"]["page_id"]
    second = publish(slug="pay")
    assert second["result"]["action"] == "updated" and second["result"]["page_id"] == page_id
    assert second["result"]["version"] == 2 and conf_api.pages[page_id]["version"] == 2
    for path in notion.MAP_DIR.glob("*.json"):
        path.unlink()
    third = publish(slug="pay")  # lost map: the owner search under the parent finds the page
    assert third["result"]["page_id"] == page_id and third["result"]["version"] == 3


def test_confluence_human_page_is_title_conflict_and_elsewhere_is_duplicate_title(project, conf_api):
    human = conf_api.add("결제")
    result = publish(slug="pay")
    assert (result["status"], result["result"]["code"]) == ("failed", "title_conflict")
    conf_api.pages[human]["parentId"] = "999"  # same title outside the parent: never touched
    result = publish(slug="pay")
    assert (result["status"], result["result"]) == ("failed", {"code": "duplicate_title", "http_status": 400})
    assert conf_api.pages[human]["version"] == 1


def test_confluence_401_is_failed_without_the_token(project, conf_api):
    conf_api.force("GET", r"/wiki/api/v2/spaces", httpx.Response(401, json={}))
    result = publish(slug="pay")
    assert result["status"] == "failed" and result["result"]["http_status"] == 401
    assert "fake-token-SECRET" not in json.dumps(result)


# --- accept_owner policy (AC-18; Review 4b M-2, Security 4b M-1) ----------------

OLD_MARK = {"project_id": "old-svc", "slug": "pay"}


def set_previous_ids(ids):
    data = json.loads(projects.REGISTRY_FILE.read_text(encoding="utf-8"))
    data["projects"]["demo-svc"]["previous_ids"] = ids
    projects.REGISTRY_FILE.write_text(json.dumps(data), encoding="utf-8")


def test_foreign_marker_without_opt_in_is_foreign_owner_and_untouched(project, conf_api):
    """An unregistered project_id on this machine is not consent: nothing is written."""
    page_id = conf_api.add("결제", owner=OLD_MARK)
    result = publish(slug="pay")
    assert result["status"] == "failed"
    assert result["result"] == {"code": "foreign_owner", "page_id": page_id, "found_project_id": "old-svc"}
    assert "--adopt-from old-svc" in result["reason"]
    assert conf_api.pages[page_id]["version"] == 1
    assert conf_api.pages[page_id]["properties"]["agent-platform"]["value"] == OLD_MARK


def test_registry_previous_ids_opt_in_to_adoption(project, conf_api):
    page_id = conf_api.add("결제", owner=OLD_MARK)
    set_previous_ids(["old-svc"])
    result = publish(slug="pay")
    assert result["status"] == "published" and result["result"]["adopted_from"] == "old-svc"
    assert conf_api.pages[page_id]["properties"]["agent-platform"]["value"] == {"project_id": "demo-svc", "slug": "pay"}


def test_registry_read_error_means_no_adoption(project, conf_api, monkeypatch):
    """Review 4b L-2 (mutation M14): a registry problem never turns into consent."""
    page_id = conf_api.add("결제", owner=OLD_MARK)
    set_previous_ids(["old-svc"])
    real = projects.previous_ids

    def broken(project_id):
        raise RuntimeError("registry unreadable")

    monkeypatch.setattr(projects, "previous_ids", broken)
    assert publish(slug="pay")["result"]["code"] == "foreign_owner"
    set_previous_ids("old-svc")  # malformed field
    monkeypatch.setattr(projects, "previous_ids", real)
    assert publish(slug="pay")["result"]["code"] == "foreign_owner"
    assert conf_api.pages[page_id]["version"] == 1


def test_marker_adopted_with_adopt_from_is_reported(project, conf_api):
    page_id = conf_api.add("결제", owner=OLD_MARK)
    assert publish(slug="pay", adopt_from="Bad/Id")["code"] == "invalid_arguments"
    result = publish(slug="pay", adopt_from="old-svc")
    assert result["status"] == "published" and result["result"]["page_id"] == page_id
    assert result["result"]["adopted_from"] == "old-svc"
    assert conf_api.pages[page_id]["properties"]["agent-platform"]["value"] == {"project_id": "demo-svc", "slug": "pay"}
    assert "adopted_from" not in publish(slug="pay")["result"]  # now an exact marker


def test_marker_of_a_registered_project_or_other_slug_is_not_adopted(project, notion_api):
    other = project["base"] / "other"
    other.mkdir()
    projects.register(str(other), "other-svc")
    for owner in ({"project_id": "other-svc", "slug": "pay"}, {"project_id": "old-svc", "slug": "refund"}):
        page = _add_page(notion_api, PARENT_ID, "결제")
        notion_api.mark(page, owner)
        result = publish(slug="pay")
        code = "foreign_owner" if owner["slug"] == "pay" else "title_conflict"  # registered or not
        assert (result["status"], result["result"]["code"]) == ("failed", code)
        notion_api.blocks[page]["archived"] = True


# --- CLI / MCP -----------------------------------------------------------------

def test_cli_spec_flags(project, no_network, capsys):
    # Review 4b L-4: skipped with a reason (target none here) is exit 3; planned stays 0.
    assert cli.main(["publish", "--spec", "pay", "--root", "demo-svc"]) == cli.SPEC_SKIPPED_EXIT == 3
    assert json.loads(capsys.readouterr().out)["feature"] == "specs/pay"
    assert cli.main(["publish", "--spec-index", "--root", "demo-svc", "--dry-run"]) == 3
    assert json.loads(capsys.readouterr().out)["feature"] == "specs/INDEX"
    for argv in (["publish"], ["publish", "demo", "--spec", "pay"], ["publish", "demo", "--allow-draft"],
                 ["publish", "--spec-index", "--allow-draft"], ["publish", "demo", "--adopt-from", "old-svc"]):
        assert cli.main([*argv, "--root", "demo-svc"]) == 1
        assert json.loads(capsys.readouterr().out)["code"] == "invalid_arguments"
    with pytest.raises(SystemExit):
        cli.main(["publish", "--spec", "pay", "--spec-index"])
    capsys.readouterr()
    assert no_network == []


def test_cli_failed_publish_exits_1(project, notion_api, capsys):
    _add_page(notion_api, PARENT_ID, "결제")
    assert cli.main(["publish", "--spec", "pay", "--root", "demo-svc"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


def test_cli_adopt_from_and_exit_codes(project, conf_api, capsys):
    page_id = conf_api.add("결제", owner=OLD_MARK)
    assert cli.main(["publish", "--spec", "pay", "--root", "demo-svc"]) == 1
    assert json.loads(capsys.readouterr().out)["result"]["code"] == "foreign_owner"
    assert cli.main(["publish", "--spec", "pay", "--root", "demo-svc", "--dry-run", "--adopt-from", "old-svc"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "planned"
    assert cli.main(["publish", "--spec", "pay", "--root", "demo-svc", "--adopt-from", "old-svc"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["adopted_from"] == "old-svc"
    assert conf_api.pages[page_id]["version"] == 2
    write_spec(project["path"], "pay", status="draft")
    assert cli.main(["publish", "--spec", "pay", "--root", "demo-svc"]) == 3


# --- MCP confirmation (Security 4b M-2) ----------------------------------------

def test_mcp_publish_needs_confirm_and_sends_nothing_without_it(project, notion_api):
    from agent_platform_mcp import server

    notion_api.calls.clear()
    asked = server.publish_spec(slug="pay", root="demo-svc")
    assert asked["status"] == "confirmation_required" and "confirm=true" in asked["reason"]
    assert asked["result"]["title"] == "결제" and asked["result"]["parent_page_id"] == PARENT_ID
    assert asked["target"] == "notion" and asked["result"]["dry_run"] is False
    assert server.publish_spec(index=True, root="demo-svc")["status"] == "confirmation_required"
    assert server.publish_spec(slug="pay", dry_run=True, root="demo-svc")["status"] == "planned"  # a dry-run needs no confirm
    assert notion_api.calls == []
    assert server.publish_spec(slug="pay", confirm=True, root="demo-svc")["status"] == "published"


def test_mcp_allow_draft_needs_confirm_even_for_a_dry_run(project, notion_api):
    from agent_platform_mcp import server

    write_spec(project["path"], "pay", status="draft")
    notion_api.calls.clear()
    for dry_run in (True, False):
        asked = server.publish_spec(slug="pay", allow_draft=True, dry_run=dry_run, root="demo-svc")
        assert asked["status"] == "confirmation_required" and asked["result"]["allow_draft"] is True
        assert "draft" in asked["reason"]
    assert server.publish_spec(slug="pay", root="demo-svc")["status"] == "skipped"  # nothing to confirm: not approved
    assert notion_api.calls == []
    assert server.publish_spec(slug="pay", allow_draft=True, confirm=True, root="demo-svc")["status"] == "published"


def test_mcp_without_confirm_keeps_skips_and_errors(project, no_network):
    from agent_platform_mcp import server

    assert server.publish_spec(slug="pay", root="demo-svc")["status"] == "skipped"  # target none
    assert server.publish_spec(root="demo-svc")["code"] == "invalid_arguments"
    assert no_network == []


def test_server_lists_publish_spec():
    from agent_platform_mcp import server

    assert "publish_spec" in {tool.name for tool in asyncio.run(server.mcp.list_tools())}
