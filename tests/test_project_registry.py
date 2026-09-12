import json
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

from agent_platform_mcp import cli, config, server
from agent_platform_mcp.tools import feature, handoff, projects


class ProjectRegistryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.registry = self.base / ".agent-projects.json"
        registry = patch.object(projects, "REGISTRY_FILE", self.registry)
        registry.start()
        self.addCleanup(registry.stop)
        environment = patch.dict(os.environ, {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": str(self.base)})
        environment.start()
        self.addCleanup(environment.stop)
        self.a = self.base / "a/service"
        self.b = self.base / "b/service"
        self.a.mkdir(parents=True)
        self.b.mkdir(parents=True)

    def git(self, *args):
        return subprocess.run(["git", "-c", "user.email=test@example.invalid", "-c", "user.name=Fixture", *args],
                              cwd=self.a, check=True, capture_output=True, text=True, timeout=30)

    def test_generated_ids_separate_same_basename_and_preserve_environment(self):
        before = dict(os.environ)
        first = projects.register(str(self.a))
        second = projects.register(str(self.b))
        self.assertNotEqual(first["project_id"], second["project_id"])
        self.assertTrue(first["project_id"].startswith("project-"))
        self.assertEqual(config.resolve_project_dir(first["project_id"]), self.a)
        self.assertEqual(config.resolve_project_dir(second["project_id"]), self.b)
        self.assertEqual(config.resolve_project(self.a).project_id, first["project_id"])
        self.assertEqual(dict(os.environ), before)

    def test_explicit_root_precedes_active_fallback(self):
        projects.register(str(self.a), "service-a")
        with patch.dict(os.environ, {"TARGET_PROJECT_ROOT": str(self.b)}):
            self.assertEqual(config.resolve_project_dir(), self.b)
            self.assertEqual(config.resolve_project_dir("service-a"), self.a)

    def test_registered_profile_is_used_and_explicit_override_wins(self):
        cfg = {"verify_profiles": {
            "fixture": {"argv": [sys.executable, "-c", "from pathlib import Path; Path('verified').write_text('ok')"]},
            "failure": {"argv": [sys.executable, "-c", "raise SystemExit(1)"]},
        }}
        with patch.object(config, "agent_config", return_value=cfg), patch.object(feature, "agent_config", return_value=cfg):
            projects.register(str(self.a), "service-a", "fixture")
            feature.scaffold("small-feature", root="service-a")
            result = feature.gate_check("small-feature", root="service-a", verify=True)
            self.assertEqual(result["project_id"], "service-a")
            self.assertEqual(result["verify_profile_id"], "fixture")
            self.assertEqual(result["verification_status"], "passed")
            self.assertTrue((self.a / "verified").is_file())
            self.assertFalse((self.b / "verified").exists())
            result = feature.gate_check("small-feature", root="service-a", verify=True, verify_profile="failure")
            self.assertEqual(result["verification_status"], "failed")

    def test_real_worktree_keeps_requested_path_and_shared_identity(self):
        self.git("init", "-q")
        (self.a / "sample.txt").write_text("base")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        projects.register(str(self.a), "service-a")
        worktree = self.base / "worktree"
        self.git("worktree", "add", "--detach", str(worktree), "HEAD")
        context = config.resolve_project(str(worktree))
        self.assertEqual(context.project_id, "service-a")
        self.assertEqual(context.path, worktree)
        feature.scaffold("sample-feature", root=worktree)
        self.assertTrue((worktree / "docs/features/sample-feature/PRD.md").is_file())
        self.assertFalse((self.a / "docs").exists())
        with self.assertRaisesRegex(ValueError, "already registered"):
            projects.register(str(worktree), "other-id")

    def test_clone_is_not_automatically_the_same_identity(self):
        self.git("init", "-q")
        (self.a / "sample.txt").write_text("base")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        projects.register(str(self.a), "service-a")
        clone = self.base / "clone"
        self.git("clone", "--quiet", str(self.a), str(clone))
        self.assertIsNone(config.resolve_project(clone).project_id)

    def test_same_feature_verifies_in_two_registered_roots(self):
        cfg = {"verify_profiles": {"fixture": {"argv": [sys.executable, "-c",
                "from pathlib import Path; Path('verified').write_text(str(Path.cwd()))"]}}}
        with patch.object(config, "agent_config", return_value=cfg), patch.object(feature, "agent_config", return_value=cfg):
            for key, path in (("service-a", self.a), ("service-b", self.b)):
                projects.register(str(path), key, "fixture")
                feature.scaffold("same-feature", root=key)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda key: feature.gate_check("same-feature", root=key, verify=True),
                                        ["service-a", "service-b"]))
            self.assertTrue(all(result["verification_status"] == "passed" for result in results))
            self.assertEqual((self.a / "verified").read_text(), str(self.a))
            self.assertEqual((self.b / "verified").read_text(), str(self.b))

    def test_lock_symlink_and_missing_profile_are_not_ignored(self):
        lock = self.registry.with_suffix(".lock")
        lock.symlink_to(self.a / "unrelated")
        with self.assertRaisesRegex(ValueError, "symlink"):
            projects.register(str(self.a))
        lock.unlink()
        projects.register(str(self.a), "service-a", "pytest")
        feature.scaffold("small-feature", root="service-a")
        with patch.object(feature, "agent_config", return_value={}):
            result = feature.gate_check("small-feature", root="service-a", verify=True)
        self.assertEqual(result["verification_status"], "error")
        self.assertFalse(result["passed"])

    def test_rebind_after_move_preserves_identity_and_profile(self):
        projects.register(str(self.a), "service-a", "pytest")
        moved = self.base / "renamed"
        self.a.rename(moved)
        with self.assertRaises(FileNotFoundError):
            config.resolve_project_dir("service-a")
        projects.rebind("service-a", str(moved))
        context = config.resolve_project("service-a")
        self.assertEqual(context.path, moved)
        self.assertEqual(context.verify_profile_id, "pytest")

    def test_duplicate_id_path_and_rebind_collision_are_rejected(self):
        projects.register(str(self.a), "service-a")
        for path, key in ((self.b, "service-a"), (self.a, "other-id")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                projects.register(str(path), key)
        projects.register(str(self.b), "service-b")
        with self.assertRaises(ValueError):
            projects.rebind("service-a", str(self.b))

    def test_resolution_and_rebind_recheck_allowlist(self):
        projects.register(str(self.a), "service-a")
        with patch.dict(os.environ, {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": str(self.b)}):
            with self.assertRaises(RuntimeError):
                config.resolve_project_dir("service-a")
            with self.assertRaises(RuntimeError):
                projects.rebind("service-a", str(self.a))

    def test_unregister_only_removes_metadata(self):
        projects.register(str(self.a), "service-a")
        marker = self.a / "keep.txt"
        marker.write_text("keep")
        projects.unregister("service-a")
        self.assertEqual(projects.list_projects()["projects"], [])
        self.assertEqual(marker.read_text(), "keep")
        self.assertIsNone(config.resolve_project(self.a).project_id)

    def test_atomic_write_failure_preserves_existing_registry(self):
        projects.register(str(self.a), "service-a")
        before = self.registry.read_bytes()
        with patch.object(projects.os, "replace", side_effect=OSError("injected")):
            with self.assertRaises(OSError):
                projects.register(str(self.b), "service-b")
        self.assertEqual(self.registry.read_bytes(), before)
        self.assertEqual(list(self.base.glob(".agent-projects.json.*")), [])

    def test_concurrent_registration_does_not_lose_updates(self):
        paths = [self.base / f"project-{n}" for n in range(6)]
        for path in paths:
            path.mkdir()
        with ThreadPoolExecutor(max_workers=6) as pool:
            entries = list(pool.map(lambda p: projects.register(str(p)), paths))
        self.assertEqual(len(projects.list_projects()["projects"]), 6)
        self.assertEqual(len({entry["project_id"] for entry in entries}), 6)

    def test_invalid_schema_and_symlink_storage_are_not_overwritten(self):
        self.registry.write_text('{"schema": 99, "projects": {}}')
        with self.assertRaises(ValueError):
            projects.register(str(self.a))
        self.assertEqual(json.loads(self.registry.read_text())["schema"], 99)
        self.registry.unlink()
        self.registry.symlink_to(self.a / "unrelated.json")
        with self.assertRaisesRegex(ValueError, "symlink"):
            projects.list_projects()

    def test_invalid_id_profile_and_unknown_rebind_fail(self):
        with self.assertRaises(ValueError):
            projects.register(str(self.a), "../../outside")
        with self.assertRaises(ValueError):
            projects.register(str(self.a), verify_profile="missing-profile")
        with self.assertRaises(ValueError):
            projects.rebind("missing-id", str(self.a))

    def test_cli_mcp_and_handoff_use_same_registry(self):
        with patch.object(cli, "_print_result"):
            self.assertEqual(cli.main(["project-register", str(self.a), "--project-id", "service-a"]), 0)
        feature.scaffold("small-feature", root="service-a")
        result = handoff.validate("planner", "reviewer", "small-feature", root="service-a")
        self.assertEqual(result["project_id"], "service-a")
        self.assertEqual(result["project_dir"], str(self.a))
        self.assertEqual(server.project_list()["projects"][0]["project_id"], "service-a")
        server.project_unregister("service-a")
        self.assertEqual(projects.list_projects()["projects"], [])
