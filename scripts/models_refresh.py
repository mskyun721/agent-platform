#!/usr/bin/env python3
"""Propose the latest model per tier from the locally installed CLI catalogs.

Reads `codex debug models` (JSON catalog) and the `model` list of `copilot help config`; Claude and
Gemini use aliases that the installed CLI version resolves through its own model table (they move
when the CLI is updated), so only their CLI presence is reported. Gemini `auto` is the CLI's own
default routing (0.70.0: `-m auto` equals no `-m`). No AI call, no network request of its own.
Reports by default; `--write --backend copilot|codex [--tier T]` updates only the chosen
`model_tiers` entries. A missing CLI is `unavailable`; a partial failure or an odd catalog is `error`.
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
           "gemini": {"high": "auto", "mid": "auto", "low": "flash-lite"}}
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
    listed = [m for m in models if isinstance(m, dict) and m.get("visibility") == "list" and isinstance(m.get("slug"), str)]
    if any(type(m.get("priority", 0)) is not int for m in listed):
        raise ValueError("codex catalog priority must be an integer")
    listed.sort(key=lambda m: m.get("priority", 1 << 30))
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


def _first_line(text: str | None) -> str | None:
    return next(iter((text or "").strip().splitlines()), None)


def _copilot(runner) -> dict:
    ids = copilot_ids(runner(["copilot", "help", "config"]) or "")
    if not ids:
        return {"status": "unavailable", "proposal": {}, "catalog": [], "version": None}
    version = _first_line(runner(["copilot", "--version"]))
    info = {"status": "ok", "proposal": propose_copilot(ids), "catalog": ids, "version": version}
    return info if version else info | {"status": "error", "error": "version check failed"}


def _codex(runner) -> dict:
    catalog = runner(["codex", "debug", "models"])
    if not catalog:
        return {"status": "unavailable", "proposal": {}, "catalog": [], "version": None}
    try:
        proposal, slugs = propose_codex(catalog)
    except (ValueError, AttributeError, TypeError) as error:
        return {"status": "error", "error": f"catalog: {type(error).__name__}", "proposal": {}, "catalog": [],
                "version": None}
    return {"status": "ok", "proposal": proposal, "catalog": slugs, "version": _first_line(runner(["codex", "--version"]))}


def report(config: dict, runner=run) -> dict:
    tiers = config.get("model_tiers") or {}
    result: dict = {"warnings": [], "backends": {}}
    for backend, argv in (("claude", ["claude", "--version"]), ("gemini", ["gemini", "--version"])):
        version = runner(argv)
        result["backends"][backend] = {"status": "unavailable" if version is None else "alias",
                                       "version": _first_line(version), "proposal": ALIASES[backend]}
    for backend, probe in (("copilot", _copilot), ("codex", _codex)):
        try:
            result["backends"][backend] = probe(runner)
        except Exception as error:  # one broken CLI never stops the report of the others
            result["backends"][backend] = {"status": "error", "error": type(error).__name__, "proposal": {},
                                           "catalog": [], "version": None}
    for backend, info in result["backends"].items():
        for tier in TIERS:
            configured = (tiers.get(tier) or {}).get(backend)
            proposed = info["proposal"].get(tier)
            if info["status"] in ("unavailable", "error") or configured is None or configured == proposed:
                continue
            if backend in ALIASES:
                result["warnings"].append(f"{backend} {tier}: pinned {configured}; alias {proposed} follows the installed CLI")
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


def apply(config: dict, result: dict, backend: str, tier: str | None = None) -> list[str]:
    """Write one backend's proposals (optionally one tier) into config['model_tiers']; aliases stay as configured.

    Only a backend whose probe is `ok` is written; others raise so nothing half-checked lands."""
    if backend not in ("copilot", "codex"):
        raise ValueError("--backend must be copilot or codex")
    info = result["backends"][backend]
    if info["status"] != "ok":
        raise ValueError(f"{backend} is {info['status']}; nothing written")
    tiers, changed = config.setdefault("model_tiers", {}), []
    for name, model in info["proposal"].items():
        if tier is None or name == tier:
            if tiers.setdefault(name, {}).get(backend) != model:
                tiers[name][backend] = model
                changed.append(f"{name}.{backend}={model}")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--write", action="store_true", help="apply the proposals of --backend (and --tier) to model_tiers")
    parser.add_argument("--backend", choices=("copilot", "codex"), help="with --write: the one backend to apply")
    parser.add_argument("--tier", choices=TIERS, help="with --write: only this tier")
    args = parser.parse_args()
    if args.write and not args.backend:
        parser.error("--write needs --backend copilot|codex (review the report first)")
    path = args.repo_root / ".agent-config.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    result = report(config)
    for backend, info in result["backends"].items():
        configured = {t: (config.get("model_tiers", {}).get(t) or {}).get(backend) for t in TIERS}
        print(f"{backend}: {info['status']}" + (f" ({info['version']})" if info.get("version") else "")
              + (f" - {info['error']}" if info.get("error") else ""))
        for tier in TIERS:
            print(f"  {tier}: configured={configured[tier] or '(CLI default)'} proposed={info['proposal'].get(tier) or '-'}")
        if backend == "codex" and info["catalog"]:
            print("  listed catalog: " + ", ".join(info["catalog"]))
    for warning in result["warnings"]:
        print(f"warn: {warning}")
    if args.write:
        try:
            changed = apply(config, result, args.backend, args.tier)
        except ValueError as error:
            print(f"not written: {error}")
            return 1
        if changed:
            path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("written: " + ", ".join(changed) if changed else "written: nothing to change")
    else:
        print("report only; apply with --write --backend copilot|codex [--tier high|mid|low], then scripts/sync_hosts.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
