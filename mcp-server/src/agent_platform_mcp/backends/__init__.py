"""CLI backend registry; adapters load lazily so config.py can import NAMES without cycles."""
import importlib
import shutil
import subprocess

NAMES = ("claude", "codex", "gemini", "copilot")


def get(name):
    if name not in NAMES:
        raise ValueError(f"unknown backend: {name!r}; expected one of {list(NAMES)}")
    return importlib.import_module(f"agent_platform_mcp.backends.{name}")


def installed(name):
    get(name)
    return shutil.which(name) is not None


def version(name):
    executable = shutil.which(get(name).name)
    if not executable:
        return None
    try:
        result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip().splitlines()[0][:100] if result.returncode == 0 and result.stdout.strip() else None
