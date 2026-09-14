import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp-server/src"))
from agent_platform_mcp import cli, server
from agent_platform_mcp.tools import projects, skill_packages as packages


class SkillPackageTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        for mock in (patch.object(packages, "PACKAGES", self.root / "managed/packages"),
                     patch.object(packages, "REGISTRY", self.root / "managed/registry.json"),
                     patch.object(projects, "REGISTRY_FILE", self.root / ".agent-projects.json"),
                     patch.dict(os.environ, {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": str(self.root)})):
            mock.start()
            self.addCleanup(mock.stop)

    def package(self, name="sample-skill", **extra):
        source = self.root / name
        source.mkdir()
        (source / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Test fixture skill\n---\nFixture instructions.\n")
        (source / "skill.json").write_text(json.dumps({"id": name, "version": "1.0.0",
            "supports": ["claude", "codex"], **extra}))
        return source

    def test_add_list_remove_preserves_source_and_never_executes(self):
        source = self.package()
        sentinel = self.root / "executed"
        (source / "install.sh").write_text(f"#!/bin/sh\ntouch {sentinel}\n")
        result = server.skill_add(str(source))
        self.assertEqual(result["content_hash"], packages.fingerprint(source))
        self.assertFalse(sentinel.exists())
        self.assertEqual(len(server.skill_list()["packages"]), 1)
        with self.assertRaises(FileExistsError):
            packages.add(str(source))
        with patch.object(cli, "_print_result"):
            self.assertEqual(cli.main(["skill", "remove", "sample-skill"]), 0)
        self.assertTrue(source.is_dir())
        self.assertEqual(packages.list_skills()["packages"], [])

    def test_dependency_and_mutation_protection(self):
        packages.add(str(self.package("base-skill")))
        packages.add(str(self.package("child-skill", depends_on=["base-skill"])))
        with self.assertRaises(RuntimeError):
            packages.remove("base-skill")
        packages.remove("child-skill")
        path = packages.PACKAGES / "base-skill/SKILL.md"
        path.write_text(path.read_text() + "User edit\n")
        with self.assertRaises(RuntimeError):
            packages.remove("base-skill")
        self.assertTrue(path.exists())

    def test_invalid_metadata_and_missing_dependency(self):
        for i, extra in enumerate(({"supports": []}, {"depends_on": ["missing"]},
                                   {"requires_tools": "Bash"}, {"id": "../escape"})):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                packages.add(str(self.package(f"invalid-{i}", **extra)))
        source = self.package("missing-skill")
        (source / "SKILL.md").unlink()
        with self.assertRaises(ValueError):
            packages.add(str(source))

    def test_symlinks_and_protected_files_rejected_before_read(self):
        source = self.package()
        link = source / "link"
        link.symlink_to(self.root)
        with self.assertRaises(ValueError):
            packages.add(str(source))
        link.unlink()
        (source / ".env").touch()
        with self.assertRaises(ValueError):
            packages.add(str(source))

    def test_copy_and_registry_failure_roll_back(self):
        source = self.package()
        real_copy = packages.shutil.copytree
        def partial(*args, **kwargs):
            real_copy(*args, **kwargs)
            raise OSError("injected copy failure")
        for mock in (patch.object(packages.shutil, "copytree", side_effect=partial),
                     patch.object(packages, "write", side_effect=OSError("injected write failure"))):
            with mock, self.assertRaises(OSError):
                packages.add(str(source))
            self.assertFalse((packages.PACKAGES / "sample-skill").exists())
            self.assertEqual(packages.read()["packages"], {})
        packages.add(str(source))
        with patch.object(packages, "write", side_effect=OSError("failure")), self.assertRaises(OSError):
            packages.remove("sample-skill")
        self.assertTrue((packages.PACKAGES / "sample-skill").exists())
        self.assertIn("sample-skill", packages.read()["packages"])
