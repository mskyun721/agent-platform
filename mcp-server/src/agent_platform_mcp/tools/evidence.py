"""Acceptance criteria and code-bound evidence checks; report mode by default."""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from agent_platform_mcp import frontmatter
from agent_platform_mcp.tools import fingerprint, store

SCHEMA = """
CREATE TABLE evidence (
 id TEXT PRIMARY KEY, project_id TEXT, task_id TEXT NOT NULL, workspace TEXT NOT NULL,
 ac_id TEXT NOT NULL, verify_run_id TEXT REFERENCES runs(run_id), profile_id TEXT,
 status TEXT NOT NULL, code_fingerprint TEXT NOT NULL, criteria_hash TEXT NOT NULL, ts TEXT NOT NULL,
 profile_hash TEXT);
CREATE INDEX evidence_task ON evidence(workspace, task_id, ac_id);
"""


def lines_outside_fences(text: str) -> list[str]:
    lines = []
    fence = None
    for line in text.splitlines():
        match = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
        if match:
            marker, rest = match.groups()
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence) and not rest.strip():
                fence = None
        elif fence is None:
            lines.append(line)
    return lines


def acceptance_criteria(item_dir: Path) -> list[dict]:
    from agent_platform_mcp.tools.feature import _safe_path

    source = item_dir / ("WORK.md" if (item_dir / "WORK.md").exists() else "PRD.md")
    _safe_path(source, item_dir)
    if not source.is_file():
        return []
    active = False
    results = []
    for line in lines_outside_fences(source.read_text()):
        if line.startswith("## "):
            active = line.startswith("## 4. 검증") if source.name == "WORK.md" else line.startswith("## 12. 수락 기준")
        if active and line.strip().startswith("|"):
            cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
            if cells and re.fullmatch(r"AC-[1-9][0-9]*", cells[0]):
                if len(cells) < 3 or not cells[1] or not cells[2]:
                    raise ValueError("acceptance criterion needs condition and verification method")
                if any(item["id"] == cells[0] for item in results):
                    raise ValueError("duplicate acceptance criterion id")
                results.append({"id": cells[0], "text": cells[1], "method": cells[2], "source": source.name})
    return results


def criteria_hash(criteria: list[dict]) -> str:
    return hashlib.sha256(json.dumps(criteria, sort_keys=True).encode()).hexdigest()


def record(result: dict, project: Path, before: dict, after: dict, criteria: list[dict], ac_ids: list[str]) -> None:
    valid = {item["id"] for item in criteria}
    if not ac_ids or any(not isinstance(ac, str) or ac not in valid for ac in ac_ids) or len(set(ac_ids)) != len(ac_ids):
        raise ValueError("evidence needs explicit, unique AC mapping from the selected profile")
    status = result["verification_status"] if before["fingerprint"] == after["fingerprint"] else "stale"
    with store.open() as db, db.connection:
        for ac in ac_ids:
            db.connection.execute("INSERT INTO evidence VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(uuid4()), result.get("project_id"), result["feature"], str(project), ac,
                 result.get("verification_run_id"), result["verification"]["profile_id"], status,
                 before["fingerprint"], criteria_hash(criteria), datetime.now(timezone.utc).isoformat(),
                 result.get("policy", {}).get("profile_hash")))


def findings(path: Path, current: str) -> list[dict]:
    if not path.exists():
        return []
    from agent_platform_mcp.tools.feature import _safe_path
    _safe_path(path, path.parent)
    found = []
    active = None
    for line in lines_outside_fences(path.read_text()):
        match = re.match(r"^### \[(CRITICAL|HIGH|MEDIUM|LOW)\] (.+)$", line, re.I)
        if match:
            found.append({"severity": match[1].upper(), "title": match[2], "resolved": False, "file": path.name})
            active = found[-1]
        elif line.startswith("#"):
            active = None
        elif active is not None and re.fullmatch(r"- (?:상태|status): resolved \(" + re.escape(current) + r"\)", line, re.I):
            active["resolved"] = True
    return [item for item in found if item["severity"] in {"CRITICAL", "HIGH"} and not item["resolved"]]


def assess(result: dict, project: Path, item_dir: Path) -> dict:
    from agent_platform_mcp import config
    from agent_platform_mcp.tools.verification import profile_hash
    current = fingerprint.code_fingerprint(project)["fingerprint"]
    criteria = acceptance_criteria(item_dir)
    statuses = []
    with store.open() as db:
        for criterion in criteria:
            row = db.connection.execute("SELECT status,code_fingerprint,criteria_hash,profile_id,profile_hash FROM evidence WHERE workspace=? AND task_id=? AND ac_id=? ORDER BY rowid DESC LIMIT 1",
                                        (str(project), result["feature"], criterion["id"])).fetchone()
            status = "missing" if row is None else (
                "stale" if row[1] != current or row[2] != criteria_hash(criteria) else row[0])
            if row is not None:
                profile = config.agent_config().get("verify_profiles", {}).get(row[3])
                if not isinstance(profile, dict) or profile_hash(profile) != row[4]:
                    status = "stale"
            statuses.append({"id": criterion["id"], "status": status})
    approvals = []
    unresolved = []
    for filename in ("REVIEW.md", "SECURITY-AUDIT.md", "TEST-PLAN.md"):
        path = item_dir / filename
        from agent_platform_mcp.tools.feature import _safe_path
        _safe_path(path, item_dir)
        fm = frontmatter.read(path) or {}
        if fm.get("status") == "approved" and fm.get("approved_fingerprint") != current:
            approvals.append(filename)
        unresolved.extend(findings(path, current))
    complete = bool(statuses) and all(item["status"] == "passed" for item in statuses) and not approvals and not unresolved
    return {"status": "complete" if complete else "stale" if any(item["status"] == "stale" for item in statuses) else "incomplete",
            "acs": statuses, "approval_stale": approvals, "unresolved_findings": unresolved,
            "code_fingerprint": current, "criteria_hash": criteria_hash(criteria), "mode": "report"}
