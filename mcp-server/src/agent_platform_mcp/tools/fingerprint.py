"""Content evidence for the requested workspace; protected files are never read."""

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

IGNORED_DIRS = {".git", ".local", "docs", "__pycache__", ".pytest_cache", ".venv", "node_modules", ".mypy_cache"}
LOCAL_FILES = {".active-project", ".agent-projects.json", ".agent-projects.lock"}


def excluded(path: str) -> bool:
    parts = Path(path).parts
    return (any(part in IGNORED_DIRS for part in parts) or path.startswith("evals/results/") or
            Path(path).name in LOCAL_FILES or any(any(word in part.lower() for word in
            (".env", ".pem", ".key", "credential", "secret")) for part in parts))


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def code_fingerprint(project_dir: Path) -> dict:
    project_dir = Path(project_dir).absolute()
    if not project_dir.is_dir() or any(path.is_symlink() for path in (project_dir, *project_dir.parents)):
        raise ValueError("fingerprint requires a real workspace directory")
    def git(*args):
        return subprocess.run(["git", *args], cwd=project_dir, capture_output=True, timeout=10, check=False)
    listed = git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    head = None
    tracked = set()
    omitted = []
    if listed.returncode == 0:
        paths = set(os.fsdecode(value) for value in listed.stdout.split(b"\0") if value)
        tracking = git("ls-files", "--cached", "-z")
        if tracking.returncode:
            raise ValueError("cannot determine tracked evidence inputs")
        tracked = {os.fsdecode(value) for value in tracking.stdout.split(b"\0") if value}
        revision = git("rev-parse", "HEAD")
        head = revision.stdout.decode().strip() if revision.returncode == 0 else None
    else:
        if (project_dir / ".git").exists():
            raise ValueError("cannot inspect Git workspace")
        paths = set()
        for directory, dirs, files in os.walk(project_dir, followlinks=False):
            base = Path(directory).relative_to(project_dir)
            for name in list(dirs):
                relative = (base / name).as_posix()
                if excluded(relative):
                    dirs.remove(name)
                    omitted.append(relative + "/")
                elif (Path(directory) / name).is_symlink():
                    raise ValueError("code directory symlink cannot be fingerprinted")
            paths.update((base / name).as_posix() for name in files)
    manifest = {}
    state_db = Path(os.environ.get("AGENT_PLATFORM_STATE_DB", project_dir / ".local/state.db")).absolute()
    for relative in sorted(paths):
        if excluded(relative) or str(project_dir / relative) in {str(state_db) + suffix for suffix in ("", "-journal", "-wal", "-shm")}:
            omitted.append(relative)
            continue
        path = project_dir / relative
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("invalid evidence path")
        if any(node.is_symlink() for node in (path, *path.parents)):
            raise ValueError("code symlink cannot be fingerprinted")
        if not path.exists():
            manifest[relative] = {"deleted": True}
            continue
        mode = path.stat().st_mode
        if not stat.S_ISREG(mode):
            raise ValueError("code input must be a regular file")
        if path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("code input exceeds 64 MiB")
        manifest[relative] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "executable": mode & 0o111}
    return {"head": head, "tracked_diff": _hash({key: value for key, value in manifest.items() if key in tracked}),
            "untracked": _hash({key: value for key, value in manifest.items() if key not in tracked}),
            "fingerprint": _hash(manifest), "files": manifest, "excluded": sorted(set(omitted))}
