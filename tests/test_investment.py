import importlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server/src"))

from agent_platform_mcp import cli, config, events, frontmatter
from agent_platform_mcp.tools import feature, runner


class InvestmentTest(unittest.TestCase):
    role = "investment"
    module = "investment"
    filename = "INVESTMENT-REPORT.md"
    title = "INVESTMENT REPORT"
    sections = ("Summary", "Evidence", "Thesis and Counterevidence", "Risks and Validation",
                "Development Handoff", "Skill Usage")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.directory = self.root / "docs/research/sample"
        self.directory.mkdir(parents=True)
        env = patch.dict(os.environ, {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": str(self.root)})
        env.start()
        self.addCleanup(env.stop)

    def run_report(self, **kwargs):
        module = importlib.import_module(f"agent_platform_mcp.tools.{self.module}")
        return module.run("research/sample", requirements="전략의 근거와 반대 근거 검토",
                          as_of="2026-09-23", cli="codex", root=self.root, **kwargs)

    def report(self):
        return f"# {self.title}: research/sample\n\n" + "".join(
            f"## {i}. {section}\nINSUFFICIENT; not run.\n" for i, section in enumerate(self.sections, 1))

    def test_cli_accepts_investment_and_dry_run_is_read_only(self):
        self.assertIn(self.role, cli.VALID_RUN_AGENTS)
        with patch.object(cli, "_print_result") as output, patch.object(runner, "run_cli") as execute:
            code = cli.main(["run", self.role, "research/sample", "--root", str(self.root),
                             "--requirements", "검토", "--as-of", "2026-09-23", "--dry-run"])
        self.assertEqual(code, 0)
        result = output.call_args.args[0]
        self.assertEqual(result["project_dir"], str(self.root))
        self.assertEqual(result["command"][result["command"].index("--sandbox") + 1], "read-only")
        source = (ROOT / f"standards/agents/{self.role}.md").read_text().strip()
        self.assertEqual(result["command"][-1].count(source), 1)
        self.assertIn("2026-09-23", result["command"][-1])
        self.assertEqual(list(self.directory.iterdir()), [])
        execute.assert_not_called()

    def test_valid_report_is_draft_and_recognized_by_gate(self):
        with patch.object(runner, "run_cli", return_value=subprocess.CompletedProcess([], 0, self.report(), "")):
            result = self.run_report()
        report = self.directory / self.filename
        self.assertEqual(result["artifact_status"], "draft")
        self.assertEqual(frontmatter.read(report)["agent"], self.role)
        self.assertEqual(frontmatter.read(report)["status"], "draft")
        self.assertEqual(frontmatter.read(report)["as_of"], "2026-09-23")
        self.assertTrue(feature.gate_check("research/sample", root=self.root, agent=self.role)["passed"])
        self.assertIn(self.role, events.ROLES)
        for outputs in config.AGENT_OUTPUTS_BY_TRACK.values():
            self.assertEqual(outputs[self.role], [self.filename])
        for prereqs in config.AGENT_PREREQUISITES_BY_TRACK.values():
            self.assertEqual(prereqs[self.role], [])

    def test_invalid_and_unsuccessful_output_cannot_pass_gate(self):
        for body, code in [("unstructured private output", 0), (self.report(), 1)]:
            with self.subTest(code=code), patch.object(runner, "run_cli", return_value=subprocess.CompletedProcess([], code, body, "")):
                result = self.run_report()
                self.assertTrue(result["artifact_invalid"])
                self.assertFalse(feature.gate_check("research/sample", root=self.root)["passed"])
                self.assertNotIn("unstructured private output", Path(result["output_path"]).read_text())

    def test_invalid_inputs_fail_before_execution(self):
        module = importlib.import_module(f"agent_platform_mcp.tools.{self.module}")
        for requirements, as_of in [("", "2026-09-23"), ("review", "2026-02-30"),
                                    ("review", "20260923"), ("review", "2026-09-23\nstatus: approved")]:
            with self.subTest(as_of=as_of), patch.object(runner, "run_cli") as execute:
                with self.assertRaises(ValueError):
                    module.run("research/sample", requirements=requirements, as_of=as_of, root=self.root)
                execute.assert_not_called()

    def test_output_symlink_is_rejected_after_execution(self):
        outside = self.root / "untouched.md"
        outside.write_text("unchanged")
        def execute(*args):
            (self.directory / self.filename).symlink_to(outside)
            return subprocess.CompletedProcess([], 0, self.report(), "")
        with patch.object(runner, "run_cli", side_effect=execute):
            with self.assertRaisesRegex(ValueError, "symlink"):
                self.run_report()
        self.assertEqual(outside.read_text(), "unchanged")


class QuantTest(InvestmentTest):
    role = "quant"
    module = "quant"
    filename = "QUANT-REPORT.md"
    title = "QUANT REPORT"
    sections = ("Summary", "Strategy Specification", "Data and Methodology",
                "Results and Robustness", "Development Handoff", "Skill Usage")


class InvestmentRiskTest(InvestmentTest):
    role = "investment-risk"
    module = "investment_risk"
    filename = "INVESTMENT-RISK.md"
    title = "INVESTMENT RISK"
    sections = ("Summary", "Exposure and Limits", "Scenarios and Counterevidence",
                "Controls and Gaps", "Development Handoff", "Skill Usage")
