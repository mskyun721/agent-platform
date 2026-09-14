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
        from unittest.mock import patch
        from agent_platform_mcp.tools.git_remote import GitRemote
        adapter = GitRemote()
        action = actions.plan(self.run_id, "push", "fixture-push", {"remote": "origin", "branch": "fixture", "head": "a" * 40})
        actions.confirm(action["action_id"], "fixture-owner")
        with patch.object(adapter, "_command", side_effect=["a" * 40, "", "a" * 40, ""]) as command:
            self.assertEqual(actions.execute(action["action_id"], adapter)["status"], "executed")
        commands = [call.args[0] for call in command.call_args_list]
        self.assertEqual(commands[-1], ["git", "push", "origin", "a" * 40 + ":refs/heads/fixture"])
        self.assertFalse(any("--force" in argv for argv in commands))

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
