"""scripts/models_refresh.py: catalog parsing, proposals, warnings, unavailable CLIs, report-only default."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import models_refresh  # noqa: E402

COPILOT_HELP = '''  `logLevel`: log level.

  `model`: AI model to use for Copilot CLI.
    - "claude-sonnet-5.5"
    - "claude-opus-5.5"
    - "claude-opus-5"
    - "claude-opus-4.8-fast"
    - "claude-opus-6-fast"
    - "claude-haiku-5.5"
    - "gpt-6-astra"

  `contextTier`: context window tier.
    - "ignored"
'''
CODEX = json.dumps({"models": [
    {"slug": "hidden", "visibility": "hide", "priority": 0, "description": "Flagship."},
    {"slug": "sol", "visibility": "list", "priority": 1, "description": "Most capable flagship model."},
    {"slug": "luna", "visibility": "list", "priority": 2, "description": "Fast and affordable model."},
    {"slug": "astra", "visibility": "list", "priority": 3, "description": "Balanced agentic coding."},
    {"slug": "old", "visibility": "list", "priority": 4, "description": "Legacy balanced model."}]})
CONFIG = {"model_tiers": {"high": {"claude": "opus", "copilot": "claude-opus-5", "codex": "old"},
                          "mid": {"claude": "claude-sonnet-pinned", "copilot": "claude-sonnet-5.5", "codex": "gone"},
                          "low": {"copilot": "claude-haiku-5.5"}},
          "host_models": {"copilot": {"backend": "claude-opus-4.8"}}}


def fake(outputs):
    return lambda argv: outputs.get(argv[0])


class ModelsRefreshTest(unittest.TestCase):
    def test_copilot_ids_stop_at_the_model_section(self):
        ids = models_refresh.copilot_ids(COPILOT_HELP)
        self.assertEqual(ids[0], "claude-sonnet-5.5")
        self.assertNotIn("ignored", ids)
        self.assertEqual(models_refresh.propose_copilot(ids),
                         {"high": "claude-opus-5.5", "mid": "claude-sonnet-5.5", "low": "claude-haiku-5.5"})

    def test_codex_proposal_uses_listed_non_legacy_by_priority(self):
        proposal, slugs = models_refresh.propose_codex(CODEX)
        self.assertEqual(proposal, {"high": "sol", "mid": "astra", "low": "luna"})
        self.assertEqual(slugs, ["sol", "luna", "astra", "old"])
        only_fast = json.dumps({"models": [{"slug": "luna", "visibility": "list", "priority": 1,
                                            "description": "Fast and affordable."}]})
        self.assertEqual(models_refresh.propose_codex(only_fast)[0], {"low": "luna"})

    def test_report_warns_on_stale_pins_and_apply_changes_only_proposals(self):
        result = models_refresh.report(json.loads(json.dumps(CONFIG)), fake(
            {"claude": "2.1\n", "gemini": "0.66.0\n", "copilot": COPILOT_HELP, "codex": CODEX}))
        warnings = "\n".join(result["warnings"])
        self.assertIn("copilot high: claude-opus-5 is not the latest (claude-opus-5.5)", warnings)
        self.assertIn("codex high: old is not the latest (sol)", warnings)
        self.assertIn("codex mid: gone is not in the local catalog", warnings)
        self.assertIn("claude mid: pinned claude-sonnet-pinned; alias sonnet tracks the latest", warnings)
        self.assertIn("host_models.copilot.backend: claude-opus-4.8 is not the latest (claude-opus-5.5)", warnings)
        self.assertEqual(result["backends"]["gemini"]["status"], "alias")
        config = json.loads(json.dumps(CONFIG))
        changed = models_refresh.apply(config, result)
        self.assertEqual(config["model_tiers"]["high"], {"claude": "opus", "copilot": "claude-opus-5.5", "codex": "sol"})
        self.assertEqual(config["model_tiers"]["mid"]["claude"], "claude-sonnet-pinned")  # aliases untouched
        self.assertIn("low.codex=luna", changed)

    def test_missing_or_broken_clis_are_unavailable_without_warnings(self):
        result = models_refresh.report(CONFIG, fake({"codex": "not json"}))
        self.assertEqual({b: i["status"] for b, i in result["backends"].items()},
                         {"claude": "unavailable", "gemini": "unavailable", "copilot": "unavailable", "codex": "unavailable"})
        self.assertEqual(result["warnings"], [])
        self.assertIsNone(models_refresh.run(["agent-platform-no-such-cli-xyz"]))

    def test_cli_is_report_only_unless_write(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "codex").write_text("#!/bin/sh\ncat <<'X'\n" + CODEX + "\nX\n")
        (bin_dir / "codex").chmod(0o755)
        path = tmp / ".agent-config.json"
        original = json.dumps(CONFIG, indent=2) + "\n"
        path.write_text(original)
        env = {"PATH": f"{bin_dir}:/usr/bin:/bin"}
        script = str(ROOT / "scripts/models_refresh.py")
        out = subprocess.run([sys.executable, script, "--repo-root", str(tmp)], env=env,
                             capture_output=True, text=True, check=True).stdout
        self.assertIn("copilot: unavailable", out)
        self.assertIn("report only", out)
        self.assertEqual(path.read_text(), original)
        out = subprocess.run([sys.executable, script, "--repo-root", str(tmp), "--write"], env=env,
                             capture_output=True, text=True, check=True).stdout
        self.assertIn("high.codex=sol", out)
        self.assertEqual(json.loads(path.read_text())["model_tiers"]["high"]["codex"], "sol")


if __name__ == "__main__":
    unittest.main()
