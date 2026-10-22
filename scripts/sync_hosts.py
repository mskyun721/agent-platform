#!/usr/bin/env python3
"""Generate Gemini and Copilot host adapters from canonical platform sources.

Sources: standards/agents/<role>.md, .claude/commands/<cmd>.md, .mcp.json, .agent-config.json.
Claude adapters stay owned by sync_claude_settings.py. Copilot loads AGENTS.md and .mcp.json natively.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from sync_claude_settings import AGENTS_DIR, ROLES, _FM, _safe_role_file, canonical_body

MARK = "generated from {src}; edit the source, then run scripts/sync_hosts.py"
_DESC = re.compile(r"^description:[ \t]*(.+?)[ \t]*$", re.M)
_TOOLS = re.compile(r"^tools:[ \t]*(.+?)[ \t]*$", re.M)
# Claude tool name -> Copilot custom agent tool alias.
COPILOT_TOOLS = {"Read": "read", "Write": "edit", "Edit": "edit", "Glob": "search", "Grep": "search",
                 "Bash": "execute", "WebSearch": "web", "WebFetch": "web", "Agent": "agent",
                 "TaskCreate": "todo", "TaskUpdate": "todo", "TaskList": "todo"}


def _front(text: str) -> tuple[str, str]:
    header = _FM.match(text)
    if not header:
        return "", text
    found = _DESC.search(header.group(0))
    return (found.group(1).strip().strip('"') if found else ""), text[header.end():]


def copilot_tools(line: str) -> list[str]:
    """Translate a Claude adapter tools line so Copilot agents keep the same restrictions."""
    result: list[str] = []
    for tool in (part.strip() for part in line.split(",") if part.strip()):
        if tool.startswith("mcp__agent-platform__"):
            alias = "agent-platform/" + tool.removeprefix("mcp__agent-platform__")
        elif tool in COPILOT_TOOLS:
            alias = COPILOT_TOOLS[tool]
        else:
            raise ValueError(f"no Copilot tool mapping for {tool!r}")
        if alias not in result:
            result.append(alias)
    return result


def _toml_string(value: str) -> str:
    if "'''" in value:
        raise ValueError("command body cannot contain '''")
    return "'''\n" + value + "'''"


def render(repo: Path) -> dict[Path, str]:
    repo = repo.resolve()
    files: dict[Path, str] = {}
    files[Path("GEMINI.md")] = f"<!-- {MARK.format(src='AGENTS.md')} -->\n@AGENTS.md\n"
    server = json.loads(_safe_role_file(repo, Path(".mcp.json")).read_text(encoding="utf-8"))["mcpServers"]["agent-platform"]
    if server.get("env"):
        raise ValueError("refusing to copy MCP env values into host settings")
    gemini_server = {k: v for k, v in server.items() if k not in ("type", "env")}
    files[Path(".gemini/settings.json")] = json.dumps(
        {"contextFileName": ["GEMINI.md"], "mcpServers": {"agent-platform": gemini_server}},
        ensure_ascii=False, indent=2) + "\n"
    for source in sorted(_safe_role_file(repo, Path(".claude/commands")).glob("*.md")):
        description, body = _front(source.read_text(encoding="utf-8"))
        rel = f".claude/commands/{source.name}"
        files[Path(".gemini/commands") / (source.stem + ".toml")] = (
            f"# {MARK.format(src=rel)}\n"
            f"description = {json.dumps(description, ensure_ascii=False)}\n"
            f"prompt = {_toml_string(body.strip().replace('$ARGUMENTS', '{{args}}') + chr(10))}\n")
    config = json.loads(_safe_role_file(repo, Path(".agent-config.json")).read_text(encoding="utf-8"))
    copilot_models = (config.get("host_models") or {}).get("copilot") or {}
    for role in ROLES:
        if not _safe_role_file(repo, Path("standards/agents") / f"{role}.md").exists():
            continue
        adapter = _safe_role_file(repo, AGENTS_DIR / f"{role}.md").read_text(encoding="utf-8")
        description, _ = _front(adapter)
        header = [f"name: {role}", f"description: {json.dumps(description, ensure_ascii=False)}"]
        front = _FM.match(adapter)
        tools = _TOOLS.search(front.group(0)) if front else None
        if tools:
            header.append(f"tools: {json.dumps(copilot_tools(tools.group(1)))}")
        if copilot_models.get(role):
            header.append(f"model: {copilot_models[role]}")
        files[Path(".github/agents") / f"{role}.agent.md"] = (
            "---\n" + "\n".join(header) + "\n---\n"
            f"<!-- {MARK.format(src=f'standards/agents/{role}.md')} -->\n" + canonical_body(repo, role))
    return files


def sync_all(repo: Path, *, check: bool) -> list[str]:
    repo = repo.resolve()
    pending = []
    for rel, content in render(repo).items():
        path = _safe_role_file(repo, rel)
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            pending.append((rel, path, content))
    if not check:
        for _, path, content in pending:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    return sorted(str(rel) for rel, _, _ in pending)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    changed = sync_all(args.repo_root, check=args.check)
    if not args.quiet:
        print(("drift: " if args.check else "synced: ") + ", ".join(changed) if changed else "up to date")
    return 1 if args.check and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
