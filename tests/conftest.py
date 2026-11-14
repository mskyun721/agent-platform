"""Keep automatic collector state isolated from developers' local run history."""

import pytest

_PUBLISH_ENV = ("NOTION_TOKEN", "CONFLUENCE_URL", "CONFLUENCE_EMAIL", "CONFLUENCE_API_TOKEN")


@pytest.fixture(autouse=True)
def isolated_observation_db(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_PLATFORM_STATE_DB", str(tmp_path / "state.db"))


@pytest.fixture(autouse=True)
def isolated_publish(tmp_path, monkeypatch):
    """Never read a developer's real project registry, publish map or remote tokens
    (config loads ROOT/.env at import), so no test can publish for real. Tests that
    need any of these patch them again themselves (patch.dict / patch.object win)."""
    from agent_platform_mcp.tools import notion, projects

    monkeypatch.setattr(projects, "REGISTRY_FILE", tmp_path / ".agent-projects.json")
    monkeypatch.setattr(notion, "MAP_DIR", tmp_path / ".local" / "publish")
    for name in _PUBLISH_ENV:
        monkeypatch.delenv(name, raising=False)
