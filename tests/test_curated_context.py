import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp-server/src"))
from agent_platform_mcp.tools import runner


class CuratedContextTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.item = self.root / "docs/features/example"
        self.item.mkdir(parents=True)
        (self.root / "AGENTS.md").write_text(
            "# Guide\n## Core Policy\ncore-policy\n## Other\nexcluded-policy\n"
            "## Security Baseline\nsecurity-policy\n## Constraints\nconstraints-policy\n")
        mock = patch.object(runner, "ROOT", self.root)
        mock.start()
        self.addCleanup(mock.stop)

    def test_only_policy_sections_and_current_metadata_are_injected(self):
        artifact = self.item / "PRD.md"
        artifact.write_text("---\nstatus: approved\n---\n# Current requirement\nprivate-body\n")
        unrelated = self.root / "docs/features/unrelated/DECISIONS.md"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text("# example unrelated\nnever-inject\n")
        (self.item / "credentials.md").write_text("# do-not-read\n")
        block, sources = runner.context_block("example", self.root)
        for expected in ("core-policy", "security-policy", "constraints-policy", "Current requirement", '"status": "approved"'):
            self.assertIn(expected, block)
        for excluded in ("excluded-policy", "private-body", "never-inject", "unrelated", "do-not-read"):
            self.assertNotIn(excluded, block)
        self.assertEqual(sources, [str(self.root / "AGENTS.md"), str(artifact)])

    def test_explicit_decisions_are_bounded_and_body_is_excluded(self):
        refs = []
        for i in range(4):
            path = self.root / f"docs/refactor/decision-{i}/DECISIONS.md"
            path.parent.mkdir(parents=True)
            path.write_text(f"# Decision {i}\nbody-only-{i}\n")
            refs.append(str(path.relative_to(self.root)))
        block, sources = runner.context_block("example", self.root, decision_paths=tuple(refs))
        self.assertEqual(len(sources), 4)
        self.assertIn("Decision 2", block)
        self.assertNotIn("Decision 3", block)
        self.assertNotIn("body-only", block)
        with self.assertRaises(ValueError):
            runner.context_block("example", self.root, decision_paths=("docs/../DECISIONS.md",))

    def test_symlinks_and_missing_required_policy_fail_closed(self):
        (self.item / "PRD.md").symlink_to(self.root / "AGENTS.md")
        with self.assertRaises(ValueError):
            runner.context_block("example", self.root)
        (self.root / "AGENTS.md").write_text("## Core Policy\nonly-one\n")
        with self.assertRaises(ValueError):
            runner.context_block("example", self.root)

    def test_metadata_limits_and_invalid_status(self):
        (self.item / "PRD.md").write_text("---\nstatus: unexpected\n---\n# " + "x" * 1000)
        block, _ = runner.context_block("example", self.root)
        self.assertIn('"status": "unknown"', block)
        self.assertNotIn("x" * 241, block)
        for limit in (-1, 4, True):
            with self.assertRaises(ValueError):
                runner.context_block("example", self.root, max_decisions=limit)
