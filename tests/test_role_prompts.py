import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server/src"))

from agent_platform_mcp.tools import audit, backend, plan, qa, release, review, runner


class RolePromptTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name).resolve()
        self.feature_dir = self.target / "docs/features/example"
        self.feature_dir.mkdir(parents=True)
        env = patch.dict(os.environ, {"TARGET_PROJECT_ROOT": str(self.target),
                                     "AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": str(self.target)})
        env.start()
        self.addCleanup(env.stop)
        self.wrappers = [("planner", plan, {"requirements": "small feature"}),
                         ("backend", backend, {}), ("reviewer", review, {}),
                         ("security", audit, {}), ("qa", qa, {}), ("cicd", release, {})]

    def test_all_wrappers_embed_exact_canonical_source_and_keep_dry_run_read_only(self):
        with patch.object(runner, "run_cli", side_effect=AssertionError("dry run must not execute")):
            for role, module, kwargs in self.wrappers:
                with self.subTest(role=role):
                    result = module.run("example", cli="codex", dry_run=True, **kwargs)
                    prompt = result["command"][-1]
                    source = (ROOT / f"standards/agents/{role}.md").read_text().strip()
                    self.assertIn(source, prompt)
                    self.assertEqual(prompt.count(source), 1)
                    self.assertEqual(result["prompt_sources"][:2], ["AGENTS.md", f"standards/agents/{role}.md"])
                    self.assertIn(str(ROOT / "AGENTS.md"), result["prompt_sources"])
                    self.assertIn(str(self.target), prompt)
                    self.assertIn(str(ROOT / "AGENTS.md"), prompt)
                    self.assertIn("# Task", prompt)
        self.assertEqual(list(self.feature_dir.iterdir()), [])

    def test_missing_sources_fail_before_execution(self):
        with patch.object(runner, "ROOT", self.target), patch.object(runner, "run_cli") as execute:
            for role, module, kwargs in self.wrappers:
                with self.subTest(role=role), self.assertRaises(FileNotFoundError):
                    module.run("example", cli="codex", **kwargs)
        execute.assert_not_called()

    def test_empty_and_symlinked_sources_are_rejected(self):
        source = self.target / "standards/agents/reviewer.md"
        source.parent.mkdir(parents=True)
        source.write_text(" ")
        with patch.object(runner, "ROOT", self.target):
            with self.assertRaisesRegex(ValueError, "empty"):
                runner.role_prompt("reviewer", task="review", context="fixture")
            source.unlink()
            source.symlink_to(ROOT / "standards/agents/reviewer.md")
            with self.assertRaisesRegex(ValueError, "symlink"):
                runner.role_prompt("reviewer", task="review", context="fixture")

    def test_unknown_role_cannot_escape_source_directory(self):
        with self.assertRaises(ValueError):
            runner.role_prompt("../../outside", task="x", context="y")

    def test_release_wrapper_is_document_only(self):
        result = release.run("example", cli="codex", dry_run=True)
        self.assertIn("do not push, create PRs, merge, or deploy", result["command"][-1])

    def test_unknown_language_does_not_default_to_kotlin(self):
        self.assertEqual(runner.coding_style_path("Python (mcp-server)"), "standards/coding-style.md")
        self.assertEqual(runner.coding_style_path("Kotlin/Spring"), "standards/coding-style-kotlin.md")

    def test_stdout_transport_is_preserved_for_reviews(self):
        for module, filename in ((review, "REVIEW.md"), (audit, "SECURITY-AUDIT.md")):
            with self.subTest(filename=filename):
                result = module.run("example", cli="codex", dry_run=True)
                self.assertIn(f"stdout Markdown only; wrapper writes {filename}", result["command"][-1])
