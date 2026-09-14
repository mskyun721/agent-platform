import json
import unittest
from unittest.mock import Mock

from test_observation import ObservationFixture
from agent_platform_mcp.tools import actions, observation, recovery, state_queries, store


class ActionsTest(ObservationFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.run_id = observation.run_start("sample-task", "cicd", "codex", root="test-project")["run_id"]
        self.action = actions.plan(self.run_id, "pr", "fixture-pr", {"branch": "fixture"})
        self.adapter = Mock()
        self.adapter.lookup.return_value = None
        self.adapter.execute.return_value = "fixture-remote-reference"

    def test_confirmation_and_deduplication(self):
        with self.assertRaises(ValueError):
            actions.execute(self.action["action_id"], self.adapter)
        actions.confirm(self.action["action_id"], "fixture-owner")
        first = actions.execute(self.action["action_id"], self.adapter)
        second = actions.execute(self.action["action_id"], self.adapter)
        self.assertEqual(first["status"], "executed")
        self.assertEqual(second["status"], "skipped_duplicate")
        self.adapter.execute.assert_called_once()
        self.assertEqual(actions.plan(self.run_id, "pr", "fixture-pr", {"branch": "fixture"})["action_id"], first["action_id"])
        with self.assertRaises(ValueError):
            actions.plan(self.run_id, "pr", "fixture-pr", {"branch": "other"})

    def test_existing_remote_never_executes(self):
        actions.confirm(self.action["action_id"], "fixture-owner")
        self.adapter.lookup.return_value = "already-created"
        self.assertEqual(actions.execute(self.action["action_id"], self.adapter)["status"], "skipped_duplicate")
        self.adapter.execute.assert_not_called()

    def test_unknown_write_result_is_not_replayed(self):
        actions.confirm(self.action["action_id"], "fixture-owner")
        self.adapter.execute.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            actions.execute(self.action["action_id"], self.adapter)
        self.assertEqual(actions.execute(self.action["action_id"], self.adapter)["status"], "uncertain")
        self.assertEqual(actions.reconcile(self.action["action_id"], self.adapter)["status"], "uncertain")
        self.adapter.lookup.return_value = "created-before-timeout"
        self.assertEqual(actions.reconcile(self.action["action_id"], self.adapter)["status"], "skipped_duplicate")
        self.adapter.execute.assert_called_once()

    def test_resume_lists_pending_actions_without_remote_calls(self):
        recovery.checkpoint(self.run_id, "release", "review external action")
        recovery.transition(self.run_id, "interrupted")
        result = recovery.resume(self.run_id)
        self.assertEqual(result["actions"][0]["status"], "planned")
        self.adapter.lookup.assert_not_called()
        self.adapter.execute.assert_not_called()
        self.assertEqual(len(state_queries.export_snapshot()["actions"]), 1)

    def test_concurrent_claim_does_not_double_execute(self):
        actions.confirm(self.action["action_id"], "fixture-owner")
        def lookup(value):
            self.assertEqual(actions.execute(value["action_id"], self.adapter)["status"], "uncertain")
            return None
        self.adapter.lookup.side_effect = lookup
        actions.execute(self.action["action_id"], self.adapter)
        self.adapter.execute.assert_called_once()

    def test_git_adapter_uses_argv_and_never_forces_push(self):
        import json
        import hashlib
        from unittest.mock import patch
        from agent_platform_mcp.tools.git_remote import GitRemote
        adapter = GitRemote()
        url = "https://example.invalid/fixture.git"
        action = actions.plan(self.run_id, "push", "fixture-push", {"remote": "origin", "branch": "fixture", "head": "a" * 40,
                                                                    "remote_url_hash": hashlib.sha256(url.encode()).hexdigest()})
        actions.confirm(action["action_id"], "fixture-owner")
        with patch.object(adapter, "_command", side_effect=[url, "a" * 40, "", url, "a" * 40, ""]) as command:
            self.assertEqual(actions.execute(action["action_id"], adapter)["status"], "executed")
        commands = [call.args[0] for call in command.call_args_list]
        self.assertEqual(commands[-1], ["git", "push", "--no-follow-tags", "--recurse-submodules=no", "--", url, "a" * 40 + ":refs/heads/fixture"])
        self.assertFalse(any("--force" in argv for argv in commands))

    def test_changed_remote_and_oversized_pr_are_not_written(self):
        from unittest.mock import patch
        from agent_platform_mcp.tools.git_remote import GitRemote
        adapter = GitRemote()
        push = actions.plan(self.run_id, "push", "changed-remote", {"remote": "origin", "branch": "fixture", "head": "a" * 40, "remote_url_hash": "b" * 64})
        with patch.object(adapter, "_command", return_value="changed-destination") as command:
            with self.assertRaises(ValueError):
                adapter.execute(push)
        self.assertFalse(any(call.args[0][:2] == ["git", "push"] for call in command.call_args_list))
        pr = actions.plan(self.run_id, "pr", "large-pr", {"repository": "fixture/repo", "branch": "fixture", "base": "main", "head": "a" * 40, "base_head": "b" * 40, "title": "Fixture"})
        with patch.object(adapter, "_command", side_effect=["a" * 40, "a" * 40, "b" * 40, '{"within_limit":false}']) as command:
            with self.assertRaises(ValueError):
                adapter.execute(pr)
        self.assertFalse(any(call.args[0][:3] == ["gh", "pr", "create"] for call in command.call_args_list))

    def test_action_snapshot_is_idempotent_and_pinned(self):
        import os
        from unittest.mock import patch
        observation.run_end(self.run_id, "completed")
        snapshot = state_queries.export_snapshot()
        with patch.dict(os.environ, {"AGENT_PLATFORM_STATE_DB": str(self.root / "imported.db")}):
            state_queries.import_snapshot(snapshot)
            state_queries.import_snapshot(snapshot)
            self.assertEqual(len(actions.list_actions()), 1)
            self.assertEqual(state_queries.prune("2099-01-01T00:00:00Z")["removed_runs"], 0)

    def pr_fixture(self):
        return actions.plan(self.run_id, "pr", "remote-pr", {"repository": "fixture/repo", "branch": "fixture",
            "base": "main", "head": "a" * 40, "base_head": "b" * 40, "title": "Fixture"})

    def test_pr_remote_head_and_base_drift_block_creation(self):
        from unittest.mock import patch
        from agent_platform_mcp.tools.git_remote import GitRemote
        adapter, action = GitRemote(), self.pr_fixture()
        for results in (["a" * 40, "c" * 40], ["a" * 40, "a" * 40, "c" * 40]):
            with self.subTest(results=results), patch.object(adapter, "_command", side_effect=results) as command:
                with self.assertRaises(ValueError):
                    adapter.execute(action)
                self.assertFalse(any(c.args[0][:3] == ["gh", "pr", "create"] for c in command.call_args_list))

    def test_pr_pins_remote_base_and_checks_created_commits(self):
        from unittest.mock import patch
        from agent_platform_mcp.tools.git_remote import GitRemote
        adapter, action = GitRemote(), self.pr_fixture()
        for head in ("a" * 40, "c" * 40):
            responses = ["a" * 40, "a" * 40, "b" * 40, '{"within_limit":true}', "a" * 40, "b" * 40,
                         "https://example.invalid/pr/1", json.dumps({"headRefOid": head, "baseRefOid": "b" * 40})]
            with patch.object(adapter, "_command", side_effect=responses) as command:
                if head == "a" * 40:
                    self.assertEqual(adapter.execute(action), "https://example.invalid/pr/1")
                else:
                    with self.assertRaises(ValueError):
                        adapter.execute(action)
            size_argv = command.call_args_list[3].args[0]
            self.assertEqual(size_argv[size_argv.index("--base") + 1], "b" * 40)

    def test_pr_prepare_pins_base_and_rejects_unpushed_head(self):
        from unittest.mock import patch
        from agent_platform_mcp.tools.git_remote import GitRemote
        adapter = GitRemote()
        target = json.loads(self.pr_fixture()["target_json"])
        del target["base_head"]
        with patch.object(adapter, "_command", side_effect=["a" * 40, "a" * 40, "b" * 40]):
            self.assertEqual(adapter.prepare(self.run_id, "pr", target)["base_head"], "b" * 40)
        with patch.object(adapter, "_command", side_effect=["a" * 40, "c" * 40]):
            with self.assertRaises(ValueError):
                adapter.prepare(self.run_id, "pr", target)

    def test_push_lookup_and_reconcile_use_push_destination(self):
        import subprocess
        from agent_platform_mcp.tools.git_remote import GitRemote
        adapter = GitRemote()
        def git(*args):
            return subprocess.check_output(["git", *args], cwd=self.root, text=True).strip()
        git("init", "-q")
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-qm", "fixture")
        git("branch", "-M", "fixture")
        head = git("rev-parse", "HEAD")
        fetch, push = self.root / "fetch.git", self.root / "push.git"
        git("init", "--bare", "-q", str(fetch))
        git("init", "--bare", "-q", str(push))
        git("remote", "add", "origin", str(fetch))
        git("remote", "set-url", "--push", "origin", str(push))
        git("push", "-q", str(fetch), "fixture")
        target = adapter.prepare(self.run_id, "push", {"remote": "origin", "branch": "fixture", "head": head})
        action = actions.plan(self.run_id, "push", "split-destination", target)
        self.assertIsNone(adapter.lookup(action))
        actions.confirm(action["action_id"], "fixture-owner")
        self.assertEqual(actions.execute(action["action_id"], adapter)["status"], "executed")
        self.assertIn(head, git("ls-remote", str(push), "refs/heads/fixture"))
        with store.open() as db, db.connection:
            db.connection.execute("UPDATE actions SET status='uncertain' WHERE action_id=?", (action["action_id"],))
        self.assertEqual(actions.reconcile(action["action_id"], adapter)["status"], "skipped_duplicate")
        self.assertNotIn(str(push), str(actions.list_actions()))

    def test_existing_pr_with_other_commits_is_not_duplicate(self):
        from unittest.mock import patch
        from agent_platform_mcp.tools.git_remote import GitRemote
        adapter, action = GitRemote(), self.pr_fixture()
        rows = [{"state": "OPEN", "headRefOid": "c" * 40, "baseRefOid": "b" * 40, "url": "https://example.invalid/pr/1"}]
        with patch.object(adapter, "_command", side_effect=["a" * 40, "a" * 40, "b" * 40, json.dumps(rows)]):
            with self.assertRaises(ValueError):
                adapter.lookup(action)

    def test_created_pr_mismatch_stays_uncertain_without_replay(self):
        from unittest.mock import patch
        from agent_platform_mcp.tools.git_remote import GitRemote
        adapter, action = GitRemote(), self.pr_fixture()
        actions.confirm(action["action_id"], "fixture-owner")
        responses = ["a" * 40, "a" * 40, "b" * 40, '{"within_limit":true}', "a" * 40, "b" * 40,
                     "https://example.invalid/pr/1", json.dumps({"headRefOid": "c" * 40, "baseRefOid": "b" * 40})]
        with patch.object(adapter, "lookup", return_value=None), patch.object(adapter, "_command", side_effect=responses) as command:
            with self.assertRaises(ValueError):
                actions.execute(action["action_id"], adapter)
            self.assertEqual(actions.execute(action["action_id"], adapter)["status"], "uncertain")
            self.assertEqual(sum(c.args[0][:3] == ["gh", "pr", "create"] for c in command.call_args_list), 1)

    def test_remote_timeout_does_not_expose_destination(self):
        import subprocess
        from unittest.mock import patch
        from agent_platform_mcp.tools.git_remote import GitRemote
        argv = ["git", "ls-remote", "https://example.invalid/private-destination"]
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(argv, 60)):
            with self.assertRaises(RuntimeError) as error:
                GitRemote()._command(argv, self.root)
        self.assertNotIn("private-destination", str(error.exception))
