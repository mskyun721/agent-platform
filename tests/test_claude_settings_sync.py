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
            repo = Path(tmp) / "agent-platform"
            target = Path(tmp) / "target"  # beside the checkout: its own subtree is never granted
            target.mkdir()
            repo.mkdir()
            (repo / ".env").write_text(
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

    def test_tiers_drive_adapter_models_and_claude_models_still_override(self) -> None:
        from sync_claude_settings import claude_role_models, role_models, sync_settings

        cfg = {"model_tiers": {"high": {"claude": "opus", "copilot": "claude-opus-5.5"}, "mid": {"claude": "sonnet"}},
               "role_tiers": {"reviewer": "mid", "backend": "high"}}
        self.assertEqual(claude_role_models(cfg), {"reviewer": "sonnet", "backend": "opus"})
        self.assertEqual(claude_role_models({**cfg, "claude_models": {"reviewer": "haiku"}})["reviewer"], "haiku")
        self.assertEqual(role_models(cfg, "copilot"), {"backend": "claude-opus-5.5"})
        for bad in ({"model_tiers": {"high": "x"}, "role_tiers": {"qa": "high"}},  # REVIEW L-2: fail closed like routing
                    {"model_tiers": {"high": {}}, "role_tiers": {"qa": "hihg"}},
                    {"model_tiers": {"high": {}}, "role_tiers": {"ghost": "high"}}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                role_models(bad, "claude")
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            (repo / ".agent-config.json").write_text(json.dumps(cfg), encoding="utf-8")
            with patch.dict("os.environ", {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": ""}):
                sync_settings(repo)
            self.assertIn("model: sonnet\n", (repo / ".claude/agents/reviewer.md").read_text(encoding="utf-8"))

    def test_adapter_pins_resolve_exactly_like_routing(self) -> None:  # REVIEW M-2
        from types import SimpleNamespace
        from unittest.mock import patch as mock
        from agent_platform_mcp.tools import routing
        from sync_claude_settings import ROLES, role_models

        base = {"model_tiers": {"high": {"claude": "opus", "copilot": "claude-opus-5.5"}, "mid": {"claude": "sonnet"}},
                "role_tiers": {"reviewer": "high", "qa": "mid", "backend": "high"}}
        layers = {"claude_models": {"reviewer": "haiku", "qa": "opus"},
                  "host_models": {"claude": {"reviewer": "claude-host"}, "copilot": {"qa": "claude-copilot-qa"}},
                  "cli_models": {"copilot": "claude-cli-pin"},
                  "routing": {"roles": {"backend": {"models": {"claude": "claude-role-pin"}}}}}
        cases = [base, {**base, "claude_models": layers["claude_models"]}, {**base, "host_models": layers["host_models"]},
                 {**base, **{k: layers[k] for k in ("claude_models", "host_models")}}, {**base, **layers}]
        context = SimpleNamespace(project_id=None, path=Path("/nowhere"))
        for cfg in cases:
            for backend in ("claude", "copilot"):
                adapters = role_models(cfg, backend)
                with mock.object(routing, "configuration", return_value=cfg):
                    for role in ROLES:
                        with self.subTest(cfg=sorted(cfg), backend=backend, role=role):
                            self.assertEqual(adapters.get(role), routing.resolve(role, context, cli=backend)["model"])
        self.assertEqual(role_models({**base, "host_models": layers["host_models"]}, "claude")["reviewer"], "claude-host")

    def test_check_reports_undefined_tier_and_model_drift(self) -> None:  # REVIEW L-2
        import subprocess
        import sys
        script = [sys.executable, str(ROOT / "scripts/sync_claude_settings.py")]
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            config = repo / ".agent-config.json"
            config.write_text(json.dumps({"model_tiers": {"high": {"claude": "opus"}}, "role_tiers": {"reviewer": "hihg"}}))
            check = subprocess.run([*script, "--repo-root", str(repo), "--check"], capture_output=True, text=True, timeout=15)
            self.assertEqual(check.returncode, 1)
            self.assertIn("reviewer=hihg", check.stderr)
            self.assertNotIn("Traceback", check.stderr)
            config.write_text(json.dumps({"model_tiers": {"high": {"claude": "opus"}}, "role_tiers": {"reviewer": "high"}}))
            check = subprocess.run([*script, "--repo-root", str(repo), "--check"], capture_output=True, text=True, timeout=15)
            self.assertEqual((check.returncode, "reviewer.md" in check.stdout), (1, True))  # model line drift
            subprocess.run([*script, "--repo-root", str(repo), "--agents-only"], capture_output=True, timeout=15, check=True)
            self.assertIn("model: opus\n", (repo / ".claude/agents/reviewer.md").read_text())

    def test_shipped_config_keeps_gate_roles_at_least_as_strong_as_backend(self) -> None:
        # 2026-10-22: a gate weaker than the producer confirms instead of catching, so planner,
        # reviewer, security and dba must never sit below backend. qa executes and diagnoses real
        # tests, so it is above low. 2026-11-22: tiers replace claude_models; cicd mid, investment trio high.
        from sync_claude_settings import claude_role_models

        rank = {"low": 0, "mid": 1, "high": 2}
        cfg = json.loads((ROOT / ".agent-config.json").read_text(encoding="utf-8"))
        tiers = cfg["role_tiers"]
        for gate in ("planner", "reviewer", "security", "dba"):
            self.assertGreaterEqual(rank[tiers[gate]], rank[tiers["backend"]], gate)
        self.assertGreaterEqual(rank[tiers["qa"]], rank["mid"])
        self.assertGreaterEqual(rank[tiers["investment-risk"]], rank[tiers["investment"]])
        self.assertEqual((tiers["cicd"], tiers["investment"], tiers["quant"]), ("mid", "high", "high"))
        models = claude_role_models(cfg)
        for role in ("orchestrator", "planner", "backend", "reviewer", "security", "dba", "qa", "cicd", "investment", "quant", "investment-risk"):
            text = (ROOT / ".claude" / "agents" / f"{role}.md").read_text(encoding="utf-8")
            self.assertIn(f"model: {models[role]}\n", text, role)
            copilot = (ROOT / ".github" / "agents" / f"{role}.agent.md").read_text(encoding="utf-8")
            self.assertIn(f"model: {cfg['model_tiers'][tiers[role]]['copilot']}\n", copilot, role)

if __name__ == "__main__":
    unittest.main()
