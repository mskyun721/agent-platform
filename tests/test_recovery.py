import os
import subprocess
import sys
import unittest

from test_observation import ObservationFixture
from agent_platform_mcp.tools import observation, recovery, store


class RecoveryTest(ObservationFixture, unittest.TestCase):
    def test_cli_checkpoint_resume_and_continue_routing(self):
        from agent_platform_mcp import cli, server
        from unittest.mock import patch
        run = self.start()
        with patch.object(cli, "_print_result"):
            self.assertEqual(cli.main(["state", "checkpoint", run, "--phase", "implementation", "--next-action", "run tests"]), 0)
            self.assertEqual(cli.main(["state", "transition", run, "interrupted"]), 0)
            self.assertEqual(cli.main(["state", "resume", run]), 0)
            self.assertEqual(cli.main(["state", "continue", run, "--pid", str(os.getpid())]), 0)
        self.assertEqual(server.run_resume(run)["verdict"], "running")

    def start(self):
        return observation.run_start("sample-task", "backend", "codex", root="test-project")["run_id"]

    def test_checkpoint_sequence_and_terminal_transition_guard(self):
        run = self.start()
        first = recovery.checkpoint(run, "implementation", "run verification", decisions=["keep API unchanged"])
        second = recovery.checkpoint(run, "verification", "inspect result")
        self.assertEqual((first["seq"], second["seq"]), (1, 2))
        self.assertIn("run verification", recovery.markdown(first))
        observation.run_end(run, "completed")
        self.assertEqual(recovery.resume(run)["verdict"], "done")
        with self.assertRaises(ValueError):
            recovery.transition(run, "running")

    def test_real_interruption_resume_and_workspace_divergence(self):
        (self.root / "app.py").write_text("value = 1\n")
        run = self.start()
        recovery.checkpoint(run, "verification", "rerun tests")
        process = subprocess.Popen([sys.executable, "-c", "import time; print('ready', flush=True); time.sleep(60)"],
                                   stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "ready")
            recovery.heartbeat(run, process.pid)
            self.assertEqual(recovery.resume(run)["verdict"], "running")
            process.terminate()
            process.wait(timeout=5)
            recovery.transition(run, "interrupted", reason="signal")
            result = recovery.resume(run)
            self.assertEqual(result["verdict"], "resumable")
            self.assertFalse(result["auto_executed"])
            self.assertIn("rerun tests", result["resume_prompt"])
            (self.root / "app.py").write_text("value = 2\n")
            result = recovery.resume(run)
            self.assertEqual(result["verdict"], "diverged")
            self.assertEqual(result["workspace_diff"], ["app.py"])
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            process.stdout.close()

    def test_stale_heartbeat_live_pid_and_missing_checkpoint(self):
        run = self.start()
        recovery.heartbeat(run, os.getpid())
        with store.open() as db, db.connection:
            db.connection.execute("UPDATE run_control SET heartbeat_at=? WHERE run_id=?", ("2000-01-01T00:00:00+00:00", run))
        self.assertEqual(recovery.resume(run)["verdict"], "running")
        recovery.transition(run, "interrupted")
        self.assertEqual(recovery.resume(run)["verdict"], "running")

    def test_cancel_and_metadata_validation(self):
        run = self.start()
        with self.assertRaises(ValueError):
            recovery.checkpoint(run, "implementation", "next", artifacts=["../outside.md"])
        recovery.transition(run, "cancelled")
        self.assertEqual(recovery.resume(run)["verdict"], "done")

    def test_snapshot_round_trip_and_prune_preserve_checkpoints(self):
        from unittest.mock import patch
        from agent_platform_mcp.tools import state_queries
        run = self.start()
        value = recovery.checkpoint(run, "implementation", "inspect tests")
        observation.run_end(run, "interrupted")
        snapshot = state_queries.export_snapshot()
        with patch.dict(os.environ, {"AGENT_PLATFORM_STATE_DB": str(self.root / "restored.db")}):
            state_queries.import_snapshot(snapshot)
            state_queries.import_snapshot(snapshot)
            with store.open() as db:
                rows = recovery.export_rows(db)
                self.assertEqual(len(rows["checkpoints"]), 1)
                self.assertIn(value["snapshot"]["fingerprint"], rows["checkpoints"][0]["payload_json"])
            self.assertEqual(state_queries.prune("2099-01-01T00:00:00Z")["removed_runs"], 0)

    def test_unregistered_project_cannot_resume(self):
        from agent_platform_mcp.tools import projects
        run = self.start()
        recovery.checkpoint(run, "implementation", "test")
        recovery.transition(run, "interrupted")
        projects.unregister("test-project")
        with self.assertRaises(ValueError):
            recovery.resume(run)

    def test_new_session_claim_preserves_history_and_blocks_duplicate(self):
        from agent_platform_mcp.tools import actions, continuation, state_queries
        from unittest.mock import patch
        run = self.start()
        recovery.checkpoint(run, "implementation", "run remaining tests")
        actions.plan(run, "pr", "pending-inherited", {"branch": "fixture"})
        observation.run_end(run, "interrupted")
        claimed = continuation.claim(run, os.getpid())
        self.assertTrue(claimed["claimed"])
        self.assertNotEqual(claimed["run_id"], run)
        self.assertEqual(recovery.resume(run)["verdict"], "running")
        duplicate = continuation.claim(run, os.getpid())
        self.assertFalse(duplicate["claimed"])
        self.assertEqual(duplicate["run_id"], claimed["run_id"])
        self.assertEqual(recovery.resume(claimed["run_id"])["actions"][0]["idempotency_key"], "pending-inherited")
        observation.run_end(claimed["run_id"], "completed")
        with store.open() as db:
            self.assertEqual(db.run(run)["outcome"], "interrupted")
            self.assertEqual(db.run(claimed["run_id"])["outcome"], "completed")
        snapshot = state_queries.export_snapshot()
        with patch.dict(os.environ, {"AGENT_PLATFORM_STATE_DB": str(self.root / "lineage.db")}):
            state_queries.import_snapshot(snapshot)
            state_queries.import_snapshot(snapshot)
            self.assertEqual(recovery.resume(run)["continuation_run_id"], claimed["run_id"])

    def test_continuation_preserves_repeated_rejection_waiting(self):
        from uuid import uuid4
        from agent_platform_mcp.tools import continuation
        run = observation.run_start("sample-task", "reviewer", "codex", root="test-project")["run_id"]
        for _ in range(3):
            observation.review_result_record("sample-task", "reviewer", "rejected",
                "docs/features/sample-task/REVIEW.md", "a" * 64, "fixture-owner", str(uuid4()), "test-project", run)
        recovery.checkpoint(run, "review", "wait for user intervention")
        observation.run_end(run, "completed")
        child = continuation.claim(run, os.getpid())["run_id"]
        observation.run_end(child, "completed")
        with store.open() as db:
            parent_state, child_state = recovery._state(db, run), recovery._state(db, child)
            self.assertEqual(child_state["state"], "waiting")
            self.assertEqual(child_state["reason"], parent_state["reason"])
            self.assertTrue(db.review_status("test-project", "sample-task")["reviewer"]["intervention_recommended"])
