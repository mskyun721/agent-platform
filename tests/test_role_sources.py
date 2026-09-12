import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sync_claude_settings as sync


class RoleSourceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        (self.repo / "standards/agents").mkdir(parents=True)
        (self.repo / ".claude/agents").mkdir(parents=True)

    def fixture(self, role="reviewer"):
        source = self.repo / f"standards/agents/{role}.md"
        adapter = self.repo / f".claude/agents/{role}.md"
        source.write_text("# Role\nShared instructions.\n")
        adapter.write_text(f"---\nname: {role}\ntools: Read\nmodel: sonnet\n---\nOld instructions.\n")
        return source, adapter

    def test_all_shipped_adapters_match_sources(self):
        for role in sync.ROLES:
            with self.subTest(role=role):
                self.assertEqual(sync.generated_body(ROOT, role), sync.canonical_body(ROOT, role))
        self.assertEqual(sync.sync_agent_bodies(ROOT, check=True), [])

    def test_generation_preserves_header_and_is_idempotent(self):
        _, adapter = self.fixture()
        header = sync._FM.match(adapter.read_text()).group(0)
        self.assertEqual(sync.sync_agent_bodies(self.repo), ["reviewer.md"])
        self.assertTrue(adapter.read_text().startswith(header))
        self.assertEqual(sync.generated_body(self.repo, "reviewer"), sync.canonical_body(self.repo, "reviewer"))
        self.assertEqual(sync.sync_agent_bodies(self.repo), [])

    def test_check_never_writes(self):
        _, adapter = self.fixture()
        old = adapter.read_bytes()
        self.assertEqual(sync.sync_agent_bodies(self.repo, check=True), ["reviewer.md"])
        self.assertEqual(adapter.read_bytes(), old)

    def test_preflight_error_preserves_other_adapters(self):
        _, first = self.fixture("planner")
        _, second = self.fixture("reviewer")
        original = first.read_bytes()
        second.write_text("no header")
        with self.assertRaises(ValueError):
            sync.sync_agent_bodies(self.repo)
        self.assertEqual(first.read_bytes(), original)

    def test_missing_adapter_is_not_created_without_permissions(self):
        _, adapter = self.fixture()
        adapter.unlink()
        with self.assertRaises(FileNotFoundError):
            sync.sync_agent_bodies(self.repo)
        self.assertFalse(adapter.exists())

    def test_empty_source_and_unknown_role_are_rejected(self):
        source, _ = self.fixture()
        source.write_text(" ")
        with self.assertRaises(ValueError):
            sync.sync_agent_bodies(self.repo)
        with self.assertRaises(ValueError):
            sync.canonical_body(self.repo, "../../outside")

    def test_symlinks_are_not_followed(self):
        source, adapter = self.fixture()
        source.unlink()
        source.symlink_to(adapter)
        with self.assertRaisesRegex(ValueError, "symlink"):
            sync.sync_agent_bodies(self.repo)

    def test_model_update_never_changes_body(self):
        _, adapter = self.fixture()
        adapter.write_text("---\nname: reviewer\ntools: Read\n---\nmodel: old\n")
        self.assertEqual(sync.sync_agent_models(self.repo, {"reviewer": "new"}), [])
        self.assertIn("model: old", adapter.read_text())

    def test_model_injection_and_role_escape_are_rejected(self):
        self.fixture()
        for models in ({"../outside": "sonnet"}, {"reviewer": "sonnet\ntools: Bash"}):
            with self.subTest(models=models), self.assertRaises(ValueError):
                sync.sync_agent_models(self.repo, models)

    def test_agents_only_and_check_do_not_create_local_permissions(self):
        self.fixture()
        command = [sys.executable, str(ROOT / "scripts/sync_claude_settings.py"), "--repo-root", str(self.repo)]
        check = subprocess.run([*command, "--check"], capture_output=True, timeout=15)
        self.assertEqual(check.returncode, 1)
        generated = subprocess.run([*command, "--agents-only"], capture_output=True, timeout=15)
        self.assertEqual(generated.returncode, 0, generated.stderr)
        check = subprocess.run([*command, "--check"], capture_output=True, timeout=15)
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertFalse((self.repo / ".claude/settings.local.json").exists())
