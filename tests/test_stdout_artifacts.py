import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp-server/src"))
from agent_platform_mcp.tools import audit, feature, review, runner, stdout_artifacts as reports


def report(role):
    return f"# {reports.TITLES[role]}: example\n\n" + "\n\n".join(
        section + "\nNo issues found." for section in reports.SECTIONS[role])


class StdoutArtifactTest(unittest.TestCase):
    def test_valid_reports_are_draft_and_masked(self):
        for role in reports.SECTIONS:
            with self.subTest(role=role):
                raw = "[AI: codex]\nOpenAI Codex v0.154.0\n" + report(role) + "\npassword=example-value\n"
                body, result = reports.prepare(raw, role=role, feature="example", exit_code=0)
                self.assertEqual(result["artifact_status"], "draft")
                self.assertEqual(result["masked_lines"], 3)
                self.assertNotIn("example-value", body)
                self.assertFalse(result["raw_stored"])

    def test_invalid_output_is_not_retained(self):
        valid = report("reviewer")
        for raw, code in (("", 0), ("private-output", 0), ("```markdown\n" + valid + "\n```", 0),
                          (valid, 1), ("---\nstatus: approved\n---\n" + valid, 0),
                          (valid + "\n````\n```\n", 0)):
            with self.subTest(raw=raw, code=code):
                body, result = reports.prepare(raw, role="reviewer", feature="example", exit_code=code)
                self.assertEqual(result["artifact_status"], "invalid")
                self.assertTrue(result["invalid_reason"])
                self.assertNotIn("private-output", body)
                self.assertNotIn("status: approved", body)

    def test_wrappers_write_invalid_flag_and_gate_rejects_even_after_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            with patch.dict(os.environ, {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": str(root)}):
                feature.scaffold("example", root=root)
                for wrapper, filename in ((review, "REVIEW.md"), (audit, "SECURITY-AUDIT.md")):
                    with self.subTest(wrapper=wrapper.__name__), patch.object(
                        runner, "run_cli", return_value=subprocess.CompletedProcess([], 0, "private-output", "private-error")
                    ):
                        result = wrapper.run("example", cli="codex", root=root)
                    path = root / "docs/features/example" / filename
                    content = path.read_text()
                    self.assertIn("status: draft", content)
                    self.assertIn("artifact_invalid: true", content)
                    self.assertNotIn("private-output", content)
                    self.assertEqual(result["stderr_tail"], "")
                    path.write_text(content.replace("status: draft", "status: approved"))
                    checked = feature._validate_file(path, "example", root)
                    self.assertIn(f"artifact_invalid: {filename}", checked["errors"])
                    self.assertFalse(checked["passed"])
                    gate = feature.gate_check("example", root=root)
                    self.assertFalse(gate["passed"])
                    self.assertEqual(gate["artifact_status"], "failed")
                    entry = next(item for item in gate["files"] if item["file"] == filename)
                    self.assertIn(f"artifact_invalid: {filename}", entry["errors"])

    def test_valid_wrapper_output_passes_structure_without_self_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            with patch.dict(os.environ, {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": str(root)}):
                feature.scaffold("example", root=root)
                for role, wrapper, filename in (("reviewer", review, "REVIEW.md"), ("security", audit, "SECURITY-AUDIT.md")):
                    with patch.object(runner, "run_cli", return_value=subprocess.CompletedProcess([], 0, report(role), "")):
                        result = wrapper.run("example", cli="codex", root=root)
                    self.assertEqual(result["artifact_status"], "draft")
                    checked = feature._validate_file(root / "docs/features/example" / filename, "example", root)
                    self.assertTrue(checked["passed"], checked)
                    self.assertEqual(checked["status"], "draft")
