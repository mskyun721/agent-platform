"""PublishMap `specs`/`index` entries and owner-marker helpers (BR-7, BR-16, AC-18)."""

from __future__ import annotations

import json

import pytest

from agent_platform_mcp.tools import notion, projects
from agent_platform_mcp.tools import spec_publish_map as pmap

PARENT = "1f2e3d4c5b6a79881726354433221100"
PAGE = "aaaaaaaabbbbccccddddeeeeeeeeeeee"


@pytest.fixture
def project(tmp_path, monkeypatch):
    base = tmp_path / "projects"
    service = base / "svc"
    service.mkdir(parents=True)
    monkeypatch.setenv("AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS", str(base))
    projects.register(str(service), "demo-svc")
    return service


def stored(project_id="demo-svc") -> dict:
    return json.loads((notion.MAP_DIR / f"{project_id}.json").read_text(encoding="utf-8"))


def test_save_and_load_spec_and_index_entries(project):
    assert pmap.save_entry("demo-svc", "payment", target="notion", page_id=PAGE, parent=PARENT) is None
    assert pmap.save_entry("demo-svc", None, target="confluence", page_id="12345", parent="100") is None
    data = stored()
    assert data["specs"]["payment"] == {"target": "notion", "page_id": PAGE, "parent": PARENT,
                                        "project_path": str(project.resolve())}
    assert data["index"]["page_id"] == "12345" and data["index"]["target"] == "confluence"
    assert pmap.load_page_id("demo-svc", "payment", target="notion", parent=PARENT) == PAGE
    assert pmap.load_page_id("demo-svc", None, target="confluence", parent="100") == "12345"


def test_entry_for_another_target_or_parent_is_not_reused(project):
    pmap.save_entry("demo-svc", "payment", target="notion", page_id=PAGE, parent=PARENT)
    assert pmap.load_page_id("demo-svc", "payment", target="confluence", parent=PARENT) is None
    assert pmap.load_page_id("demo-svc", "payment", target="notion", parent="0" * 32) is None
    assert pmap.load_page_id("demo-svc", "other", target="notion", parent=PARENT) is None


def test_feature_entries_and_spec_entries_coexist(project):
    assert notion._save_map("demo-svc", "features/demo", {"parent": PARENT, "overview": PAGE, "files": {}}) is None
    pmap.save_entry("demo-svc", "payment", target="notion", page_id=PAGE, parent=PARENT)
    assert notion._save_map("demo-svc", "features/other", {"parent": PARENT, "overview": None, "files": {}}) is None
    data = stored()
    assert set(data["features"]) == {"features/demo", "features/other"}
    assert data["specs"]["payment"]["page_id"] == PAGE


def test_damaged_page_id_in_the_map_is_ignored(project):
    pmap.save_entry("demo-svc", None, target="confluence", page_id="12345", parent="100")
    path = notion.MAP_DIR / "demo-svc.json"
    data = stored()
    data["index"]["page_id"] = "../12345"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert pmap.load_page_id("demo-svc", None, target="confluence", parent="100") is None


def test_invalid_input_is_a_warning_not_a_write(project):
    assert pmap.save_entry("demo-svc", "payment", target="confluence", page_id="abc", parent="1") == \
        "publish map not saved: invalid page id"
    assert pmap.save_entry("demo-svc", "a/b", target="confluence", page_id="1", parent="1") == \
        "publish map not saved: invalid slug"
    assert pmap.save_entry("demo-svc", "x", target="none", page_id="1", parent="1") == \
        "publish map not saved: invalid page id"
    assert not (notion.MAP_DIR / "demo-svc.json").exists()
    assert pmap.save_entry(None, "x", target="confluence", page_id="1", parent="1") is None


@pytest.mark.parametrize("bad", ["../escape", "Bad ID", "a", "x/y", 7])
def test_project_id_is_validated_before_any_path_is_built(project, bad):
    """Security L-3: the id becomes `.local/publish/<project_id>.json`."""
    assert pmap.save_entry(bad, "payment", target="notion", page_id=PAGE, parent=PARENT) == \
        "publish map not saved: invalid project id"
    assert pmap.load_entry(bad, "payment", target="notion", parent=PARENT) is None
    assert not notion.MAP_DIR.exists() or list(notion.MAP_DIR.iterdir()) == []
    assert not (notion.MAP_DIR.parent / "escape.json").exists()


def test_publish_dir_is_private(project):
    pmap.save_entry("demo-svc", "payment", target="notion", page_id=PAGE, parent=PARENT)
    assert notion.MAP_DIR.stat().st_mode & 0o777 == 0o700


def test_pending_marker_entry_is_recorded_and_cleared(project):
    pmap.save_entry("demo-svc", "payment", target="confluence", page_id="42", parent="100", pending_marker=True)
    assert stored()["specs"]["payment"]["pending_marker"] is True
    assert pmap.pending_marker_page("demo-svc", "payment", target="confluence", parent="100") == "42"
    assert pmap.pending_marker_page("demo-svc", "payment", target="confluence", parent="101") is None
    pmap.save_entry("demo-svc", "payment", target="confluence", page_id="42", parent="100")
    assert "pending_marker" not in stored()["specs"]["payment"]
    assert pmap.pending_marker_page("demo-svc", "payment", target="confluence", parent="100") is None


def test_lock_timeout_is_a_warning(project, monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def busy(_path):
        raise TimeoutError("publish map is busy")
        yield

    monkeypatch.setattr(notion, "_map_lock", busy)
    assert pmap.save_entry("demo-svc", "payment", target="notion", page_id=PAGE, parent=PARENT) == \
        "publish map not saved: TimeoutError"


def test_project_path_is_the_registered_path_not_the_caller_path(project, tmp_path):
    # Whatever root the caller resolved (default, explicit, worktree), the map records the registry path.
    assert pmap.registered_path("demo-svc") == str(project.resolve())
    assert pmap.registered_path("unknown-id") is None
    assert pmap.registered_path(None) is None


def test_rebind_keeps_the_mapping(project, tmp_path):
    pmap.save_entry("demo-svc", "payment", target="notion", page_id=PAGE, parent=PARENT)
    moved = project.parent / "svc-moved"
    project.rename(moved)
    projects.rebind("demo-svc", str(moved))
    assert pmap.load_page_id("demo-svc", "payment", target="notion", parent=PARENT) == PAGE


# --- owner marker ---------------------------------------------------------------

def test_owner_marker_validation_names_the_field_only():
    assert pmap.owner_marker("demo-svc", "payment") == {"project_id": "demo-svc", "slug": "payment"}
    assert pmap.owner_marker("demo-svc", pmap.INDEX_SLUG)["slug"] == "INDEX"
    with pytest.raises(ValueError, match="^invalid owner project_id$"):
        pmap.owner_marker("Bad ID secret", "x")
    with pytest.raises(ValueError, match="^invalid owner slug$"):
        pmap.owner_marker("demo-svc", "../x")


def test_owner_matching_and_notion_marker_round_trip():
    owner = pmap.owner_marker("demo-svc", "payment")
    assert pmap.owner_matches({"project_id": "demo-svc", "slug": "payment", "extra": 1}, owner)
    assert not pmap.owner_matches({"project_id": "old-id", "slug": "payment"}, owner)
    assert pmap.owner_matches({"project_id": "old-id", "slug": "payment"}, owner, lambda found: True)
    assert not pmap.owner_matches("demo-svc/payment", owner, lambda found: True)
    with pytest.raises(pmap.AcceptOwnerError):
        pmap.owner_matches({"project_id": "old-id", "slug": "payment"}, owner, lambda found: found["missing"])
    assert pmap.map_slug(owner) == "payment" and pmap.map_slug(pmap.owner_marker("demo-svc", "INDEX")) is None
    assert pmap.title_conflict("T", "1")["error"] == "page 'T' exists and is not owned by agent-platform"
    text = pmap.notion_marker_text(owner)
    assert text == "agent-platform:demo-svc/payment"
    assert pmap.parse_notion_marker(text) == owner
    assert pmap.parse_notion_marker("agent-platform:demo-svc") is None
    assert pmap.parse_notion_marker("hello") is None


@pytest.mark.parametrize("value, expected", [("123", "123"), (123, "123"), ("0", None), ("12a", None),
                                             ("1/2", None), (True, None), (None, None), ("1" * 21, None)])
def test_confluence_page_id_format(value, expected):
    assert pmap.valid_confluence_page_id(value) == expected
