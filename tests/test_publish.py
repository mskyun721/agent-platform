"""publish_feature routing: none / confluence / notion, without any real remote call."""

from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import patch

import httpx
import pytest

from agent_platform_mcp import cli
from agent_platform_mcp.tools import notion, projects, publish

PARENT = "1f2e3d4c5b6a79881726354433221100"
TOKEN = "ntn_FAKEtoken0123456789abcdefSECRET"


@pytest.fixture
def project(tmp_path, monkeypatch):
    base = tmp_path / "projects"
    service = base / "svc"
    feature_dir = service / "docs" / "features" / "demo"
    feature_dir.mkdir(parents=True)
    (feature_dir / "PRD.md").write_text("# PRD\n", encoding="utf-8")
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


def test_unset_target_is_skipped_without_calls(project, no_network):
    result = publish.publish_feature("demo", root=project["root"])
    assert result == {"feature": "features/demo", "project_id": "demo-svc", "target": "none",
                      "status": "skipped", "reason": "publish target is none", "result": None}
    assert no_network == []


def test_explicit_none_and_unregistered_target_are_skipped(project, no_network, tmp_path):
    projects.set_publish("demo-svc", "none")
    assert publish.publish_feature("demo", root=project["root"])["status"] == "skipped"
    other = project["base"] / "plain"
    (other / "docs" / "fix" / "bug-one").mkdir(parents=True)
    result = publish.publish_feature("fix/bug-one", root=str(other))
    assert (result["project_id"], result["target"], result["status"]) == (None, "none", "skipped")
    assert no_network == []


def test_damaged_settings_report_field_only(project, no_network):
    data = json.loads(projects.REGISTRY_FILE.read_text(encoding="utf-8"))
    data["projects"]["demo-svc"]["publish"] = {"target": "confluence", "confluence": {"space_key": "TOPSECRET"}}
    projects.REGISTRY_FILE.write_text(json.dumps(data), encoding="utf-8")
    result = publish.publish_feature("demo", root=project["root"])
    assert result == {"error": "Invalid publish settings: confluence.parent_title"}
    assert no_network == []


def test_missing_feature_dir_is_an_error(project, no_network):
    projects.set_publish("demo-svc", "notion", notion_parent_page_id=PARENT)
    assert publish.publish_feature("nope", root=project["root"])["error"].startswith("Feature directory not found:")


def test_confluence_delegates_with_settings(project):
    projects.set_publish("demo-svc", "confluence", confluence_space_key="PROJ", confluence_parent_title="Sprint")
    delegated = {"feature": "demo", "overview": {"title": "demo", "status": "created", "page_id": "1", "url": "u"},
                 "attachments": [], "results": [{"file": "PRD.md", "status": "created", "url": "u"}]}
    with patch.object(publish.confluence_tools, "sync_feature", return_value=delegated) as sync:
        result = publish.publish_feature("demo", root=project["root"])
    sync.assert_called_once_with("PROJ", "Sprint", "demo", overview=True, attach_flow=True, root="demo-svc")
    assert result["target"] == "confluence" and result["status"] == "published" and result["result"] == delegated


@pytest.mark.parametrize("delegated, status", [
    ({"overview": {"status": "error", "error": "dup"}, "results": [{"status": "created"}]}, "partial"),
    ({"overview": {"status": "error", "error": "dup"}, "results": [{"status": "error"}]}, "failed"),
    ({"overview": {"status": "created"}, "results": [{"status": "error"}, {"status": "created"}]}, "partial"),
])
def test_confluence_status_rules(project, delegated, status):
    projects.set_publish("demo-svc", "confluence", confluence_space_key="PROJ", confluence_parent_title="Sprint")
    with patch.object(publish.confluence_tools, "sync_feature", return_value=delegated):
        assert publish.publish_feature("demo", root=project["root"])["status"] == status


def test_confluence_without_md_files_is_skipped_not_published(project):
    """REVIEW LOW: nothing published must not look like success."""
    projects.set_publish("demo-svc", "confluence", confluence_space_key="PROJ", confluence_parent_title="Sprint")
    delegated = {"feature": "demo", "results": [], "warning": "No .md files found in /x"}
    with patch.object(publish.confluence_tools, "sync_feature", return_value=delegated):
        result = publish.publish_feature("demo", root=project["root"])
    assert (result["status"], result["reason"], result["result"]) == ("skipped", "no .md files to publish", delegated)


def test_confluence_without_md_files_end_to_end(project):
    (project["path"] / "docs" / "features" / "demo" / "PRD.md").unlink()
    projects.set_publish("demo-svc", "confluence", confluence_space_key="PROJ", confluence_parent_title="Sprint")
    result = publish.publish_feature("demo", root=project["root"])
    assert result["status"] == "skipped" and result["reason"] == "no .md files to publish"


AWS_KEY = "AKIA" + "Q3XZ7P2M9K4L8N5R"


@pytest.mark.parametrize("dry_run", [True, False])
def test_notion_all_skipped_is_skipped_for_dry_run_and_real(project, no_network, monkeypatch, dry_run):
    """REVIEW R3-1: nothing publishable is skipped before any remote call, dry-run or not."""
    monkeypatch.setenv("NOTION_TOKEN", TOKEN)
    projects.set_publish("demo-svc", "notion", notion_parent_page_id=PARENT)
    (project["path"] / "docs" / "features" / "demo" / "PRD.md").write_text(AWS_KEY, encoding="utf-8")
    result = publish.publish_feature("demo", root=project["root"], dry_run=dry_run)
    assert (result["status"], result["reason"]) == ("skipped", "no publishable .md files")
    assert result["result"]["skipped"] == [{"file": "PRD.md", "error": "secret pattern detected: aws-access-key"}]
    assert AWS_KEY not in json.dumps(result) and no_network == []


@pytest.mark.parametrize("target", ["notion", "confluence"])
@pytest.mark.parametrize("dry_run", [True, False])
def test_no_md_at_all_is_skipped_for_every_target(project, no_network, target, dry_run):
    (project["path"] / "docs" / "features" / "demo" / "PRD.md").unlink()
    if target == "notion":
        projects.set_publish("demo-svc", "notion", notion_parent_page_id=PARENT)
    else:
        projects.set_publish("demo-svc", "confluence", confluence_space_key="PROJ", confluence_parent_title="Sprint")
    result = publish.publish_feature("demo", root=project["root"], dry_run=dry_run)
    assert (result["target"], result["status"], result["reason"]) == (target, "skipped", "no .md files to publish")
    assert no_network == []


def test_confluence_env_error_is_passed_through(project):
    projects.set_publish("demo-svc", "confluence", confluence_space_key="PROJ", confluence_parent_title="Sprint")
    result = publish.publish_feature("demo", root=project["root"])
    assert result == {"error": "Missing env vars: CONFLUENCE_URL, CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN"}


def test_confluence_dry_run_makes_no_call(project, no_network):
    projects.set_publish("demo-svc", "confluence", confluence_space_key="PROJ", confluence_parent_title="Sprint")
    result = publish.publish_feature("demo", root=project["root"], dry_run=True)
    assert result["status"] == "planned" and result["result"]["files"] == ["PRD.md"]
    assert no_network == []


def test_notion_without_token_is_an_error_without_calls(project, no_network):
    projects.set_publish("demo-svc", "notion", notion_parent_page_id=PARENT)
    assert publish.publish_feature("demo", root=project["root"]) == {"error": "Missing env var: NOTION_TOKEN"}
    assert no_network == []


def test_notion_dry_run_without_token(project, no_network):
    projects.set_publish("demo-svc", "notion", notion_parent_page_id=PARENT)
    result = publish.publish_feature("demo", root=project["root"], dry_run=True)
    assert result["status"] == "planned" and result["target"] == "notion"
    assert result["result"]["overview"]["status"] == "planned_create"
    assert no_network == []


def test_notion_route_passes_parent_and_maps_status(project, monkeypatch):
    projects.set_publish("demo-svc", "notion", notion_parent_page_id=PARENT)
    seen = {}

    def fake_sync(feature, parent, root=None, dry_run=False):
        seen.update(feature=feature, parent=parent, root=root, dry_run=dry_run)
        return {"feature": "features/demo", "parent_page_id": parent, "dry_run": False,
                "overview": {"status": "error", "error": "Notion auth failed. Check NOTION_TOKEN"}, "results": []}

    monkeypatch.setattr(notion, "sync_feature", fake_sync)
    result = publish.publish_feature("demo", root=project["root"])
    assert seen == {"feature": "demo", "parent": PARENT, "root": "demo-svc", "dry_run": False}
    assert result["status"] == "failed" and result["reason"] == "Notion auth failed. Check NOTION_TOKEN"


def test_cli_publish_exit_codes(project, no_network, capsys):
    assert cli.main(["publish", "demo", "--root", "demo-svc"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "skipped"
    projects.set_publish("demo-svc", "notion", notion_parent_page_id=PARENT)
    assert cli.main(["publish", "demo", "--root", "demo-svc", "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "planned"
    assert cli.main(["publish", "demo", "--root", "demo-svc"]) == 1  # no NOTION_TOKEN
    assert json.loads(capsys.readouterr().out) == {"error": "Missing env var: NOTION_TOKEN"}


def test_server_lists_tools_without_env():
    # conftest removed NOTION_TOKEN/CONFLUENCE_*; nothing reads them at import or listing time.
    assert "NOTION_TOKEN" not in os.environ
    from agent_platform_mcp import server

    names = {tool.name for tool in asyncio.run(server.mcp.list_tools())}
    assert {"notion_sync_feature", "publish_feature", "confluence_sync_feature"} <= names
