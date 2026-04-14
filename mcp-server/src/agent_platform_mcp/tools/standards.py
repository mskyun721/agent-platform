"""Read-only access to standards/ and workflows/ documents."""

from __future__ import annotations

import re
from typing import Any

from agent_platform_mcp.config import ROOT

STANDARDS_DIR = ROOT / "standards"
WORKFLOWS_DIR = ROOT / "workflows"
TEMPLATES_DIR = ROOT / "templates"

SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]*$")
ALLOWED_BASES = {
    "standards": STANDARDS_DIR,
    "workflows": WORKFLOWS_DIR,
    "templates": TEMPLATES_DIR,
}


def read(kind: str, name: str) -> dict[str, Any]:
    """Return content of a standards/workflows/templates document.

    Args:
        kind: one of {standards, workflows, templates}
        name: file stem (without extension) — e.g. "coding-style"
    """
    if kind not in ALLOWED_BASES:
        raise ValueError(f"kind must be one of {sorted(ALLOWED_BASES)}")
    if not SAFE_NAME_RE.match(name):
        raise ValueError("name contains unsafe characters")

    base = ALLOWED_BASES[kind]
    path = (base / f"{name}.md").resolve()
    if base.resolve() not in path.parents and path.parent != base.resolve():
        raise PermissionError("resolved path escapes the allowed base directory")
    if not path.is_file():
        raise FileNotFoundError(f"{kind}/{name}.md not found")

    content = path.read_text(encoding="utf-8")
    return {
        "kind": kind,
        "name": name,
        "path": str(path),
        "bytes": len(content.encode("utf-8")),
        "content": content,
    }


def list_available() -> dict[str, list[str]]:
    """List files available under each allowed base."""
    out: dict[str, list[str]] = {}
    for kind, base in ALLOWED_BASES.items():
        if base.is_dir():
            out[kind] = sorted(p.stem for p in base.glob("*.md"))
        else:
            out[kind] = []
    return out
