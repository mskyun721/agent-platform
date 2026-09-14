import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp-server/src"))
from agent_platform_mcp import server
from agent_platform_mcp.tools import feature, observation, projects, review, runner, skill_packages, store


class ObservationFixture:
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        for mock in (patch.object(projects, "REGISTRY_FILE", self.root / ".agent-projects.json"),
                     patch.object(skill_packages, "REGISTRY", self.root / "skill-registry.json"),
                     patch.dict(os.environ, {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": str(self.root),
                                             "AGENT_PLATFORM_STATE_DB": str(self.root / "state.db")})):
            mock.start()
            self.addCleanup(mock.stop)
        projects.register(str(self.root), "test-project")
        feature.scaffold("sample-task", root="test-project")


class ObservationTest(ObservationFixture, unittest.TestCase):
    def test_real_terminated_verification_process_is_interrupted(self):
        context = projects.resolve("test-project")
        def action():
            process = subprocess.Popen([sys.executable, "-c", "import time; print('ready', flush=True); time.sleep(60)"],
                                       cwd=self.root, stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(), "ready")
                process.terminate()
                self.assertLess(process.wait(timeout=5), 0)
                raise KeyboardInterrupt()
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                process.stdout.close()
        with self.assertRaises(KeyboardInterrupt):
            observation.observed(context, "sample-task", "qa", "codex", False, action)
        with store.open() as db:
            self.assertEqual(db.runs()[0]["outcome"], "interrupted")

    def test_dry_run_does_not_record(self):
        with patch.object(store, "open", side_effect=AssertionError("dry run must not collect")):
            review.run("sample-task", cli="codex", root="test-project", dry_run=True)

    def test_wrapper_lifecycle_is_metadata_only(self):
        with patch.object(runner, "run_cli", return_value=subprocess.CompletedProcess([], 0, "private source", "private stderr")):
            result = review.run("sample-task", cli="codex", root="test-project")
        self.assertTrue(result["observability"]["stored"])
        with store.open() as db:
            rows = db.connection.execute("SELECT event_json FROM events").fetchall()
            self.assertEqual(len(rows), 2)
            self.assertNotIn("private source", str([row[0] for row in rows]))
            self.assertNotIn("private stderr", str([row[0] for row in rows]))
            self.assertEqual(db.run(result["run_id"])["outcome"], "completed")
            usage = json.loads(db.connection.execute("SELECT payload_json FROM usage").fetchone()[0])
            self.assertIsNone(usage["input_tokens"])
            self.assertEqual(usage["completeness"], "unavailable")
        # A successful CLI process is not an approved or structurally valid review.
        self.assertEqual(result["artifact_status"], "invalid")

    def test_collection_failure_does_not_block_work(self):
        context = projects.resolve("test-project")
        with patch.object(store, "open", side_effect=store.StoreError("private diagnostic")):
            result = observation.observed(context, "sample-task", "backend", "codex", False, lambda: {"exit_code": 0})
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["observability"], {"stored": False, "error": "StoreError"})

    def test_failed_and_cancelled_execution_are_recorded(self):
        context = projects.resolve("test-project")
        for error in (RuntimeError("private failure"), KeyboardInterrupt()):
            def fail():
                raise error
            with self.assertRaises(type(error)):
                observation.observed(context, "sample-task", "backend", "codex", False, fail)
        with store.open() as db:
            self.assertEqual({run["outcome"] for run in db.runs()}, {"failed", "interrupted"})

    def test_direct_lifecycle_review_retry_and_role_counters(self):
        started = server.run_start("sample-task", "reviewer", "claude", root="test-project")
        identity = str(uuid4())
        arguments = dict(task_id="sample-task", role="reviewer", decision="rejected", artifact="docs/features/sample-task/REVIEW.md",
                         code_fingerprint="a" * 64, reviewer_id="owning-reviewer", decision_id=identity,
                         root="test-project", run_id=started["run_id"])
        first = server.review_result_record(**arguments)
        second = server.review_result_record(**arguments)
        self.assertEqual(first["attempt"], second["attempt"])
        self.assertFalse(second["inserted"])
        self.assertEqual(server.review_cycle_status("sample-task", "test-project")["reviewer"]["consecutive_rejections"], 1)
        self.assertTrue(server.run_end(started["run_id"], "completed")["observability"]["stored"])
        self.assertEqual(len(server.runs_list("test-project")["runs"]), 1)

    def test_verification_not_run_is_observed_without_passing(self):
        result = feature.gate_check("sample-task", root="test-project", verify=True)
        self.assertFalse(result["passed"])
        with store.open() as db:
            row = db.connection.execute("SELECT event_json FROM events WHERE event_type='verification'").fetchone()
            self.assertIsNotNone(row)
            payload = json.loads(row[0])["payload"]
            self.assertEqual(payload["status"], "not_run")
            self.assertNotIn("stdout", payload)
