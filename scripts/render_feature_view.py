#!/usr/bin/env python3
"""Render a feature's REVIEW-VIEW.html (layout B: review requests → flow · API → full docs).

  python3 scripts/render_feature_view.py --root <project-or-id> --feature features/<name>

The page is derived from PRD.md, API-SPEC.md and FLOW.drawio and is kept out of git
(`docs/**/REVIEW-VIEW.html` is appended to the target .gitignore unless --no-gitignore).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_VENV_PYTHON = _REPO / "mcp-server" / ".venv" / "bin" / "python"
# The platform package needs its own dependencies (python-dotenv, httpx); re-run under the
# mcp-server venv when it exists and this is not already that interpreter.
if _VENV_PYTHON.is_file() and Path(sys.prefix).resolve() != _VENV_PYTHON.parents[1].resolve() and not os.environ.get("APA_NO_REEXEC"):
    os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON), __file__, *sys.argv[1:]])

sys.path.insert(0, str(_REPO / "mcp-server" / "src"))

from agent_platform_mcp.tools.feature_view import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
