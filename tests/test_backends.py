import json
import unittest
from pathlib import Path
from agent_platform_mcp import backends
from agent_platform_mcp.tools import runner


class LegacyBackendTest(unittest.TestCase):
    def test_claude_and_codex_argv_unchanged(self):
        wd = Path("/w")
        for read_only in (True, False):
            for model in (None, "m1"):
                self.assertEqual(
                    backends.get("claude").command("P", wd, model=model, read_only=read_only),
                    ["claude", "-p", "--output-format", "json", "--strict-mcp-config", "--permission-mode", "dontAsk",
                     "--tools", "Read,Glob,Grep,WebSearch,WebFetch" if read_only else "Read,Glob,Grep,Edit,Write,Bash",
                     "--allowedTools", "Read,Glob,Grep,WebSearch,WebFetch" if read_only else "Read,Glob,Grep,Edit,Write",
                     *(["--model", model] if model else []), "--", "P"])
                self.assertEqual(
                    backends.get("codex").command("P", wd, model=model, read_only=read_only),
                    ["codex", "exec", "--cd", "/w", *(["-m", model] if model else []), "--skip-git-repo-check",
                     "--sandbox", "read-only" if read_only else "workspace-write", "--json", "P"])
                self.assertEqual(runner.build_cmd("claude", "P", wd, model=model, read_only=read_only),
                                 backends.get("claude").command("P", wd, model=model, read_only=read_only))

    def test_codex_parse_never_reports_failure_flag(self):
        text, usage, failed = backends.get("codex").parse("legacy report")
        self.assertEqual((text, usage.completeness, failed), ("legacy report", "unavailable", False))

    def test_claude_parse_failure(self):
        self.assertTrue(backends.get("claude").parse("not json")[2])
        ok = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "r"})
        self.assertEqual(backends.get("claude").parse(ok)[0::2], ("r", False))

    def test_unknown_backend_rejected(self):
        with self.assertRaises(ValueError):
            backends.get("gpt")
        self.assertEqual(backends.NAMES, ("claude", "codex", "gemini", "copilot"))


FIX = Path(__file__).parent / "fixtures" / "backends"


class GeminiTest(unittest.TestCase):
    def test_argv_is_bounded_and_isolated(self):
        cmd = backends.get("gemini").command("P", Path("/w"), model="gemini-3.5-flash", read_only=True)
        self.assertEqual(cmd, ["gemini", "-o", "json", "--approval-mode", "plan", "-e", "none",
                               "--allowed-mcp-server-names", "none", "-m", "gemini-3.5-flash", "-p", "P"])
        edit = backends.get("gemini").command("P", Path("/w"), model=None, read_only=False)
        self.assertIn("auto_edit", edit)
        self.assertNotIn("yolo", " ".join(edit))

    def test_parse_success_and_usage(self):
        text, usage, failed = backends.get("gemini").parse((FIX / "gemini-ok.json").read_text())
        self.assertFalse(failed)
        self.assertTrue(text.strip())
        self.assertEqual(usage.source, "gemini-json")
        self.assertIn(usage.completeness, ("full", "partial"))

    def test_error_and_noise_are_failures(self):
        for raw in ((FIX / "gemini-error.json").read_text(), "Warning: x\n{}", "", "[]"):
            self.assertTrue(backends.get("gemini").parse(raw)[2], raw)


class CopilotTest(unittest.TestCase):
    def test_argv_disables_platform_mcp_and_shell(self):
        ro = backends.get("copilot").command("P", Path("/w"), model="claude-sonnet-5-5", read_only=True)
        self.assertEqual(ro, ["copilot", "-s", "--no-ask-user", "--no-color", "--disable-mcp-server", "agent-platform",
                              "--deny-tool", "shell", "--deny-tool", "write", "--model", "claude-sonnet-5-5", "-p", "P"])
        rw = backends.get("copilot").command("P", Path("/w"), model=None, read_only=False)
        self.assertEqual(rw[-4:], ["--allow-tool", "write", "-p", "P"])
        self.assertIn("agent-platform", rw)
        for flag in ("--allow-all-tools", "--allow-all-paths", "--yolo"):
            self.assertNotIn(flag, rw)

    def test_parse_text_only(self):
        self.assertEqual(backends.get("copilot").parse("done\n")[0::2], ("done", False))
        text, usage, failed = backends.get("copilot").parse("  \n")
        self.assertTrue(failed)
        self.assertEqual(usage.completeness, "unavailable")


class VersionTest(unittest.TestCase):
    def test_version_keeps_first_line_only(self):
        import subprocess
        from unittest.mock import patch
        done = subprocess.CompletedProcess([], 0, stdout="GitHub Copilot CLI 1.0.95.\nRun 'copilot update'\n")
        with patch.object(backends.shutil, "which", return_value="/bin/copilot"), \
             patch.object(backends.subprocess, "run", return_value=done):
            self.assertEqual(backends.version("copilot"), "GitHub Copilot CLI 1.0.95.")


class LearningPackageTest(unittest.TestCase):
    def test_shims_point_to_same_objects(self):
        from agent_platform_mcp.learning import feedback, improvements, evals
        from agent_platform_mcp.tools import learning, improvements as legacy_improvements, improvement_evals, projects
        self.assertIs(learning.add, feedback.add)
        self.assertIs(legacy_improvements.propose, improvements.propose)
        self.assertIs(improvement_evals.compare, evals.compare)
        self.assertIs(projects.safe_storage, projects._safe_storage)
