"""Keep automatic collector state isolated from developers' local run history."""

import pytest


@pytest.fixture(autouse=True)
def isolated_observation_db(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_PLATFORM_STATE_DB", str(tmp_path / "state.db"))
