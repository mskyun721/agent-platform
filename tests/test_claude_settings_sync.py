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


class AgentModelSyncTest(unittest.TestCase):
    """P1 Task 5: subagent models come from .agent-config.json, not hand-edited front-matter."""

    def _repo(self, tmp: str) -> Path:
        repo = Path(tmp)
        agents = repo / ".claude" / "agents"
        agents.mkdir(parents=True)
        (agents / "reviewer.md").write_text(
            "---\nname: reviewer\ntools: Read\nmodel: haiku\n---\n# Role\nbody\n", encoding="utf-8"
        )
        (agents / "backend.md").write_text(
            "---\nname: backend\nmodel: opus\n---\n# Role\n", encoding="utf-8"
        )
        return repo

    def test_sync_agent_models_rewrites_only_the_model_line(self) -> None:
        from sync_claude_settings import sync_agent_models

        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp)

            changed = sync_agent_models(repo, {"reviewer": "sonnet", "backend": "opus", "ghost": "haiku"})

            reviewer = (repo / ".claude/agents/reviewer.md").read_text(encoding="utf-8")
            backend = (repo / ".claude/agents/backend.md").read_text(encoding="utf-8")

        self.assertEqual(changed, ["reviewer.md"])
        self.assertIn("model: sonnet\n", reviewer)
        self.assertIn("tools: Read\n", reviewer)
        self.assertIn("# Role\nbody\n", reviewer)
        self.assertIn("model: opus\n", backend)

    def test_sync_settings_applies_models_from_agent_config(self) -> None:
        from sync_claude_settings import sync_settings

        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            (repo / ".agent-config.json").write_text(
                json.dumps({"claude_models": {"reviewer": "sonnet"}}), encoding="utf-8"
            )

            with patch.dict("os.environ", {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": ""}):
                sync_settings(repo)
            reviewer = (repo / ".claude/agents/reviewer.md").read_text(encoding="utf-8")

        self.assertIn("model: sonnet\n", reviewer)

    def test_shipped_config_puts_review_roles_on_sonnet(self) -> None:
        cfg = json.loads((ROOT / ".agent-config.json").read_text(encoding="utf-8"))
        models = cfg["claude_models"]
        self.assertEqual(models["reviewer"], "sonnet")
        self.assertEqual(models["security"], "sonnet")
        for role in ("orchestrator", "planner", "backend", "reviewer", "security", "qa", "cicd", "investment", "quant", "investment-risk"):
            text = (ROOT / ".claude" / "agents" / f"{role}.md").read_text(encoding="utf-8")
            self.assertIn(f"model: {models[role]}\n", text, role)


if __name__ == "__main__":
    unittest.main()
