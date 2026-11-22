"""refactor/single-project-registry: one .agent-projects.json for targets, default and workspaces."""

import asyncio
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server/src"))
sys.path.insert(0, str(ROOT / "scripts"))

from agent_platform_mcp import cli, config, server
from agent_platform_mcp.tools import projects

ALLOW = config.ALLOW_ENV


class RegistryCase(unittest.TestCase):
    """Temp platform ROOT (base/agent-platform) + registry; workspaces are siblings under base.
    The env starts without the deprecated roots."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.root = self.base / "agent-platform"
        self.root.mkdir()
        self.registry = self.root / ".agent-projects.json"
        environment = {k: v for k, v in os.environ.items() if k not in {ALLOW, "TARGET_PROJECT_ROOT"}}
        for patcher in (patch.object(projects, "REGISTRY_FILE", self.registry),
                        patch.object(config, "ROOT", self.root),
                        patch.object(config, "_WARNED", set()),
                        patch.dict(os.environ, environment, clear=True)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.ws = self.base / "ws"
        self.outside = self.base / "outside"
        self.ws.mkdir()
        self.outside.mkdir()

    def dirs(self, *names, parent=None):
        made = []
        for name in names:
            path = (parent or self.ws) / name
            path.mkdir(parents=True, exist_ok=True)
            made.append(path)
        return made

    def cli(self, *argv):
        out = []
        with patch.object(cli, "_print_result", side_effect=out.append):
            code = cli.main(list(argv))
        return code, (out[0] if out else None)

    def data(self):
        return json.loads(self.registry.read_text(encoding="utf-8"))


class MigrateTest(RegistryCase):  # AC-1
    def test_migrate_moves_lines_and_env_then_is_idempotent(self):
        alpha, beta = self.dirs("alpha", "beta")
        os.environ[ALLOW] = str(self.ws)  # unmigrated checkout: env roots are the workspaces
        taken = self.dirs("alpha", parent=self.ws / "elsewhere")[0]
        projects.register(str(taken), "alpha")  # forces the derived ID to collide
        projects.register(str(beta), "svc-beta")
        stray = self.dirs("stray", parent=self.outside)[0]
        legacy = self.root / ".active-project"
        legacy.write_text(f"{alpha}\n{beta}\n{stray}\n{self.base}/missing\n", encoding="utf-8")

        before = self.registry.read_bytes()
        preview = projects.migrate(dry_run=True)
        self.assertEqual((self.registry.read_bytes(), legacy.is_file()), (before, True))  # nothing written
        self.assertEqual(preview["default"], "alpha-2")

        report = projects.migrate()
        data = self.data()
        self.assertEqual(data["version"], 2)
        self.assertEqual(data["default"], "alpha-2")
        self.assertEqual(data["workspaces"], [str(self.ws)])
        self.assertEqual(data["projects"]["alpha-2"]["path"], str(alpha))
        self.assertEqual(report["reused"], [{"project_id": "svc-beta", "path": str(beta)}])
        self.assertEqual({item["reason"] for item in report["skipped"]}, {"outside workspaces", "missing"})
        self.assertNotIn(str(stray), [r["path"] for r in data["projects"].values()])  # listing never widened access
        self.assertFalse(legacy.exists())
        self.assertTrue((self.root / ".active-project.migrated").is_file())
        self.assertIn(ALLOW, report["notice"])
        self.assertEqual(config.target_project_root(), alpha)

        snapshot = self.registry.read_bytes()
        again = projects.migrate()
        self.assertFalse(again["changed"])
        self.assertEqual(self.registry.read_bytes(), snapshot)

    def test_cli_migrate_dry_run(self):
        (self.root / ".active-project").write_text(f"{self.dirs('svc')[0]}\n", encoding="utf-8")
        os.environ[ALLOW] = str(self.ws)
        code, result = self.cli("project-migrate", "--dry-run")
        self.assertEqual((code, result["dry_run"], result["default"]), (0, True, "svc"))
        self.assertFalse(self.registry.exists())
        self.assertTrue((self.root / ".active-project").is_file())


class AllowTest(RegistryCase):  # AC-2
    def setUp(self):
        super().setUp()
        projects.workspace_add(str(self.ws))
        self.registered = self.dirs("proj", parent=self.outside)[0]
        projects.add(str(self.registered))

    def test_workspace_and_registered_subtrees_are_allowed_others_rejected(self):
        inside = self.dirs("svc")[0]
        self.assertEqual(config._ensure_within_allowed_roots(inside), inside)
        nested = self.dirs("sub", parent=self.registered)[0]
        self.assertEqual(config._ensure_within_allowed_roots(nested), nested)
        other = self.dirs("other", parent=self.base)[0]
        with self.assertRaises(RuntimeError):
            config._ensure_within_allowed_roots(other)
        with self.assertRaises(RuntimeError):
            config._ensure_within_allowed_roots(self.outside)  # parent of a registered project

    def test_registered_platform_root_does_not_open_its_subtree(self):
        projects.register(str(self.root), "agent-platform")
        self.assertEqual(config._resolve_project_path(str(self.root)), self.root)
        inner = self.dirs("mcp-server", parent=self.root)[0]
        with self.assertRaises(RuntimeError):
            config._resolve_project_path(str(inner))

    def test_symlink_escapes_are_rejected(self):
        other = self.dirs("other", parent=self.base)[0]
        for link in (self.ws / "link", self.registered / "link"):
            link.symlink_to(other, target_is_directory=True)
            with self.subTest(link=link), self.assertRaises(RuntimeError):
                config._resolve_project_path(str(link))

    def test_registered_path_turned_into_symlink_is_not_followed(self):
        other = self.dirs("other", parent=self.base)[0]
        self.registered.rmdir()
        self.registered.symlink_to(other, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            config._ensure_within_allowed_roots(self.registered)


class McpBoundaryTest(RegistryCase):  # AC-3
    def setUp(self):
        super().setUp()
        projects.workspace_add(str(self.ws))
        self.registered = self.dirs("proj", parent=self.outside)[0]
        projects.add(str(self.registered), project_id="proj")

    def test_mcp_register_rebind_init_stay_inside_workspaces(self):
        stray = self.dirs("stray", parent=self.outside)[0]
        nested = self.dirs("nested", parent=self.registered)[0]
        before = self.registry.read_bytes()
        for path in (stray, nested):
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                server.project_register(str(path), "stray-id")
        with self.assertRaises(RuntimeError):
            server.project_rebind("proj", str(stray))
        for target in (str(self.outside), str(self.registered)):
            with self.subTest(target=target), self.assertRaises(RuntimeError):
                server.project_init("new-svc", "com.example.svc", target_dir=target, git_commit=False)
        self.assertEqual(self.registry.read_bytes(), before)
        self.assertEqual(server.project_register(str(self.dirs("ok")[0]), "ok-id")["project_id"], "ok-id")

    def test_no_mcp_tool_changes_workspaces_or_clones(self):
        names = {tool.name for tool in asyncio.run(server.mcp.list_tools())}
        self.assertFalse({n for n in names if "workspace" in n or "migrate" in n or n == "project_add"})

    def test_mcp_use_selects_registered_projects_only(self):
        unregistered = self.dirs("plain")[0]
        with self.assertRaises(ValueError):
            server.project_use(str(unregistered))
        self.assertEqual(self.data()["default"], "proj")  # unchanged by the rejected call
        self.assertEqual(server.project_use("proj")["path"], str(self.registered))
        with self.assertRaises(ValueError):
            server.project_use(str(self.root))  # the platform itself


class CliTest(RegistryCase):  # AC-4
    def test_add_local_default_and_id_collisions(self):
        a, b = self.dirs("svc", "two")
        other = self.dirs("svc", parent=self.ws / "x")[0]
        projects.workspace_add(str(self.ws))
        self.assertEqual(self.cli("project-add", str(a))[1]["project_id"], "svc")
        self.assertEqual(self.data()["default"], "svc")  # first one becomes the default
        self.assertEqual(self.cli("project-add", str(other))[1]["project_id"], "svc-2")
        with self.assertRaises(ValueError):
            projects.add(str(b), project_id="svc")  # explicit taken ID
        code, result = self.cli("project-add", str(b), "--project-id", "svc-two", "--default")
        self.assertEqual((code, result["default"], self.data()["default"]), (0, True, "svc-two"))
        self.assertTrue(self.cli("project-add", str(a))[1]["reused"])
        self.assertEqual(self.cli("project-use", "svc")[1]["path"], str(a))
        self.assertEqual(self.data()["default"], "svc")
        outside = self.dirs("ext", parent=self.outside)[0]
        self.assertEqual(self.cli("project-add", str(outside))[1]["project_id"], "ext")  # human may add outside

    def test_add_git_url_clones_into_first_workspace(self):
        projects.workspace_add(str(self.ws))
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(argv)
            if argv[:2] == ["git", "clone"]:
                Path(argv[-1]).mkdir()
                return subprocess.CompletedProcess(argv, 0, "", "")
            return subprocess.CompletedProcess(argv, 1, "", "not a repo")

        with patch.object(projects.subprocess, "run", side_effect=fake_run):
            code, result = self.cli("project-add", "https://example.invalid/org/sample-repo.git", "--default")
            with self.assertRaises(RuntimeError):
                projects.add("https://example.invalid/org/other.git", into=str(self.outside))
        self.assertEqual((code, result["path"], result["project_id"]), (0, str(self.ws / "sample-repo"), "sample-repo"))
        self.assertEqual(self.data()["default"], "sample-repo")
        self.assertIn(["git", "clone", "--", "https://example.invalid/org/sample-repo.git", str(self.ws / "sample-repo")],
                      calls)

    def test_workspace_add_remove_list(self):
        second = self.dirs("second", parent=self.base)[0]
        os.environ[ALLOW] = str(self.outside)
        code, added = self.cli("project-workspace", "add", str(self.ws))
        self.assertEqual(added["imported_from_env"], [str(self.outside)])  # env roots are not silently dropped
        self.cli("project-workspace", "add", str(second))
        self.assertEqual(self.cli("project-workspace", "list")[1]["workspaces"],
                         [str(self.outside), str(self.ws), str(second)])
        projects.add(str(self.dirs("svc")[0]))
        removed = self.cli("project-workspace", "remove", str(self.ws))[1]
        self.assertEqual(removed["projects_still_registered"], ["svc"])
        self.assertNotIn(str(self.ws), self.data()["workspaces"])
        with self.assertRaises(FileNotFoundError):
            projects.workspace_add(str(self.base / "missing"))
        with self.assertRaises(ValueError):
            projects.workspace_add("/")


class ResolveTest(RegistryCase):  # AC-5
    def setUp(self):
        super().setUp()
        projects.workspace_add(str(self.ws))
        self.a, self.b = self.dirs("alpha", "beta")
        projects.add(str(self.a), project_id="svc-a", default=True)
        projects.add(str(self.b), project_id="svc-b")

    def test_id_folder_name_path_and_default(self):
        self.assertEqual(config.resolve_project_dir("svc-b"), self.b)
        self.assertEqual(config.resolve_project_dir("beta"), self.b)
        self.assertEqual(config.resolve_project("beta").project_id, "svc-b")
        self.assertEqual(config.resolve_project_dir(str(self.b)), self.b)
        self.assertEqual(config.resolve_project_dir(), self.a)
        with self.assertRaises(FileNotFoundError):
            config.resolve_project_dir("not-registered")

    def test_ambiguous_folder_name_is_an_error(self):
        projects.add(str(self.dirs("alpha", parent=self.ws / "copy")[0]), project_id="copy-alpha")
        with self.assertRaises(RuntimeError):
            config.resolve_project_dir("alpha")


class CompatTest(RegistryCase):  # AC-6
    def test_legacy_active_file_still_selects_with_one_warning(self):
        os.environ[ALLOW] = str(self.ws)
        a, b = self.dirs("a1", "b1")
        (self.root / ".active-project").write_text(f"{b}\n{a}\n", encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(config.active_projects(), [b, a])
            self.assertEqual(config.target_project_root(), b)
        self.assertEqual(err.getvalue().count(".active-project is deprecated"), 1)
        self.assertEqual(err.getvalue().count(f"using the deprecated {ALLOW}"), 1)  # F2: fallback is announced

    def test_v1_registry_is_read_and_upgraded_preserving_fields(self):
        os.environ[ALLOW] = str(self.ws)
        svc = self.dirs("svc")[0]
        record = {"path": str(svc), "git_common_dir": None, "verify_profile_id": None,
                  "registered_at": "2026-01-01T00:00:00+00:00", "skills": {"x": {"v": 1}},
                  "publish": {"target": "none"}}
        self.registry.write_text(json.dumps({"schema": 1, "projects": {"svc": record}}), encoding="utf-8")
        self.assertEqual(config.resolve_project("svc").path, svc)
        projects.use("svc")
        data = self.data()
        self.assertEqual((data["version"], data["default"], data["workspaces"]), (2, "svc", []))
        self.assertEqual(data["projects"]["svc"], record)

    def test_env_left_after_migration_warns_and_is_ignored(self):
        projects.workspace_add(str(self.ws))
        os.environ[ALLOW] = str(self.outside)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(RuntimeError):
            config._ensure_within_allowed_roots(self.dirs("x", parent=self.outside)[0])
        self.assertIn("deprecated", err.getvalue())

    def test_env_fallback_keeps_old_rule_registered_paths_grant_nothing(self):
        os.environ[ALLOW] = str(self.ws)
        with self.assertRaises(RuntimeError):  # CLI cannot register outside the env roots either
            projects.add(str(self.dirs("ext", parent=self.outside)[0]))
        self.assertTrue(config.env_fallback_active())


class ClaudePermissionsTest(RegistryCase):  # AC-7
    def test_permissions_come_from_registry_workspaces_and_outside_projects(self):
        from sync_claude_settings import load_allowed_roots, sync_settings

        projects.workspace_add(str(self.ws))
        projects.add(str(self.dirs("in-ws")[0]))
        ext = self.dirs("ext", parent=self.outside)[0]
        projects.add(str(ext))
        projects.register(str(self.root), "agent-platform")
        os.environ[ALLOW] = "/ignored/when/registry/has/workspaces"
        self.assertEqual(load_allowed_roots(self.root), [self.ws, ext])
        sync_settings(self.root)
        allow = json.loads((self.root / ".claude/settings.local.json").read_text())["permissions"]["allow"]
        self.assertIn(f"Write({ext}/**)", allow)
        self.assertNotIn("Write(/ignored/when/registry/has/workspaces/**)", allow)

    def test_env_fallback_without_workspaces(self):
        from sync_claude_settings import load_allowed_roots

        os.environ[ALLOW] = str(self.ws)
        self.assertEqual(load_allowed_roots(self.root), [self.ws])



def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"})


class IsolationTest(unittest.TestCase):  # REVIEW M-2
    def test_platform_root_and_local_files_are_never_the_real_checkout(self):
        self.assertNotEqual(config.ROOT.resolve(), ROOT.resolve())
        self.assertNotEqual(projects.REGISTRY_FILE.parent.resolve(), ROOT.resolve())
        self.assertFalse(config.platform_relation(ROOT))  # the real checkout is not even related
        (config.ROOT / ".active-project").write_text("/nowhere\n", encoding="utf-8")
        self.assertEqual(config.legacy_active_file(), config.ROOT / ".active-project")


class SubprocessIsolationTest(unittest.TestCase):  # REVIEW M-3
    def test_spawned_cli_reads_the_isolated_root_registry(self):
        self.assertEqual(Path(os.environ["AGENT_PLATFORM_ROOT"]), config.ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp).resolve()
            projects.REGISTRY_FILE.write_text(json.dumps({  # a migrated registry, as after AC-9
                "version": 2, "env_fallback": False, "workspaces": [str(workspace)], "projects": {}}),
                encoding="utf-8")
            result = subprocess.run([sys.executable, "-m", "agent_platform_mcp.cli", "project-list"],
                                    capture_output=True, text=True, timeout=60, check=True,
                                    env={**os.environ, "PYTHONPATH": str(ROOT / "mcp-server/src")})
        listed = json.loads(result.stdout)
        self.assertEqual((listed["workspaces"], listed["env_fallback"]), ([str(workspace)], False))


class WorktreeDefaultTest(RegistryCase):  # REVIEW M-1
    def setUp(self):
        super().setUp()
        self.main = self.dirs("svc")[0]
        _git("init", "-q", cwd=self.main)
        _git("commit", "-q", "--allow-empty", "-m", "init", cwd=self.main)
        self.worktree = self.ws / "svc-wt"
        _git("worktree", "add", "-q", str(self.worktree), cwd=self.main)
        self.worktree = self.worktree.resolve()
        projects.workspace_add(str(self.ws))
        projects.register(str(self.main), "svc", trusted=True)

    def test_migrate_keeps_a_worktree_first_line_as_the_default_checkout(self):
        (self.root / ".active-project").write_text(f"{self.worktree}\n{self.main}\n", encoding="utf-8")
        self.assertEqual(config.target_project_root(), self.worktree)  # before
        report = projects.migrate()
        self.assertEqual((report["default"], report["default_path"]), ("svc", str(self.worktree)))
        self.assertEqual(report["reused"][0]["worktree_of"], str(self.main))
        self.assertEqual(config.target_project_root(), self.worktree)  # after: unchanged
        self.assertEqual(config.resolve_project(None).project_id, "svc")

    def test_use_of_a_worktree_keeps_it_and_the_registered_path_clears_it(self):
        projects.use(str(self.worktree))
        self.assertEqual(config.target_project_root(), self.worktree)
        projects.use("svc")
        self.assertEqual((self.data()["default_path"], config.target_project_root()), (None, self.main))
        projects.use(str(self.worktree))
        projects.unregister("svc")
        self.assertEqual((self.data()["default"], self.data()["default_path"]), (None, None))


    def test_worktree_outside_the_allowlist_never_becomes_the_default(self):  # REVIEW L-7
        ext = self.dirs("ext", parent=self.outside)[0]
        _git("init", "-q", cwd=ext)
        _git("commit", "-q", "--allow-empty", "-m", "init", cwd=ext)
        elsewhere = self.base / "elsewhere" / "ext-wt"
        elsewhere.parent.mkdir()
        _git("worktree", "add", "-q", str(elsewhere), cwd=ext)
        self.assertEqual(self.cli("project-add", str(ext), "--default")[1]["project_id"], "ext")
        before = self.registry.read_bytes()
        with self.assertRaisesRegex(ValueError, "cannot be the default"):
            projects.add(str(elsewhere.resolve()), default=True)
        self.assertEqual(self.registry.read_bytes(), before)  # no success report, nothing written
        self.assertEqual(config.target_project_root(), ext)
        projects.use(str(self.worktree))  # inside a workspace: still allowed
        _git("worktree", "remove", "--force", str(self.worktree), cwd=self.main)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertIsNone(config.target_project_root())
        self.assertIn("no longer exists", err.getvalue())  # a removed default worktree is reported


class MigrateSafetyTest(RegistryCase):  # REVIEW L-1, L-2, SECURITY F2
    def test_skipped_first_line_is_reported_with_the_new_default(self):
        projects.workspace_add(str(self.ws))
        svc = self.dirs("svc")[0]
        (self.root / ".active-project").write_text(f"{self.base}/gone\n{svc}\n", encoding="utf-8")
        report = projects.migrate()
        self.assertEqual(report["default"], "svc")
        self.assertEqual(len(report["notices"]), 1)
        self.assertIn("was skipped (missing)", report["notices"][0])

    def test_pointer_changed_during_migration_is_not_renamed(self):
        projects.workspace_add(str(self.ws))
        legacy = self.root / ".active-project"
        legacy.write_text(f"{self.dirs('svc')[0]}\n", encoding="utf-8")
        real_write = projects._write

        def racing_write(data):
            real_write(data)
            legacy.write_text(legacy.read_text() + f"{self.dirs('late')[0]}\n", encoding="utf-8")

        with patch.object(projects, "_write", racing_write), self.assertRaises(RuntimeError):
            projects.migrate()
        self.assertTrue(legacy.is_file())
        self.assertFalse(list(self.root.glob(".active-project.migrated*")))

    def test_dry_run_never_renames_or_writes(self):
        os.environ[ALLOW] = str(self.ws)
        legacy = self.root / ".active-project"
        legacy.write_text(f"{self.dirs('svc')[0]}\n", encoding="utf-8")
        report = projects.migrate(dry_run=True)
        self.assertTrue(report["renamed"])  # reported only
        self.assertTrue(legacy.is_file())
        self.assertFalse(list(self.root.glob(".active-project.migrated*")))
        self.assertFalse(self.registry.exists())

    def test_migration_turns_the_env_fallback_off_for_good(self):
        os.environ[ALLOW] = str(self.ws)
        self.assertTrue(config.env_fallback_active())
        projects.migrate()
        self.assertFalse(self.data()["env_fallback"])
        self.assertEqual(self.data()["workspaces"], [str(self.ws)])
        with self.assertRaises(ValueError):  # last workspace needs an explicit flag
            projects.workspace_remove(str(self.ws))
        code, _ = self.cli("project-workspace", "remove", str(self.ws), "--allow-empty")
        self.assertEqual(code, 0)
        self.assertEqual((config.workspaces(), config.env_fallback_active()), ((), False))  # env stays off
        with self.assertRaises(RuntimeError):
            config._ensure_within_allowed_roots(self.dirs("svc")[0])
        self.assertEqual(projects.workspace_add(str(self.outside))["imported_from_env"], [])  # not re-imported

    def test_deleted_registry_is_the_only_way_back_to_the_env(self):
        projects.workspace_add(str(self.ws))
        os.environ[ALLOW] = str(self.outside)
        self.assertFalse(config.env_fallback_active())
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.registry.unlink()
            self.assertTrue(config.env_fallback_active())
        self.assertIn(f"using the deprecated {ALLOW}", err.getvalue())

    def test_migrated_checkout_never_falls_back_to_the_env(self):  # SECURITY F8
        from sync_claude_settings import load_allowed_roots

        os.environ[ALLOW] = str(self.ws)
        (self.root / ".active-project").write_text(f"{self.dirs('svc')[0]}\n", encoding="utf-8")
        projects.migrate()
        self.assertTrue(projects.migrated())
        os.environ[ALLOW] = str(self.outside)
        self.registry.unlink()  # deleted (or moved away) after the migration
        self.assertEqual((config.workspaces(), config.env_fallback_active()), ((), False))
        with self.assertRaises(RuntimeError):
            config._ensure_within_allowed_roots(self.outside)
        self.assertEqual(load_allowed_roots(self.root), [])
        self.assertEqual(projects.workspace_add(str(self.ws))["imported_from_env"], [])

    def test_corrupt_marker_is_rejected(self):
        self.registry.write_text(json.dumps({"version": 2, "env_fallback": "no", "projects": {}}), encoding="utf-8")
        with self.assertRaises(ValueError):
            projects._read()


class PlatformSubtreeTest(RegistryCase):  # SECURITY F4
    def test_subtree_is_rejected_even_when_a_workspace_contains_the_checkout(self):
        os.environ[ALLOW] = str(self.base)  # an old env root that contains ROOT
        inner = self.dirs("mcp-server", parent=self.root)[0]
        for call in (config._ensure_within_allowed_roots, config.ensure_within_workspaces):
            with self.subTest(call=call.__name__), self.assertRaises(RuntimeError):
                call(inner)
        with self.assertRaises(RuntimeError):
            config._resolve_project_path(str(inner))
        with self.assertRaises(RuntimeError):  # not created yet: still inside
            config.ensure_within_workspaces(self.root / "new-project")
        self.assertEqual(config._ensure_within_allowed_roots(self.ws), self.ws)  # elsewhere still allowed

    def test_workspaces_and_projects_cannot_be_the_checkout_or_contain_it(self):
        for path in (self.base, self.root, self.dirs("docs", parent=self.root)[0]):
            with self.subTest(path=path), self.assertRaises(ValueError):
                projects.workspace_add(str(path))
        projects.workspace_add(str(self.ws))
        for path in (self.base, self.dirs("skills", parent=self.root)[0]):
            with self.subTest(path=path), self.assertRaises(ValueError):
                projects.register(str(path), "wide", trusted=True)
        os.environ[ALLOW] = str(self.base)
        self.assertEqual(projects.migrate(dry_run=True)["workspaces_rejected_from_env"], [])  # already migrated

    def test_env_root_containing_the_checkout_is_not_imported(self):
        os.environ[ALLOW] = f"{self.base}{os.pathsep}{self.ws}"
        report = projects.migrate()
        self.assertEqual((report["workspaces"], report["workspaces_rejected_from_env"]), ([str(self.ws)], [str(self.base)]))

    def test_case_variant_of_the_checkout_is_recognised(self):
        variant = Path(str(self.root).swapcase())
        if not variant.exists():
            self.skipTest("case-sensitive filesystem: a case variant is a different path")
        inner = self.dirs("mcp-server", parent=self.root)[0]
        projects.workspace_add(str(self.ws))
        self.assertEqual(config.platform_relation(variant / "mcp-server"), "inside")
        self.assertEqual(config._resolve_project_path(str(variant)), self.root)  # self-target only
        with self.assertRaises(RuntimeError):
            config._resolve_project_path(str(variant / inner.name))
        self.assertEqual(projects.register(str(variant), "agent-platform", trusted=True)["path"], str(self.root))
        with self.assertRaises(RuntimeError):  # the registered (canonical) root still opens no subtree
            config._ensure_within_allowed_roots(variant / inner.name)
        with self.assertRaises(ValueError):
            projects.workspace_add(str(Path(str(self.base).swapcase())))


class ClaudeSettingsHardeningTest(RegistryCase):  # SECURITY F1-p2, F2, F5, REVIEW L-5
    def local(self):
        return json.loads((self.root / ".claude/settings.local.json").read_text())["permissions"]

    def test_deny_rules_prune_stale_grants_and_keep_user_entries(self):
        from sync_claude_settings import sync_settings

        stale, root = str(self.outside / "old"), str(self.root).lstrip("/")
        (self.root / ".claude").mkdir()
        (self.root / ".claude/settings.local.json").write_text(json.dumps({"permissions": {
            "additionalDirectories": [stale, "/user/dir"],
            "allow": [f"Read({stale}/**)", f"Write({stale}/**)", f"Edit({stale}/**)", "Bash(custom *)",
                      "Read(/user/dir/**)"],
            "deny": ["Read(//secret)", f"Edit(//{root}/.env*)", f"Write(//{root}/.env*)",  # retired
                     f"Edit(//{root}/.env*.bak)"]}}), encoding="utf-8")
        projects.workspace_add(str(self.ws))
        self.assertTrue(sync_settings(self.root))
        permissions = self.local()
        self.assertEqual(permissions["additionalDirectories"], ["/user/dir", str(self.ws)])
        self.assertNotIn(f"Write({stale}/**)", permissions["allow"])
        self.assertIn("Bash(custom *)", permissions["allow"])
        self.assertNotIn("retired_deny", permissions)
        for rule in (f"Edit(//{root}/.agent-projects.json)", f"Write(//{root}/.agent-projects.json)",
                     f"Write(//{root}/.env)", f"Edit(//{root}/.agent-platform.env)", f"Write(//{root}/.env.local)",
                     f"Edit(//{root}/.claude/settings*.json)", "Read(//secret)", f"Edit(//{root}/.env*.bak)"):
            self.assertIn(rule, permissions["deny"])
        # the generated `.env*` rules are gone, so the tracked .env.example stays editable
        self.assertFalse([rule for rule in permissions["deny"] if rule.endswith("/.env*)")])
        self.assertFalse([rule for rule in permissions["deny"] if ".env.example" in rule])

    def test_env_deny_names_the_files_read_and_the_example_stays_inert(self):  # SECURITY R-5
        import sync_claude_settings as sync

        self.assertEqual(sync.ENV_FILE_NAME, config._AGENT_PLATFORM_ENV_FILE_NAME)
        self.assertEqual(sync.LEGACY_ENV_FILE_NAMES, config._LEGACY_ENV_FILE_NAMES)
        self.assertTrue({".env", ".agent-platform.env", ".env.local"} <= set(sync.PROTECTED))
        self.assertFalse([name for name in sync.PROTECTED if "*" in name and name.startswith(".env")])
        example = (ROOT / ".env.example").read_text(encoding="utf-8")  # setup.sh copies it to .env
        self.assertNotRegex(example, rf"(?m)^\s*(?:export\s+)?{ALLOW}\s*=")

    def test_registered_paths_count_without_workspaces_and_root_or_checkout_never(self):
        from sync_claude_settings import load_allowed_roots

        ext = self.dirs("ext", parent=self.outside)[0]
        self.registry.write_text(json.dumps({"version": 2, "env_fallback": False, "workspaces": ["/", str(self.base)],
                                             "projects": {"ext": {"path": str(ext)}}}), encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(load_allowed_roots(self.root), [ext])
        self.assertIn("not granting /", err.getvalue())
        self.registry.write_text(json.dumps({"version": 2, "env_fallback": False, "workspaces": [],
                                             "projects": {"ext": {"path": str(ext)}}}), encoding="utf-8")
        os.environ[ALLOW] = str(self.ws)  # ignored: the registry is migrated
        self.assertEqual(load_allowed_roots(self.root), [ext])

    def test_corrupt_registry_fails_instead_of_falling_back_to_env(self):
        import sync_claude_settings as sync

        os.environ[ALLOW] = str(self.ws)
        self.registry.write_text("{not json", encoding="utf-8")
        with self.assertRaises(sync.RegistryError):
            sync.load_allowed_roots(self.root)
        result = subprocess.run([sys.executable, str(ROOT / "scripts/sync_claude_settings.py"), "--repo-root",
                                 str(self.root)], capture_output=True, text=True, env=os.environ, timeout=60)
        self.assertEqual(result.returncode, 1)
        self.assertIn("cannot be read", result.stderr)
        self.assertFalse((self.root / ".claude/settings.local.json").exists())

if __name__ == "__main__":
    unittest.main()
