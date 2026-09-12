import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server/src"))
from agent_platform_mcp import cli, server
from agent_platform_mcp.tools import audit, backend, feature, plan, projects, qa, release, review, runner


class WrapperContextTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.a, self.b = self.base / "a/service", self.base / "b/service"
        for path in (self.a, self.b):
            path.mkdir(parents=True)
        for mock in (patch.object(projects, "REGISTRY_FILE", self.base / ".agent-projects.json"),
                     patch.dict(os.environ, {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": str(self.base),
                                             "TARGET_PROJECT_ROOT": str(self.b)})):
            mock.start()
            self.addCleanup(mock.stop)
        projects.register(str(self.a), "service-a")
        projects.register(str(self.b), "service-b")
        for key in ("service-a", "service-b"):
            feature.scaffold("same-feature", root=key)
        self.calls = [(plan, {"requirements": "small fix"}, server.plan_run),
                      (backend, {}, server.backend_run), (review, {}, server.review_run),
                      (audit, {}, server.audit_run), (qa, {}, server.qa_run), (release, {}, server.release_run)]

    def test_every_wrapper_and_mcp_uses_explicit_id_not_active_project(self):
        before = dict(os.environ)
        for module, kwargs, tool in self.calls:
            with self.subTest(module=module.__name__):
                for call in (module.run, tool):
                    result = call("same-feature", cli="codex", root="service-a", dry_run=True, **kwargs)
                    self.assertEqual(result["project_id"], "service-a")
                    self.assertEqual(result["project_dir"], str(self.a))
                    self.assertEqual(result["command"][result["command"].index("--cd") + 1], str(self.a))
                    self.assertIn(str(self.a / "docs/features/same-feature"), result["command"][-1])
                    self.assertNotIn(str(self.b), result["command"][-1])
        self.assertEqual(dict(os.environ), before)

    def test_context_is_resolved_once_even_when_active_project_changes_during_execution(self):
        for module, kwargs, _ in self.calls:
            with self.subTest(module=module.__name__):
                def execute(ai, command, workdir, timeout):
                    self.assertEqual(workdir, self.a)
                    os.environ["TARGET_PROJECT_ROOT"] = str(self.b)
                    self.assertNotIn(str(self.b), command[-1])
                    for filename in ("API-SPEC.md", "DECISIONS.md", "TEST-PLAN.md", "RELEASE-NOTE.md"):
                        (workdir / "docs/features/same-feature" / filename).write_text("# Fixture\n")
                    return subprocess.CompletedProcess(command, 0, "# Fixture result", "")
                with patch.dict(os.environ, {"TARGET_PROJECT_ROOT": str(self.a)}), \
                     patch.object(runner, "resolve_project", wraps=runner.resolve_project) as resolve, \
                     patch.object(runner, "run_cli", side_effect=execute):
                    result = module.run("same-feature", cli="codex", root="service-a", **kwargs)
                self.assertEqual(resolve.call_count, 1)
                self.assertEqual(result["project_dir"], str(self.a))
        self.assertEqual(sorted(p.name for p in (self.b / "docs/features/same-feature").iterdir()), ["PRD.md", "TASK.md"])

    def test_parallel_reviews_do_not_mix_roots(self):
        def execute(ai, command, workdir, timeout):
            return subprocess.CompletedProcess(command, 0, f"# Review for {workdir}", "")
        with patch.object(runner, "run_cli", side_effect=execute), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda key: review.run("same-feature", cli="codex", root=key), ["service-a", "service-b"]))
        self.assertEqual({r["project_id"] for r in results}, {"service-a", "service-b"})
        for own, other in ((self.a, self.b), (self.b, self.a)):
            content = (own / "docs/features/same-feature/REVIEW.md").read_text()
            self.assertIn(str(own), content)
            self.assertNotIn(str(other), content)

    def test_symlink_outputs_are_rejected_after_cli_returns(self):
        outside = self.base / "untouched.md"
        outside.write_text("unchanged")
        def execute(*args):
            (self.a / "docs/features/same-feature/REVIEW.md").symlink_to(outside)
            return subprocess.CompletedProcess([], 0, "replacement", "")
        with patch.object(runner, "run_cli", side_effect=execute):
            with self.assertRaisesRegex(ValueError, "symlink"):
                review.run("same-feature", cli="codex", root="service-a")
        self.assertEqual(outside.read_text(), "unchanged")

    def test_cli_exposes_root_and_existing_fallback_still_works(self):
        with patch.object(cli, "_print_result") as output:
            self.assertEqual(cli.main(["run", "reviewer", "same-feature", "--root", "service-a", "--dry-run"]), 0)
        self.assertEqual(output.call_args.args[0]["project_id"], "service-a")
        self.assertEqual(review.run("same-feature", cli="codex", dry_run=True)["project_id"], "service-b")

    def test_unallowed_root_cannot_launch_cli(self):
        with patch.object(runner, "run_cli") as execute:
            with self.assertRaises(RuntimeError):
                review.run("same-feature", cli="codex", root=ROOT / "mcp-server")
        execute.assert_not_called()
