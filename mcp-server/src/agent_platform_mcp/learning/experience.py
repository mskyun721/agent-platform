"""Evidence-backed experience library (harness2 R): project/role lessons read before work.

Entries are draft until explicitly approved; only approved entries reach INDEX.md.
Files live in the target project (docs/experience/<role>/) so they are reviewable in Git.
"""
import datetime
import re
from pathlib import Path

from agent_platform_mcp import config, frontmatter
from agent_platform_mcp.tools.stdout_artifacts import _mask

FIELDS = {"cue", "lesson", "evidence_note", "evidence", "source_handoff"}
MAX_BYTES = 4096
MAX_APPROVED = 30
_STEM = re.compile(r"[a-z0-9-]+__[a-z0-9-]+__\d+")
_SECTION = re.compile(r"^## (Cue|Lesson|Evidence)\n(.*?)(?=^## |\Z)", re.M | re.S)
_FORBIDDEN_LINE = re.compile(r"^(#{1,6} |---)", re.M)


def _project(root):
    if not root:
        raise ValueError("explicit project root required")
    return config.resolve_project(root).path


def library(project, role):
    from agent_platform_mcp.tools.feature import _safe_path
    if role not in config.VALID_AGENTS:
        raise ValueError(f"unknown role: {role}")
    path = Path(project) / "docs" / "experience" / role
    _safe_path(path, Path(project))
    return path


def _work(feature):
    from agent_platform_mcp.tools.feature import canonical_feature
    kind, _, name = canonical_feature(feature).rpartition("/")
    return kind or "features", name


def _plain_lines(value):
    """Only \n may break lines: other separators (\r, \u2028, ...) re-split on read and forge sections."""
    return value.splitlines() == value.split("\n") and not any(
        ord(char) < 32 and char not in "\n\t" for char in value)


def _text(key, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} requires non-empty text")
    value = value.strip()
    if not _plain_lines(value):
        raise ValueError(f"{key} may only use \\n line breaks")
    if _FORBIDDEN_LINE.search(value):
        raise ValueError(f"{key} cannot contain headings or front-matter markers")
    if key == "evidence_note" and any(line.startswith("- ") for line in value.split("\n")):
        raise ValueError("evidence_note cannot contain '- ' bullet lines; list paths in evidence instead")
    return value


def _evidence(project, refs):
    from agent_platform_mcp.tools.feature import _safe_path
    if not isinstance(refs, list) or not 1 <= len(refs) <= 10:
        raise ValueError("evidence requires 1..10 project-relative file paths")
    for ref in refs:
        if not isinstance(ref, str) or not ref.strip() or "\n" in ref or "\\" in ref:
            raise ValueError("evidence must be project-relative paths")
        rel = Path(ref.split("#", 1)[0])
        if rel.is_absolute() or ".." in rel.parts or not rel.parts:
            raise ValueError(f"evidence must be a project-relative path: {ref}")
        target = Path(project) / rel
        _safe_path(target, Path(project))
        if not target.is_file():
            raise ValueError(f"evidence file not found: {rel}")
    return refs


def _next_number(directory, kind, name):
    numbers = [int(p.stem.rsplit("__", 1)[1]) for p in directory.glob(f"{kind}__{name}__*.md")
               if p.stem.rsplit("__", 1)[1].isdigit()]
    return max(numbers, default=0) + 1


def _render(meta, sections, evidence):
    head = "\n".join(f"{key}: {value}" for key, value in meta.items())
    refs = "\n".join(f"- {ref}" for ref in evidence)
    return (f"---\n{head}\n---\n\n## Cue\n{sections['cue']}\n\n## Lesson\n{sections['lesson']}\n\n"
            f"## Evidence\n{refs}\n\n{sections['evidence_note']}\n")


def _read(path):
    text = path.read_text(encoding="utf-8")
    meta = frontmatter.parse(text) or {}
    found = {m.group(1): m.group(2).strip() for m in _SECTION.finditer(text)}
    lines = found.get("Evidence", "").splitlines()
    evidence = [line[2:].strip() for line in lines if line.startswith("- ")]
    note = "\n".join(line for line in lines if not line.startswith("- ")).strip()
    return meta, found, evidence, note


def _entry(project, entry_id):
    role, _, stem = str(entry_id).partition("/")
    if not _STEM.fullmatch(stem):
        raise ValueError("unknown experience id")
    path = library(project, role) / f"{stem}.md"
    if not path.is_file() or path.is_symlink():
        raise ValueError("unknown experience id")
    return role, path


def add(root, role, feature, payload):
    project = _project(root)
    if not isinstance(payload, dict) or set(payload) != FIELDS:
        raise ValueError(f"provide exactly {sorted(FIELDS)}")
    sections = {key: _text(key, payload[key]) for key in ("cue", "lesson", "evidence_note")}
    handoff = payload["source_handoff"]
    if not isinstance(handoff, str) or not re.fullmatch(r"[a-z-]+->[a-z-]+", handoff) \
            or any(part not in config.VALID_AGENTS for part in handoff.split("->")):
        raise ValueError("source_handoff must be <role>-><role>")
    evidence = _evidence(project, payload["evidence"])
    kind, name = _work(feature)
    directory = library(project, role)
    meta = {"agent": role, "feature": name, "type": kind, "status": "draft", "scope": "project",
            "created": datetime.date.today().isoformat(), "source_handoff": handoff}
    text = _render(meta, sections, evidence)
    if _mask(text) != text:
        raise ValueError("suspected secret in experience entry")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError(f"experience entry exceeds {MAX_BYTES} bytes")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{kind}__{name}__{_next_number(directory, kind, name)}.md"
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(text)
    except FileExistsError as exc:
        raise ValueError("experience entry number collided; retry explicitly") from exc
    return show(root, f"{role}/{path.stem}")


def show(root, entry_id):
    from agent_platform_mcp.tools.feature import _safe_path
    project = _project(root)
    role, path = _entry(project, entry_id)
    meta, found, evidence, note = _read(path)
    checked = []
    for ref in evidence:
        target = project / ref.split("#", 1)[0]
        try:
            _safe_path(target, project)
            status = "present" if target.is_file() else "missing"
        except ValueError:
            status = "invalid"
        checked.append({"ref": ref, "status": status})
    return {"id": f"{role}/{path.stem}", "path": str(path), "status": meta.get("status", "unknown"),
            "role": role, "feature": meta.get("feature"), "type": meta.get("type"), "created": meta.get("created"),
            "source_handoff": meta.get("source_handoff"), "rejected_reason": meta.get("rejected_reason"),
            "cue": found.get("Cue", ""), "lesson": found.get("Lesson", ""), "note": note, "evidence": checked}


def _paths(project, role):
    directory = library(project, role)
    return sorted(p for p in directory.glob("*.md") if _STEM.fullmatch(p.stem) and not p.is_symlink()) \
        if directory.is_dir() else []


def list_entries(root, role=None, status=None):
    project = _project(root)
    roles = [role] if role else sorted(config.VALID_AGENTS)
    entries = []
    for name in roles:
        for path in _paths(project, name):
            meta = frontmatter.read(path) or {}
            if status and meta.get("status") != status:
                continue
            entries.append({"id": f"{name}/{path.stem}", "status": meta.get("status"), "feature": meta.get("feature"),
                            "type": meta.get("type"), "created": meta.get("created")})
    return {"project_dir": str(project), "entries": entries}


def _set_status(path, status, reason=None):
    text = path.read_text(encoding="utf-8")
    end = text.index("\n---", 3)
    head = [line for line in text[4:end].splitlines() if not line.startswith(("status:", "rejected_reason:"))]
    head.insert(3, f"status: {status}")
    if reason:
        head.append(f"rejected_reason: {reason}")
    path.write_text("---\n" + "\n".join(head) + text[end:], encoding="utf-8")


def _index_path(project, role):
    path = library(project, role) / "INDEX.md"
    if path.is_symlink():
        raise ValueError("INDEX.md symlink not allowed")
    return path


def _index(project, role):
    directory = library(project, role)
    lines = [f"# Experience: {role}", "",
             "Approved, evidence-backed lessons for this project. Read before starting this role.",
             "Generated by `agent-platform-agent experience approve|reject`; do not edit.", ""]
    for path in _paths(project, role):
        meta, found, evidence, _ = _read(path)
        if meta.get("status") != "approved":
            continue
        flat = lambda value: " ".join(value.split())
        lines += [f"## {role}/{path.stem}", f"- Cue: {flat(found.get('Cue', ''))}",
                  f"- Lesson: {flat(found.get('Lesson', ''))}", f"- Evidence: {', '.join(evidence)}", ""]
    _index_path(project, role).write_text("\n".join(lines), encoding="utf-8")


def approve(root, entry_id):
    project = _project(root)
    role, path = _entry(project, entry_id)
    _, _, evidence, _ = _read(path)
    _evidence(project, evidence)
    _index_path(project, role)
    others = [p for p in _paths(project, role) if p != path and (frontmatter.read(p) or {}).get("status") == "approved"]
    if len(others) >= MAX_APPROVED:
        raise ValueError(f"{role} already has {MAX_APPROVED} approved entries; reject outdated ones first")
    _set_status(path, "approved")
    _index(project, role)
    return show(root, entry_id)


def reject(root, entry_id, reason):
    project = _project(root)
    role, path = _entry(project, entry_id)
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 200 or "\n" in reason.strip() \
            or not _plain_lines(reason) or reason.strip().startswith("---") or _mask(reason) != reason:
        raise ValueError("reason requires one line of 1..200 characters without secrets")
    _index_path(project, role)
    _set_status(path, "rejected", reason.strip())
    _index(project, role)
    return show(root, entry_id)


def promote(platform_root, refs):
    """Bundle approved lessons from >=2 projects into platform feedback for the improvement workflow."""
    platform = _project(platform_root)
    if platform != Path(config.ROOT).resolve():
        raise ValueError("promotion is recorded against the platform root")
    if not isinstance(refs, list) or not 2 <= len(refs) <= 20:
        raise ValueError("promote 2..20 approved entries")
    picked = []
    for project_root, entry_id in refs:
        project = _project(project_root)
        role, path = _entry(project, entry_id)
        meta, found, _, _ = _read(path)
        if meta.get("status") != "approved":
            raise ValueError(f"{entry_id} is not approved")
        picked.append((project, role, " ".join(found.get("Lesson", "").split()), entry_id))
    roles = {item[1] for item in picked}
    if len(roles) != 1:
        raise ValueError("promote one role at a time")
    if len({item[0] for item in picked}) < 2:
        raise ValueError("promotion requires approved entries from at least two projects")
    role = roles.pop()
    summary = f"Common {role} lesson candidate:\n" + "\n".join(f"- {lesson} ({entry_id})" for _, _, lesson, entry_id in picked)
    if len(summary) > 2000:
        raise ValueError("promoted lessons exceed the 2000-character feedback limit; promote fewer entries")
    from agent_platform_mcp.learning import feedback
    record = feedback.add(platform_root, "manual", None, "suggestion", summary)
    target = f"standards/agents/{role}.md"
    return {"role": role, "feedback_id": record["id"], "target": target,
            "sources": [{"project_dir": str(p), "id": i} for p, _, _, i in picked],
            "next": f"Write candidate.json for {target}, then: agent-platform-agent improvement propose "
                    f"--root {platform} --feedback {record['id']} < candidate.json"}


def recorded(project, role, feature):
    kind, name = _work(feature)
    directory = library(project, role)
    return directory.is_dir() and any(directory.glob(f"{kind}__{name}__*.md"))
