import unittest
from unittest.mock import patch

from test_skill_packages import SkillPackageFixture
from agent_platform_mcp import cli, server
from agent_platform_mcp.tools import projects, skill_packages as packages, skills


class SkillActivationTest(SkillPackageFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.a, self.b = self.root / "project-a", self.root / "project-b"
        for path, key in ((self.a, "project-a"), (self.b, "project-b")):
            path.mkdir()
            projects.register(str(path), key)
        packages.add(str(self.package()))

    def test_enable_disable_two_projects_preserves_products(self):
        product = self.a / "product.py"
        product.write_text("product = 1\n")
        server.skill_enable("sample-skill", "project-a")
        server.skill_enable("sample-skill", "project-b")
        with self.assertRaises(RuntimeError):
            packages.remove("sample-skill")
        for backend, relative in skills.NATIVE.items():
            self.assertTrue((self.a / relative / "sample-skill" / packages.MARKER).exists())
            self.assertIn("sample-skill", skills.active_versions("project-a", backend)["skill_versions"])
        result = server.skill_disable("sample-skill", "project-a")
        self.assertTrue(result["complete"])
        self.assertTrue((self.b / ".agents/skills/sample-skill/SKILL.md").exists())
        self.assertEqual(product.read_text(), "product = 1\n")
        with patch.object(cli, "_print_result"):
            self.assertEqual(cli.main(["skill", "disable", "sample-skill", "project-b"]), 0)
        packages.remove("sample-skill")
        self.assertTrue(product.exists())

    def test_user_modified_is_retained_and_not_expected_loaded(self):
        skills.enable("sample-skill", "project-a")
        path = self.a / ".agents/skills/sample-skill/SKILL.md"
        original = path.read_text()
        path.write_text(original + "My change\n")
        self.assertEqual(skills.active_versions("project-a", "codex")["skill_versions"], {})
        result = skills.disable("sample-skill", "project-a")
        self.assertFalse(result["complete"])
        self.assertEqual(result["materialized"]["codex"], "user_modified")
        self.assertTrue(path.exists())
        with self.assertRaises(RuntimeError):
            packages.remove("sample-skill")
        path.write_text(original)
        self.assertTrue(skills.disable("sample-skill", "project-a")["complete"])

    def test_unmanaged_collision_and_dependency_guard(self):
        path = self.a / ".claude/skills/sample-skill"
        path.mkdir(parents=True)
        self.assertTrue(server.skill_list("project-a")["packages"][0]["shadowed"])
        with self.assertRaises(FileExistsError):
            skills.enable("sample-skill", "project-a")
        self.assertFalse((self.a / ".agents").exists())
        packages.add(str(self.package("child-skill", depends_on=["sample-skill"])))
        with self.assertRaises(RuntimeError):
            skills.enable("child-skill", "project-b")
        skills.enable("sample-skill", "project-b")
        skills.enable("child-skill", "project-b")
        with self.assertRaises(RuntimeError):
            skills.disable("sample-skill", "project-b")

    def test_activation_and_disable_rollback(self):
        with patch.object(projects, "_write", side_effect=OSError("disk failure")), self.assertRaises(OSError):
            skills.enable("sample-skill", "project-a")
        self.assertFalse((self.a / ".claude").exists())
        self.assertFalse((self.a / ".agents").exists())
        skills.enable("sample-skill", "project-a")
        with patch.object(projects, "_write", side_effect=OSError("disk failure")), self.assertRaises(OSError):
            skills.disable("sample-skill", "project-a")
        for relative in skills.NATIVE.values():
            self.assertTrue((self.a / relative / "sample-skill/SKILL.md").exists())

    def test_active_project_rebind_unregister_and_allowlist_guards(self):
        skills.enable("sample-skill", "project-a")
        with self.assertRaises(RuntimeError):
            projects.unregister("project-a")
        moved = self.root / "moved"
        moved.mkdir()
        with self.assertRaises(RuntimeError):
            projects.rebind("project-a", str(moved))
        skills.disable("sample-skill", "project-a")
        with patch.dict("os.environ", {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": str(self.b)}):
            with self.assertRaises(RuntimeError):
                projects.resolve("project-a")
