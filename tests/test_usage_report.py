"""Token usage report: budget config, feature type/completion, aggregation, quality, budget warning."""

import tempfile
import unittest
from pathlib import Path

from agent_platform_mcp.tools import usage_report

DOC = "---\nagent: {agent}\nfeature: {feature}\nstatus: {status}\ncreated: 2026-11-01\nupdated: 2026-11-01\n{extra}---\n\n# body\n"


def write_doc(project: Path, key: str, file: str, status: str = "approved", agent: str = "cicd", extra: str = "") -> Path:
    path = project / "docs" / key / file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DOC.format(agent=agent, feature=key, status=status, extra=extra), encoding="utf-8")
    return path


def complete(project: Path, key: str) -> None:
    for file in ("RELEASE-NOTE.md", "PR-BODY.md", "DEPLOY-CHECKLIST.md"):
        write_doc(project, key, file)


class BudgetConfigTest(unittest.TestCase):
    def test_absent_budget_has_no_defaults(self):
        self.assertEqual(usage_report.load_budget({}), {"types": {}, "roles": {}})

    def test_valid_budget_and_comment_keys(self):
        budget = usage_report.load_budget({"token_budget": {"_note": "x", "types": {"work": 150000},
                                                            "roles": {"backend": 300000}}})
        self.assertEqual(budget, {"types": {"work": 150000}, "roles": {"backend": 300000}})

    def test_invalid_fields_are_named(self):
        cases = {"token_budget": [], "types": {"types": []}, "types.huge": {"types": {"huge": 1}},
                 "types.full": {"types": {"full": 0}}, "roles.backend": {"roles": {"backend": True}},
                 "roles.writer": {"roles": {"writer": 5}}, "limit": {"limit": 5}}
        for field, value in cases.items():
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, f"^invalid token_budget: {field}$"):
                usage_report.load_budget({"token_budget": value})
        with self.assertRaisesRegex(ValueError, "types.full"):
            usage_report.load_budget({"token_budget": {"types": {"full": 1.5}}})


class FeatureKindTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name).resolve()

    def test_type_follows_contract_and_prefix(self):
        write_doc(self.project, "features/big", "PRD.md", "draft", "planner")
        write_doc(self.project, "fix/small", "PRD.md", "draft", "planner")
        write_doc(self.project, "refactor/tiny", "WORK.md", "draft", "backend")
        kinds = {key: usage_report.feature_kind(self.project, key)["type"]
                 for key in ("big", "features/big", "fix/small", "refactor/tiny")}
        self.assertEqual(kinds, {"big": "full", "features/big": "full", "fix/small": "light", "refactor/tiny": "work"})
        self.assertEqual(usage_report.feature_kind(self.project, "big")["feature"], "features/big")

    def test_completed_requires_all_cicd_outputs_approved(self):
        write_doc(self.project, "features/big", "PRD.md", "approved", "planner")
        self.assertFalse(usage_report.feature_kind(self.project, "features/big")["completed"])
        complete(self.project, "features/big")
        write_doc(self.project, "features/big", "PR-BODY.md", "draft")
        self.assertFalse(usage_report.feature_kind(self.project, "features/big")["completed"])
        write_doc(self.project, "features/big", "PR-BODY.md")
        self.assertTrue(usage_report.feature_kind(self.project, "features/big")["completed"])

    def test_work_contract_completion_and_archived(self):
        write_doc(self.project, "refactor/tiny", "WORK.md", "draft", "backend")
        self.assertFalse(usage_report.feature_kind(self.project, "refactor/tiny")["completed"])
        write_doc(self.project, "refactor/tiny", "WORK.md", "approved", "backend")
        self.assertTrue(usage_report.feature_kind(self.project, "refactor/tiny")["completed"])
        write_doc(self.project, "features/old", "PRD.md", "draft", "planner", "archived: true\n")
        self.assertTrue(usage_report.feature_kind(self.project, "features/old")["completed"])

    def test_missing_folder(self):
        self.assertEqual(usage_report.feature_kind(self.project, "fix/gone"),
                         {"feature": "fix/gone", "exists": False, "type": None, "completed": False})


if __name__ == "__main__":
    unittest.main()
