import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class HostSyncTest(unittest.TestCase):
    def repo(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        for rel in ("standards/agents", ".claude/agents", ".claude/commands"):
            shutil.copytree(ROOT / rel, tmp / rel)
        for rel in ("AGENTS.md", ".mcp.json", ".agent-config.json"):
            shutil.copy(ROOT / rel, tmp / rel)
        return tmp

    def test_render_covers_every_role_and_command(self):
        import sync_hosts
        repo = self.repo()
        files = sync_hosts.render(repo)
        roles = {p.stem for p in (repo / "standards/agents").glob("*.md")}
        self.assertEqual({p.name.removesuffix(".agent.md") for p in files if p.parts[:2] == (".github", "agents")}, roles)
        self.assertIn(Path("GEMINI.md"), files)
        settings = json.loads(files[Path(".gemini/settings.json")])
        self.assertEqual(settings["mcpServers"]["agent-platform"]["command"], "uv")
        commands = {p.stem for p in (repo / ".claude/commands").glob("*.md")}
        self.assertEqual({p.stem for p in files if p.parts[:2] == (".gemini", "commands")}, commands)
        feature = files[Path(".gemini/commands/new-feature.toml")]
        self.assertIn("{{args}}", feature)
        self.assertNotIn("$ARGUMENTS", feature)
        body = (repo / "standards/agents/reviewer.md").read_text().strip()
        self.assertIn(body, files[Path(".github/agents/reviewer.agent.md")])

    def test_check_detects_manual_edit_and_sync_repairs(self):
        import sync_hosts
        repo = self.repo()
        self.assertTrue(sync_hosts.sync_all(repo, check=True))
        sync_hosts.sync_all(repo, check=False)
        self.assertEqual(sync_hosts.sync_all(repo, check=True), [])
        (repo / ".gemini/commands/handoff.toml").write_text("tampered")
        self.assertEqual(sync_hosts.sync_all(repo, check=True), [".gemini/commands/handoff.toml"])

    def test_mcp_env_values_are_never_copied(self):
        import sync_hosts
        repo = self.repo()
        cfg = json.loads((repo / ".mcp.json").read_text())
        cfg["mcpServers"]["agent-platform"]["env"] = {"TOKEN": "x"}
        (repo / ".mcp.json").write_text(json.dumps(cfg))
        with self.assertRaises(ValueError):
            sync_hosts.render(repo)

    def test_cli_check_exit_code(self):
        repo = self.repo()
        script = ROOT / "scripts/sync_hosts.py"
        self.assertEqual(subprocess.run([sys.executable, str(script), "--repo-root", str(repo), "--check"],
                                        capture_output=True).returncode, 1)
        subprocess.run([sys.executable, str(script), "--repo-root", str(repo)], check=True, capture_output=True)
        self.assertEqual(subprocess.run([sys.executable, str(script), "--repo-root", str(repo), "--check"],
                                        capture_output=True).returncode, 0)

    def test_copilot_agents_keep_claude_tool_restrictions(self):
        import sync_hosts
        files = sync_hosts.render(self.repo())
        investment = files[Path(".github/agents/investment.agent.md")]
        header = investment.split("---", 2)[1]
        self.assertIn('tools: ["read", "edit", "search", "web", "agent-platform/experience_add"]', header)
        self.assertNotIn("execute", header)
        reviewer = files[Path(".github/agents/reviewer.agent.md")].split("---", 2)[1]
        self.assertIn('"execute"', reviewer)
        self.assertIn('"agent-platform/review_run"', reviewer)
        self.assertEqual(sync_hosts.copilot_tools("Read, mcp__whodb__whodb_query"), ["read", "whodb/whodb_query"])
        with self.assertRaises(ValueError):
            sync_hosts.copilot_tools("Read, Teleport")
