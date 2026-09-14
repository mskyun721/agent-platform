import os
import signal
import subprocess
import sys
import unittest

from test_observation import ObservationFixture
from agent_platform_mcp.tools import monitored_process, observation, store


class MonitoredProcessTest(ObservationFixture, unittest.TestCase):
    def test_timeout_kills_actual_group_and_records_interruption(self):
        from agent_platform_mcp.tools import runner, projects
        from unittest.mock import patch
        command = [sys.executable, "-c", "import time; time.sleep(60)"]
        def execute():
            runner.run_cli("codex", command, self.root, 0.05)
        with patch.object(runner.shutil, "which", return_value=sys.executable):
            with self.assertRaises(monitored_process.ProcessInterrupted):
                observation.observed(projects.resolve("test-project"), "sample-task", "qa", "codex", False, execute)
        with store.open() as db:
            run = db.runs()[0]
            self.assertEqual(run["outcome"], "interrupted")
            pid = db.connection.execute("SELECT pid FROM run_control WHERE run_id=?", (run["run_id"],)).fetchone()[0]
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_sigterm_restores_handler_and_reaps_child(self):
        previous = signal.getsignal(signal.SIGTERM)
        pids = []
        def pulse(pid):
            pids.append(pid)
            os.kill(os.getpid(), signal.SIGTERM)
        with self.assertRaises(monitored_process.ProcessInterrupted):
            monitored_process.run([sys.executable, "-c", "import time; time.sleep(60)"], cwd=self.root, timeout=5, pulse=pulse)
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)
        with self.assertRaises(ProcessLookupError):
            os.kill(pids[0], 0)

    def test_actual_output_is_returned_not_persisted(self):
        result = monitored_process.run([sys.executable, "-c", "print('fixture')"], cwd=self.root, timeout=5)
        self.assertEqual(result.stdout.strip(), "fixture")
        self.assertEqual(result.returncode, 0)
