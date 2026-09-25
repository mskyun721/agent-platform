"""Quant Report report wrapper."""

from pathlib import Path
from typing import Any

from agent_platform_mcp.tools.investment import run_report


def run(feature: str, requirements: str, as_of: str, cli: str = "auto", dry_run: bool = False,
        timeout_sec: int = 600, root: str | Path | None = None) -> dict[str, Any]:
    """Write a draft report without trading or product-code changes."""
    return run_report("quant", feature, requirements, as_of, cli, dry_run, timeout_sec, root)
