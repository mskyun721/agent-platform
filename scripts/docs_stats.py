#!/usr/bin/env python3
"""Read-only artifact statistics; every gate uses the same explicit root."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server" / "src"))

from agent_platform_mcp.config import resolve_project_dir  # noqa: E402
from agent_platform_mcp.tools import feature  # noqa: E402


def collect(root: Path) -> dict[str, Any]:
    project = resolve_project_dir(root)
    docs = project / "docs"
    feature._safe_path(docs, project)
    if not docs.is_dir():
        raise FileNotFoundError(f"No docs directory under {project}")
    counts: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    results: list[dict[str, Any]] = []
    for directory in sorted(docs.rglob("*")):
        if directory.is_symlink() or not directory.is_dir():
            continue
        relative = directory.relative_to(docs)
        if len(relative.parts) < 2:
            continue
        feature._safe_path(directory, project)
        children = list(directory.iterdir())
        if children and not any(p.suffix == ".md" for p in children):
            continue
        name = feature.canonical_feature(relative.as_posix())
        gate = feature.gate_check(name, root=project)
        for item in gate["files"]:
            counts[item["file"]] += 1
            statuses[str(item["status"] or "missing")] += 1
        results.append({"feature": name, "passed": gate["passed"], "files": gate["files"]})
    return {"project_dir": str(project), "items": len(results), "artifacts": dict(counts),
            "statuses": dict(statuses), "gate_pass": sum(item["passed"] for item in results),
            "gate_fail": [item["feature"] for item in results if not item["passed"]],
            "results": results, "verification_executed": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(collect(resolve_project_dir(args.root)), ensure_ascii=False, indent=2))
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, f"docs_stats: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
