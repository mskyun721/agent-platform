"""Test isolation: no test may read, write or delete the real checkout's local files.

Every test runs against a temporary platform ROOT (`config.ROOT`): one session copy
of the checkout's git-tracked files, with the local state wiped around each test. The
local, ignored state (`.active-project*`, `.agent-projects.json/.lock`, `.local/`,
`.env*`) is never linked, so legacy-pointer, registry and state-db code paths land in
the temporary ROOT; `AGENT_PLATFORM_ROOT` points spawned CLIs there too. A session
guard hashes the real files and fails the run if any of them changed; a per-test stat
check names the offending test. The 0600 recovery copies are removed unless it fails.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REAL_ROOT / "mcp-server/src"))
sys.path.insert(0, str(REAL_ROOT / "scripts"))

_PUBLISH_ENV = ("NOTION_TOKEN", "CONFLUENCE_URL", "CONFLUENCE_EMAIL", "CONFLUENCE_API_TOKEN")
# Never mirrored into the temporary ROOT, whether tracked or not.
_LOCAL_NAMES = (".active-project", ".agent-projects.json", ".agent-projects.lock", ".local", ".env")
_LIVE_DB_SUFFIXES = (".db", ".db-wal", ".db-shm", ".db-journal")  # written by live sessions too
# Exact runtime files the user's own processes write while tests run (never globbed): the
# collect hook's lock (empty or a one-byte rerun flag) and the log of a user-started `observe serve`.
_LIVE_FILES = (Path(".local/native-collect.lock"), Path(".local/observe-serve.log"))


def _is_local(name: str) -> bool:
    return any(name == local or name.startswith(local + ".") for local in _LOCAL_NAMES)


def _protected_files() -> list[Path]:
    found = [REAL_ROOT / name for name in (".active-project", ".agent-projects.json", ".agent-projects.lock")]
    found += sorted(REAL_ROOT.glob(".active-project.migrated*"))
    local = REAL_ROOT / ".local"
    if local.is_dir():
        live = {REAL_ROOT / path for path in _LIVE_FILES}
        found += sorted(path for path in local.rglob("*") if path.is_file() and path not in live)
    return found


def _fingerprint(path: Path) -> str | None:
    if not path.exists():
        return None
    if path.name.endswith(_LIVE_DB_SUFFIXES):  # a running MCP/observer may write these: existence only
        return "present"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot() -> dict[str, str | None]:
    return {str(path): _fingerprint(path) for path in _protected_files()}


def _stat_snapshot() -> dict[str, tuple[int, int] | None]:
    paths = [REAL_ROOT / name for name in (".active-project", ".agent-projects.json", ".agent-projects.lock")]
    paths += sorted(REAL_ROOT.glob(".active-project.migrated*"))
    result: dict[str, tuple[int, int] | None] = {}
    for path in paths:
        try:
            stat = path.stat()
            result[str(path)] = (stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            result[str(path)] = None
    return result


def _diff(before: dict, after: dict) -> list[str]:
    return sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))


_SESSION: dict[str, object] = {}


def pytest_sessionstart(session):
    _SESSION["snapshot"] = _snapshot()
    keep = Path(tempfile.mkdtemp(prefix="agent-platform-real-root-"))  # 0700
    for name in (".active-project", ".agent-projects.json"):  # recovery copies, never read by tests
        source = REAL_ROOT / name
        if source.is_file():
            descriptor = os.open(keep / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(source.read_bytes())
    _SESSION["backup"] = keep


def pytest_sessionfinish(session, exitstatus):
    changed = _diff(_SESSION.get("snapshot", {}), _snapshot())
    backup = _SESSION.get("backup")
    if changed:  # keep the recovery copies only when they may be needed
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        print("\nFAILED test isolation: the real checkout's local files changed during the run:\n  "
              + "\n  ".join(changed)
              + f"\nPre-run copies of .active-project/.agent-projects.json: {backup}",
              file=sys.stderr)
    elif isinstance(backup, Path):
        shutil.rmtree(backup, ignore_errors=True)


def _copy_tracked(destination: Path) -> None:
    """Copy (never link) the tracked files: storage guards reject symlinked paths."""
    listed = subprocess.run(["git", "-C", str(REAL_ROOT), "ls-files", "-z"], capture_output=True, timeout=30, check=True)
    for entry in listed.stdout.decode("utf-8", "replace").split("\0"):
        if not entry or _is_local(entry.split("/", 1)[0]):
            continue
        source = REAL_ROOT / entry
        if not (source.is_file() or source.is_symlink()):
            continue  # deleted in the working tree
        target = destination / entry
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target, follow_symlinks=False)


@pytest.fixture(scope="session")
def _platform_copy(tmp_path_factory) -> Path:
    root = (tmp_path_factory.mktemp("platform") / "agent-platform").resolve()
    root.mkdir()
    _copy_tracked(root)
    return root


def _clear_local_state(root: Path) -> None:
    for path in root.iterdir():
        if _is_local(path.name):
            shutil.rmtree(path) if path.is_dir() and not path.is_symlink() else path.unlink()


@pytest.fixture(autouse=True)
def isolated_platform_root(_platform_copy, monkeypatch):
    """Point config.ROOT (and the paths derived from it at import) at a copy of the checkout."""
    from agent_platform_mcp import config
    from agent_platform_mcp.tools import notion, projects

    root = _platform_copy
    _clear_local_state(root)
    monkeypatch.setattr(config, "ROOT", root)
    monkeypatch.setattr(projects, "REGISTRY_FILE", root / ".agent-projects.json")
    monkeypatch.setattr(notion, "MAP_DIR", root / ".local" / "publish")
    monkeypatch.setattr(config, "_WARNED", set())
    monkeypatch.setenv("AGENT_PLATFORM_STATE_DB", str(root / ".local" / "state.db"))
    monkeypatch.setenv("AGENT_PLATFORM_ROOT", str(root))  # subprocess CLIs use the copy too (REVIEW M-3)
    monkeypatch.delenv("TARGET_PROJECT_ROOT", raising=False)
    for name in _PUBLISH_ENV:  # config loads ROOT/.env at import: no test may publish for real
        monkeypatch.delenv(name, raising=False)
    for name in list(os.environ):  # host detection (observation.host_backend) must not follow the CLI running pytest
        if name == "CLAUDECODE" or name.startswith(("CLAUDE_CODE_", "CODEX_")) and name != "CODEX_HOME":
            monkeypatch.delenv(name, raising=False)
    before = _stat_snapshot()
    yield root
    _clear_local_state(root)
    changed = _diff(before, _stat_snapshot())
    if changed:
        pytest.fail(f"test touched the real checkout's local files: {changed}", pytrace=False)
