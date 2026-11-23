"""Doc checks for living-feature-spec Phase 6 (AC-2, AC-13, AC-16) and token-usage-management BR-1."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "standards/agents"
DEV_ROLES = ("backend", "reviewer", "security", "dba", "qa")


def section(text: str, heading: str) -> str:
    match = re.search(rf"^# {re.escape(heading)}\n(.*?)(?=^# |\Z)", text, re.M | re.S)
    return match.group(1) if match else ""


class RoleReadScopeTest(unittest.TestCase):
    def test_every_role_has_a_read_scope_table_that_excludes_archived_folders(self):
        for path in sorted(AGENTS.glob("*.md")):
            with self.subTest(role=path.stem):
                scope = section(path.read_text(), "Read Scope")
                self.assertIn("| 최소 (항상) |", scope)
                self.assertIn("| 확장 (근거가 있을 때만) |", scope)
                self.assertIn("archived: true", scope)

    def test_development_roles_keep_their_required_inputs_in_the_minimum_set(self):
        for role in DEV_ROLES:
            with self.subTest(role=role):
                scope = section((AGENTS / f"{role}.md").read_text(), "Read Scope")
                minimum = next(line for line in scope.splitlines() if line.startswith("| 최소 (항상) |"))
                for needle in ("SPEC.md", "diff", "ARCHITECTURE.md", "API-SPEC", "DECISIONS", "테스트"):
                    self.assertIn(needle, minimum)
                self.assertIn("AGENT_PREREQUISITES_BY_TRACK", scope)

    def test_planner_proposes_the_feature_and_prefers_work_v1(self):
        text = (AGENTS / "planner.md").read_text()
        self.assertIn("spec: <slug>", text)
        self.assertIn("검토 요청", text)
        self.assertIn("spec new", text)
        self.assertIn("work-v1 을 먼저 권한다", text)

    def test_cicd_updates_the_spec_resets_it_to_draft_and_publishes_after_merge(self):
        text = (AGENTS / "cicd.md").read_text()
        for needle in ("2~5절", "status: draft", "spec history-add", "spec index", "머지 후", "publish --spec", "사용자가 확인한 뒤에만"):
            self.assertIn(needle, text)

    def test_local_observation_records_runs_with_the_feature_key(self):
        for path in sorted(AGENTS.glob("*.md")):
            if path.stem == "orchestrator":
                continue
            with self.subTest(role=path.stem):
                observation = section(path.read_text(), "Local Observation")
                self.assertIn(f"state start <type>/<name> --role {path.stem}", observation)
                self.assertIn("state end", observation)
        orchestrator = (AGENTS / "orchestrator.md").read_text()
        self.assertIn("기능 키 `<type>/<name>`", orchestrator)
        # Overlapping runs make every turn ambiguous, so the orchestrator never opens its own run.
        self.assertIn("자기 run 을 열지 않는다", section(orchestrator, "Local Observation"))
        self.assertNotIn("--role orchestrator", orchestrator)

    def test_readme_documents_work_v1_first_spec_commands_and_token_report(self):
        text = (ROOT / "README.md").read_text()
        for needle in ("work-v1 우선", "spec new", "spec history-add", "spec bootstrap", "feature-archive",
                       "project-spec-set", "publish --spec", "observe usage", "token_budget"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
