"""Explicit Git/PR adapter for the confirmed ledger, never called by resume."""

import json
import hashlib
import re
import subprocess
import sys

from agent_platform_mcp import config
from agent_platform_mcp.tools import recovery, store


class GitRemote:
    def prepare(self, run_id, kind, target):
        if kind == "push":
            if set(target) != {"remote", "branch", "head"} or not isinstance(target["remote"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}", target["remote"]):
                raise ValueError("push planning requires remote alias, branch and commit")
            with store.open() as db:
                workspace = recovery._workspace(db.run(run_id))
            url = self._command(["git", "remote", "get-url", "--push", "--all", target["remote"]], workspace)
            if len(url.splitlines()) != 1:
                raise ValueError("push requires exactly one configured destination")
            return {**target, "remote_url_hash": hashlib.sha256(url.encode()).hexdigest()}
        return target

    def _command(self, argv, workspace):
        result = subprocess.run(argv, cwd=workspace, capture_output=True, text=True, timeout=60, check=False)
        if result.returncode:
            raise RuntimeError("remote command failed; inspect remote state without replaying")
        return result.stdout.strip()

    def _target(self, action):
        target = json.loads(action["target_json"])
        expected = {"remote", "branch", "head", "remote_url_hash"} if action["kind"] == "push" else {"repository", "branch", "base", "head", "title"}
        if action["kind"] not in {"push", "pr"} or set(target) != expected:
            raise ValueError("Git adapter requires an explicit push or PR target")
        for field in (expected - {"head", "title", "remote_url_hash"}):
            if not isinstance(target[field], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,200}", target[field]) or ".." in target[field]:
                raise ValueError("invalid remote/ref identifier")
        if not isinstance(target["head"], str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", target["head"]):
            raise ValueError("explicit commit identity required")
        if "title" in target:
            recovery._text(target["title"])
        with store.open() as db:
            workspace = recovery._workspace(db.run(action["run_id"]))
        if action["kind"] == "push":
            url = self._command(["git", "remote", "get-url", "--push", "--all", target["remote"]], workspace)
            if hashlib.sha256(url.encode()).hexdigest() != target["remote_url_hash"]:
                raise ValueError("remote destination changed since confirmation; plan a new action")
        elif not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", target["repository"]):
            raise ValueError("PR requires explicit owner/repository")
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
        rows = json.loads(self._command(["gh", "pr", "list", "--repo", target["repository"], "--head", target["branch"], "--base", target["base"],
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
            self._command(["git", "push", "--no-follow-tags", "--recurse-submodules=no", target["remote"], target["head"] + ":refs/heads/" + target["branch"]], workspace)
            return "refs/heads/" + target["branch"] + "@" + target["head"]
        size = json.loads(self._command([sys.executable, str(config.ROOT / "scripts/pr_logic_size.py"), "--repo", str(workspace),
                                        "--base", target["base"], "--head", target["head"]], workspace))
        if size.get("within_limit") is not True:
            raise ValueError("PR logic changes exceed 500 lines or cannot be classified")
        return self._command(["gh", "pr", "create", "--repo", target["repository"], "--draft", "--head", target["branch"], "--base", target["base"],
                              "--title", target["title"], "--body", "Created after explicit action-ledger confirmation. Review before merge."], workspace)
