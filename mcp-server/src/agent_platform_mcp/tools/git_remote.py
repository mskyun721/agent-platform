"""Explicit Git/PR adapter for the confirmed ledger, never called by resume."""

import json
import re
import subprocess

from agent_platform_mcp.tools import recovery, store


class GitRemote:
    def _command(self, argv, workspace):
        result = subprocess.run(argv, cwd=workspace, capture_output=True, text=True, timeout=60, check=False)
        if result.returncode:
            raise RuntimeError("remote command failed; inspect remote state without replaying")
        return result.stdout.strip()

    def _target(self, action):
        target = json.loads(action["target_json"])
        expected = {"remote", "branch", "head"} if action["kind"] == "push" else {"branch", "base", "head", "title"}
        if action["kind"] not in {"push", "pr"} or set(target) != expected:
            raise ValueError("Git adapter requires an explicit push or PR target")
        for field in (expected - {"head", "title"}):
            if not isinstance(target[field], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,200}", target[field]) or ".." in target[field]:
                raise ValueError("invalid remote/ref identifier")
        if not isinstance(target["head"], str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", target["head"]):
            raise ValueError("explicit commit identity required")
        if "title" in target:
            recovery._text(target["title"])
        with store.open() as db:
            workspace = recovery._workspace(db.run(action["run_id"]))
        head = self._command(["git", "rev-parse", "--verify", "--end-of-options", "refs/heads/" + target["branch"]], workspace)
        if head != target["head"]:
            raise ValueError("branch changed since action planning; plan and confirm a new action")
        return workspace, target

    def lookup(self, action):
        workspace, target = self._target(action)
        if action["kind"] == "push":
            result = self._command(["git", "ls-remote", "--refs", target["remote"], "refs/heads/" + target["branch"]], workspace)
            for line in result.splitlines():
                fields = line.split()
                if fields == [target["head"], "refs/heads/" + target["branch"]]:
                    return "refs/heads/" + target["branch"] + "@" + target["head"]
            return None
        rows = json.loads(self._command(["gh", "pr", "list", "--head", target["branch"], "--base", target["base"],
                                        "--state", "all", "--limit", "100", "--json", "url,headRefOid,state"], workspace))
        for row in rows:
            if row.get("state") == "OPEN" or row.get("headRefOid") == target["head"]:
                return row["url"]
        if len(rows) >= 100:
            raise ValueError("PR lookup is truncated; inspect remote state manually")
        return None

    def execute(self, action):
        workspace, target = self._target(action)
        if action["kind"] == "push":
            self._command(["git", "push", target["remote"], target["head"] + ":refs/heads/" + target["branch"]], workspace)
            return "refs/heads/" + target["branch"] + "@" + target["head"]
        return self._command(["gh", "pr", "create", "--draft", "--head", target["branch"], "--base", target["base"],
                              "--title", target["title"], "--body", "Created after explicit action-ledger confirmation. Review before merge."], workspace)
