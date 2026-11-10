"""Single .env, default-target switching and per-request Confluence project."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server/src"))
sys.path.insert(0, str(ROOT / "scripts"))

from agent_platform_mcp import cli, config, server
from agent_platform_mcp.tools import confluence, projects

ALLOW = "AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS"


class EnvFileTest(unittest.TestCase):
    def roots(self, files: dict[str, str]) -> list[Path]:
        from sync_claude_settings import load_allowed_roots

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            for name, value in files.items():
                (repo / name).write_text(f'{ALLOW}="{value}"\n', encoding="utf-8")
            with patch.dict(os.environ, {ALLOW: ""}):
                return load_allowed_roots(repo)

    def test_env_is_the_single_source(self):
        self.assertEqual(config._AGENT_PLATFORM_ENV_FILE_NAME, ".env")
        self.assertEqual(self.roots({".env": "/srv/new"}), [Path("/srv/new").resolve()])

    def test_legacy_files_still_read_but_env_wins(self):
        self.assertEqual(self.roots({".agent-platform.env": "/srv/old"}), [Path("/srv/old").resolve()])
        self.assertEqual(self.roots({".agent-platform.env": "/srv/old", ".env": "/srv/new"}),
                         [Path("/srv/new").resolve()])

    def test_example_lists_every_consumed_key_and_no_target_override(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        for key in (ALLOW, "CONFLUENCE_URL", "CONFLUENCE_EMAIL", "CONFLUENCE_API_TOKEN", "APIDOG_API_TOKEN"):
            self.assertIn(key, text)
        self.assertNotIn("TARGET_PROJECT_ROOT", text)


class TrackedSkillSourceTest(unittest.TestCase):
    def test_every_package_is_registered_without_machine_paths(self):
        import json

        registry = json.loads((ROOT / "skills/registry.json").read_text(encoding="utf-8"))["packages"]
        on_disk = sorted(path.name for path in (ROOT / "skills/packages").iterdir() if path.is_dir())
        self.assertEqual(sorted(registry), on_disk)  # setup installs from the registry
        self.assertEqual({record["source"] for record in registry.values()}, {"local"})

    def test_tracked_packages_match_their_registered_hash(self):
        from agent_platform_mcp.tools import skill_packages as packages

        registry = packages.read()["packages"]
        drifted = [key for key, record in registry.items()
                   if packages.fingerprint(packages.PACKAGES / key) != record["content_hash"]]
        self.assertEqual(drifted, [])  # a drifted package cannot be enabled by setup


class ProjectUseTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        environment = {key: value for key, value in os.environ.items() if key != "TARGET_PROJECT_ROOT"}
        environment[ALLOW] = str(self.base / "work")
        for patcher in (patch.object(projects, "REGISTRY_FILE", self.base / ".agent-projects.json"),
                        patch.object(config, "ROOT", self.base),
                        patch.dict(os.environ, environment, clear=True)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.a, self.b = self.base / "work/a", self.base / "work/b"
        for path, key in ((self.a, "svc-a"), (self.b, "svc-b")):
            path.mkdir(parents=True)
            projects.register(str(path), key)

    def test_use_switches_default_target_and_list_marks_it(self):
        self.assertIsNone(projects.list_projects()["active_path"])
        self.assertEqual(server.project_use("svc-a")["path"], str(self.a))
        with patch.object(cli, "_print_result"):
            self.assertEqual(cli.main(["project-use", "svc-b"]), 0)
        self.assertEqual(config.target_project_root(), self.b)
        listed = projects.list_projects()
        self.assertEqual(listed["active_path"], str(self.b))
        self.assertEqual({item["project_id"]: item["active"] for item in listed["projects"]},
                         {"svc-a": False, "svc-b": True})

    def test_active_file_lists_several_targets_first_is_default(self):
        (self.base / ".active-project").write_text(f"\n# default\n{self.b}\n{self.a}\n{self.b}\n", encoding="utf-8")
        self.assertEqual(config.active_projects(), [self.b, self.a])
        self.assertEqual(config.target_project_root(), self.b)
        listed = projects.list_projects()["active_targets"]
        self.assertEqual([(item["name"], item["default"], item["project_id"]) for item in listed],
                         [("b", True, "svc-b"), ("a", False, "svc-a")])

    def test_listed_target_is_selected_by_folder_name_without_registration(self):
        extra = self.base / "work/extra"
        extra.mkdir()
        (self.base / ".active-project").write_text(f"{self.a}\n{extra}\n", encoding="utf-8")
        self.assertEqual(config.resolve_project_dir("extra"), extra)
        self.assertEqual(config.resolve_project_dir(None), self.a)
        with self.assertRaises(FileNotFoundError):
            config.resolve_project_dir("not-listed")
        outside = self.base / "outside"
        outside.mkdir()
        (self.base / ".active-project").write_text(f"{self.a}\n{outside}\n", encoding="utf-8")
        with self.assertRaises(RuntimeError):  # listing a path does not bypass the allowlist
            config.resolve_project_dir("outside")

    def test_use_promotes_and_keeps_the_other_targets(self):
        (self.base / ".active-project").write_text(f"{self.a}\n{self.b}\n", encoding="utf-8")
        self.assertEqual(projects.use("b")["path"], str(self.b))
        self.assertEqual(config.active_projects(), [self.b, self.a])
        projects.use("svc-a")
        self.assertEqual(config.active_projects(), [self.a, self.b])

    def test_use_rejects_unknown_and_out_of_allowlist(self):
        with self.assertRaises(FileNotFoundError):
            projects.use("missing")
        with patch.dict(os.environ, {ALLOW: str(self.base / "elsewhere")}):
            with self.assertRaises(RuntimeError):
                projects.use("svc-a")
        self.assertFalse((self.base / ".active-project").exists())

    def test_add_lists_a_local_path_and_keeps_the_default(self):
        extra = self.base / "work/extra"
        extra.mkdir()
        self.assertTrue(projects.add(str(self.a))["default"])  # empty list: first becomes default
        added = projects.add(str(extra))
        self.assertEqual((added["default"], added["cloned_from"]), (False, None))
        self.assertEqual(config.active_projects(), [self.a, extra])
        projects.add(str(extra))  # idempotent
        with patch.object(cli, "_print_result"):
            self.assertEqual(cli.main(["project-add", str(self.b), "--default"]), 0)
        self.assertEqual(config.active_projects(), [self.b, self.a, extra])

    def test_add_clones_a_git_url_into_the_allowlist_and_reuses_it(self):
        import subprocess

        source = self.base / "remote/sample-repo.git"
        source.mkdir(parents=True)
        git = ["git", "-c", "user.email=test@example.invalid", "-c", "user.name=Fixture", "-c", "init.defaultBranch=main"]
        subprocess.run([*git, "init", "-q"], cwd=source, check=True)
        (source / "README.md").write_text("fixture\n")
        subprocess.run([*git, "add", "."], cwd=source, check=True)
        subprocess.run([*git, "commit", "-qm", "init"], cwd=source, check=True)
        url = source.as_uri()
        result = projects.add(url)
        clone = self.base / "work/sample-repo"
        self.assertEqual((result["path"], result["cloned_from"]), (str(clone), url))
        self.assertTrue((clone / "README.md").is_file())
        self.assertEqual(projects.add(url)["path"], str(clone))  # existing clone of the same URL is reused
        self.assertEqual(config.resolve_project_dir("sample-repo"), clone)
        with self.assertRaises(RuntimeError):  # --into outside the allowlist
            projects.add(url, into=str(self.base / "outside"))
        (self.base / "work/other").mkdir()
        with self.assertRaises(FileExistsError):
            projects.add((self.base / "remote/other.git").as_uri())

    def test_add_treats_option_like_or_unsupported_refs_as_paths(self):
        for ref in ("--upload-pack=touch x", "ext::sh -c x", "http://plain.example/repo.git"):
            self.assertFalse(projects._is_git_url(ref))
            with self.assertRaises(FileNotFoundError):
                projects.add(ref)
        for ref in ("https://github.com/org/repo.git", "git@github.com:org/repo.git", "ssh://git@host/org/repo"):
            self.assertTrue(projects._is_git_url(ref))

    def test_confluence_sync_reads_requested_project_not_active(self):
        projects.use("svc-a")
        (self.b / "docs/features/only-in-b").mkdir(parents=True)
        missing = confluence.sync_feature("SPACE", "Parent", "only-in-b")
        self.assertIn(str(self.a), missing["error"])
        found = confluence.sync_feature("SPACE", "Parent", "only-in-b", root="svc-b")
        self.assertEqual(found["results"], [])
        self.assertIn(str(self.b), found["warning"])


if __name__ == "__main__":
    unittest.main()
