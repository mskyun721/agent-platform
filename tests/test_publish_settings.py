"""Per-project publish target in the (isolated) project registry and its CLI."""

from __future__ import annotations

import json

import pytest

from agent_platform_mcp import cli
from agent_platform_mcp.tools import projects

PARENT = "1F2E3D4C-5B6A-7988-1726-354433221100"


@pytest.fixture
def registered(tmp_path, monkeypatch):
    base = tmp_path / "projects"
    (base / "svc").mkdir(parents=True)
    monkeypatch.setenv("AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS", str(base))
    projects.register(str(base / "svc"), "demo-svc")
    return "demo-svc"


def stored(project_id: str) -> dict:
    return json.loads(projects.REGISTRY_FILE.read_text(encoding="utf-8"))["projects"][project_id]


def test_registry_is_isolated_by_conftest(tmp_path):
    assert projects.REGISTRY_FILE.parent == tmp_path


def test_record_without_publish_stays_valid(registered):
    assert "publish" not in stored(registered)
    assert projects.get_publish(registered) is None
    assert projects.get_publish(None) is None
    listing = projects.list_projects()["projects"][0]
    assert listing["publish"] is None


def test_notion_target_is_normalized_and_listed(registered):
    result = projects.set_publish(registered, "notion", notion_parent_page_id=PARENT)
    expected = {"target": "notion", "notion": {"parent_page_id": PARENT.replace("-", "").lower()}}
    assert result == {"project_id": registered, "publish": expected}
    assert stored(registered)["publish"] == expected
    assert projects.list_projects()["projects"][0]["publish"] == expected
    assert projects.set_publish(registered, "notion", notion_parent_page_id=PARENT) == result  # idempotent


def test_confluence_target_and_none_resets(registered):
    projects.set_publish(registered, "confluence", confluence_space_key="PROJ", confluence_parent_title="Sprint")
    assert projects.get_publish(registered) == {
        "target": "confluence", "confluence": {"space_key": "PROJ", "parent_title": "Sprint"}}
    projects.set_publish(registered, "none")
    assert stored(registered)["publish"] == {"target": "none"}


@pytest.mark.parametrize("kwargs, message", [
    ({"target": "notion"}, "--notion-parent-page-id is required for target notion"),
    ({"target": "notion", "notion_parent_page_id": "abc"}, "Invalid parent_page_id"),
    ({"target": "confluence", "confluence_space_key": "PROJ"},
     "--confluence-space-key and --confluence-parent-title are required for target confluence"),
    ({"target": "slack"}, "target must be one of"),
])
def test_invalid_settings_are_rejected_and_not_stored(registered, kwargs, message):
    with pytest.raises(ValueError, match=message):
        projects.set_publish(registered, **kwargs)
    assert "publish" not in stored(registered)


def test_unknown_project_is_rejected(registered):
    with pytest.raises(ValueError, match="unknown project_id"):
        projects.set_publish("other-svc", "none")
    with pytest.raises(ValueError, match="unknown project_id"):
        projects.show_publish("other-svc")


@pytest.mark.parametrize("publish, field", [
    ("notion", "publish"),
    ({"target": "ftp"}, "target"),
    ({"target": "notion", "notion": {"parent_page_id": "SECRET-VALUE"}}, "notion.parent_page_id"),
    ({"target": "confluence", "confluence": {"space_key": "SECRET-VALUE"}}, "confluence.parent_title"),
])
def test_damaged_record_names_field_not_value_and_keeps_resolution(registered, publish, field):
    data = json.loads(projects.REGISTRY_FILE.read_text(encoding="utf-8"))
    data["projects"][registered]["publish"] = publish
    projects.REGISTRY_FILE.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(projects.InvalidSettings) as caught:
        projects.get_publish(registered)
    assert str(caught.value) == f"Invalid publish settings: {field}"
    assert "SECRET-VALUE" not in str(caught.value)
    assert projects.resolve(registered).project_id == registered  # other flows unaffected


def test_cli_set_and_show(registered, capsys):
    assert cli.main(["project-publish-set", registered, "--target", "notion", "--notion-parent-page-id", PARENT]) == 0
    assert json.loads(capsys.readouterr().out)["publish"]["target"] == "notion"
    assert cli.main(["project-publish-show", registered]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown == {"project_id": registered,
                     "publish": {"target": "notion", "notion": {"parent_page_id": PARENT.replace("-", "").lower()}}}


def test_cli_rejects_missing_ids_with_exit_1(registered, capsys):
    assert cli.main(["project-publish-set", registered, "--target", "notion"]) == 1
    assert "--notion-parent-page-id is required" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.main(["project-publish-set", registered, "--target", "ftp"])
