from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class ClaudeSettingsSyncTest(unittest.TestCase):
    def test_builds_permissions_from_allowed_project_roots(self) -> None:
        from sync_claude_settings import build_dynamic_settings

        with tempfile.TemporaryDirectory() as tmp:
            root_a = Path(tmp) / "service-a"
            root_b = Path(tmp) / "service-b"
            root_a.mkdir()
            root_b.mkdir()

            settings = build_dynamic_settings([root_a, root_b])

        permissions = settings["permissions"]
        self.assertEqual(
            permissions["additionalDirectories"],
            [str(root_a.resolve()), str(root_b.resolve())],
        )
        self.assertIn(f"Read({root_a.resolve()}/**)", permissions["allow"])
        self.assertIn(f"Write({root_a.resolve()}/**)", permissions["allow"])
        self.assertIn(f"Edit({root_a.resolve()}/**)", permissions["allow"])

    def test_sync_preserves_existing_local_settings(self) -> None:
        from sync_claude_settings import sync_settings

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            target = repo / "target"
            target.mkdir()
            (repo / ".agent-platform.env").write_text(
                f'AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS="{target}"\n',
                encoding="utf-8",
            )
            local = repo / ".claude" / "settings.local.json"
            local.parent.mkdir()
            local.write_text(
                json.dumps({"permissions": {"allow": ["Bash(custom *)"]}, "custom": True}),
                encoding="utf-8",
            )

            with patch.dict("os.environ", {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": ""}):
                sync_settings(repo)
            updated = json.loads(local.read_text(encoding="utf-8"))

        self.assertTrue(updated["custom"])
        self.assertIn("Bash(custom *)", updated["permissions"]["allow"])
        self.assertIn(f"Read({target.resolve()}/**)", updated["permissions"]["allow"])


if __name__ == "__main__":
    unittest.main()
