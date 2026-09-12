"""Tests for .agent-config.json as the single source of CLI policy."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server" / "src"))

from agent_platform_mcp import config  # noqa: E402


class AgentConfigSingleSourceTest(unittest.TestCase):
    def test_config_file_has_no_dead_keys(self) -> None:
        raw = json.loads((config.ROOT / ".agent-config.json").read_text(encoding="utf-8"))
        for key in ("cli_fallback", "agent_cli_defaults", "model_overrides"):
            self.assertNotIn(key, raw, f"dead config key '{key}' must be removed")

    def test_preferred_cli_default_matches_config_file(self) -> None:
        # config.py 코드 기본값과 .agent-config.json 값이 일치해야 한다 (codex)
        self.assertEqual(config.preferred_cli(), "codex")
        self.assertEqual(config._DEFAULT_CLI, "codex")

    def test_cli_model_returns_none_when_unpinned(self) -> None:
        self.assertIsNone(config.cli_model("codex"))
        self.assertIsNone(config.cli_model("gemini"))

    def test_only_codex_is_a_valid_external_cli(self) -> None:
        self.assertEqual(config._VALID_CLI, {"codex"})
        self.assertEqual(config.preferred_cli(), "codex")
        self.assertNotIn("gemini", config.agent_config().get("cli_models", {}))

    def test_no_default_agent_cli_constant(self) -> None:
        self.assertFalse(hasattr(config, "_DEFAULT_AGENT_CLI"))

    def test_no_legacy_log_file_constant(self) -> None:
        self.assertFalse(hasattr(config, "LOG_FILE"))


class LoggingRemovalTest(unittest.TestCase):
    def test_log_helpers_removed(self) -> None:
        self.assertFalse(hasattr(config, "log_file"))

    def test_log_tool_module_removed(self) -> None:
        import importlib.util

        spec = importlib.util.find_spec("agent_platform_mcp.tools.log")
        self.assertIsNone(spec)

    def test_server_has_no_log_append_tool(self) -> None:
        from agent_platform_mcp import server

        self.assertFalse(hasattr(server, "log_append"))


if __name__ == "__main__":
    unittest.main()
