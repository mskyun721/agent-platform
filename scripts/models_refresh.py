#!/usr/bin/env python3
"""Propose the latest model per tier from the locally installed CLI catalogs.

Reads `codex debug models` (JSON catalog) and the `model` list of `copilot help config`; Claude and
Gemini use aliases that already track the latest model, so only their CLI presence is reported.
No AI call, no network request of its own. Reports by default; `--write` updates only the
`model_tiers` entries that have a proposal. A missing or failing CLI is reported as unavailable.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

TIERS = ("high", "mid", "low")
ALIASES = {"claude": {"high": "opus", "mid": "sonnet", "low": "haiku"},
           "gemini": {"high": "pro", "mid": "flash", "low": "flash-lite"}}
COPILOT_FAMILIES = {"high": "claude-opus", "mid": "claude-sonnet", "low": "claude-haiku"}
_FAST = re.compile(r"\b(fast|affordable|easier|simpler|mini|lite)\b", re.I)


def run(argv: list[str], timeout: int = 30) -> str | None:
    """stdout of a fixed argv (never a shell); None when the CLI is missing, fails or times out."""
    if shutil.which(argv[0]) is None:
        return None
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def copilot_ids(text: str) -> list[str]:
    """Quoted IDs under the `model` key of `copilot help config`, in listed order."""
    ids, inside = [], False
    for line in text.splitlines():
        if re.match(r"^\s*`model`:", line):
            inside = True
            continue
        if inside:
            found = re.match(r'^\s*-\s*"([A-Za-z0-9._:-]+)"\s*$', line)
            if not found:
                break
            ids.append(found.group(1))
    return ids


def _version(model_id: str, family: str) -> tuple[int, ...] | None:
    found = re.fullmatch(re.escape(family) + r"-(\d+(?:\.\d+)*)", model_id)  # skips -fast variants
    return tuple(int(part) for part in found.group(1).split(".")) if found else None


def propose_copilot(ids: list[str]) -> dict[str, str]:
    proposal = {}
    for tier, family in COPILOT_FAMILIES.items():
        versions = [(v, i) for i in ids if (v := _version(i, family))]
        if versions:
            proposal[tier] = max(versions)[1]
    return proposal


def propose_codex(text: str) -> tuple[dict[str, str], list[str]]:
    """high = top-priority listed non-legacy general model, mid = the next one (else high), low = the
    top-priority fast one. Descriptions are heuristics, so the result is a proposal, never a pin."""
    models = json.loads(text).get("models", [])
    listed = sorted((m for m in models if isinstance(m, dict) and m.get("visibility") == "list"
                     and isinstance(m.get("slug"), str)), key=lambda m: m.get("priority", 1 << 30))
    current = [m for m in listed if not str(m.get("description", "")).lower().startswith("legacy")]
    general = [m["slug"] for m in current if not _FAST.search(str(m.get("description", "")))]
    fast = [m["slug"] for m in current if m["slug"] not in general]
    proposal = {}
    if general:
        proposal["high"] = general[0]
        proposal["mid"] = general[1] if len(general) > 1 else general[0]
    if fast:
        proposal["low"] = fast[0]
    return proposal, [m["slug"] for m in listed]


def report(config: dict, runner=run) -> dict:
    tiers = config.get("model_tiers") or {}
    result: dict = {"warnings": [], "backends": {}}
    for backend, argv in (("claude", ["claude", "--version"]), ("gemini", ["gemini", "--version"])):
        version = runner(argv)
        result["backends"][backend] = {"status": "unavailable" if version is None else "alias",
                                       "version": (version or "").strip() or None, "proposal": ALIASES[backend]}
    help_text = runner(["copilot", "help", "config"])
    ids = copilot_ids(help_text or "")
    result["backends"]["copilot"] = {"status": "ok" if ids else "unavailable", "proposal": propose_copilot(ids),
                                     "catalog": ids, "version": (runner(["copilot", "--version"]) or "").strip()
                                     .splitlines()[0] if ids else None}
    catalog = runner(["codex", "debug", "models"])
    try:
        proposal, slugs = propose_codex(catalog) if catalog else ({}, [])
        status = "ok" if catalog else "unavailable"
    except (ValueError, AttributeError):
        proposal, slugs, status = {}, [], "unavailable"
    result["backends"]["codex"] = {"status": status, "proposal": proposal, "catalog": slugs,
                                   "version": (runner(["codex", "--version"]) or "").strip() or None}
    for backend, info in result["backends"].items():
        for tier in TIERS:
            configured = (tiers.get(tier) or {}).get(backend)
            proposed = info["proposal"].get(tier)
            if info["status"] == "unavailable" or configured is None or configured == proposed:
                continue
            if backend in ALIASES:
                result["warnings"].append(f"{backend} {tier}: pinned {configured}; alias {proposed} tracks the latest")
            elif configured not in info["catalog"]:
                result["warnings"].append(f"{backend} {tier}: {configured} is not in the local catalog")
            elif proposed:
                result["warnings"].append(f"{backend} {tier}: {configured} is not the latest ({proposed})")
    latest = result["backends"]["copilot"]["proposal"]
    for role, pinned in ((config.get("host_models") or {}).get("copilot") or {}).items():
        for tier, family in COPILOT_FAMILIES.items():
            if _version(str(pinned), family) and latest.get(tier) not in (None, pinned):
                result["warnings"].append(f"host_models.copilot.{role}: {pinned} is not the latest ({latest[tier]})")
    return result


def apply(config: dict, result: dict) -> list[str]:
    """Write proposals for copilot/codex into config['model_tiers']; aliases are left as configured."""
    tiers, changed = config.setdefault("model_tiers", {}), []
    for backend in ("copilot", "codex"):
        for tier, model in result["backends"][backend]["proposal"].items():
            if tiers.setdefault(tier, {}).get(backend) != model:
                tiers[tier][backend] = model
                changed.append(f"{tier}.{backend}={model}")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--write", action="store_true", help="apply copilot/codex proposals to model_tiers")
    args = parser.parse_args()
    path = args.repo_root / ".agent-config.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    result = report(config)
    for backend, info in result["backends"].items():
        configured = {t: (config.get("model_tiers", {}).get(t) or {}).get(backend) for t in TIERS}
        print(f"{backend}: {info['status']}" + (f" ({info['version']})" if info.get("version") else ""))
        for tier in TIERS:
            print(f"  {tier}: configured={configured[tier] or '(CLI default)'} proposed={info['proposal'].get(tier) or '-'}")
        if backend == "codex" and info["catalog"]:
            print("  listed catalog: " + ", ".join(info["catalog"]))
    for warning in result["warnings"]:
        print(f"warn: {warning}")
    if args.write:
        changed = apply(config, result)
        if changed:
            path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("written: " + ", ".join(changed) if changed else "written: nothing to change")
    else:
        print("report only; rerun with --write to apply copilot/codex proposals, then scripts/sync_hosts.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
