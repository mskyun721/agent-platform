"""Token usage report: budget config, feature type/completion, aggregation, quality, budget warning."""

import json
import os
import tempfile
import time
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from agent_platform_mcp import events
from agent_platform_mcp.tools import pricing, projects, store, usage_report

PRICE = {"price_id": "fixture-v1", "currency": "USD", "as_of": "2026-11-01",
         "models": {"priced": {"input_per_mtok": "2", "output_per_mtok": "4", "cache_read_per_mtok": "0.5",
                               "cache_write_per_mtok": "1", "input_includes_cache": False}}}

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


class StoreFixture(unittest.TestCase):
    """Fixture DB plus a target project folder; project_id 'proj-a'."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name).resolve() / "target"
        self.project.mkdir()
        mock = patch.dict(os.environ, {"AGENT_PLATFORM_STATE_DB": str(Path(temp.name).resolve() / "state.db")})
        mock.start()
        self.addCleanup(mock.stop)
        self.context = projects.ProjectContext("proj-a", self.project)
        self.clock = 0

    def event(self, task, role, backend="claude", model="m", project="proj-a", ts=None):
        self.clock += 1
        ts = ts or f"2026-11-{1 + self.clock // 1440:02d}T{self.clock // 60 % 24:02d}:{self.clock % 60:02d}:00+00:00"
        price = pricing.snapshot(PRICE, model)
        return events.RunEvent(str(uuid4()), str(uuid4()), None, project, task, role, "run_started", ts, backend, model, {},
                               {"workspace": str(self.project), "price_snapshot": price}, "direct", "partial")

    def add_run(self, task, role, backend="claude", tokens=(100, 10, 5, 1), completeness="full", **kwargs):
        event = self.event(task, role, backend, **kwargs)
        with store.open() as db:
            db.record_event(event)
            if tokens is None:
                db.record_usage(event.run_id, events.Usage(None, None, None, None, "unavailable", "unavailable"))
            else:
                db.record_usage(event.run_id, events.Usage(*tokens, "fixture", completeness))
        return event

    def add_handoff(self, task, to_agent, passed, from_agent="backend"):
        event = self.event(task, "orchestrator", None, model=None)
        with store.open() as db:
            db.record_event(event)
            db.record_event(replace(event, event_id=str(uuid4()), event_type="handoff", payload={
                "from_agent": from_agent, "to_agent": to_agent, "purpose": "implementation_complete", "passed": passed}))


class FeatureAggregationTest(StoreFixture):
    def test_roles_reworks_missing_and_single_backend_total(self):
        write_doc(self.project, "features/pay", "PRD.md", "draft", "planner")
        self.add_run("pay", "planner", tokens=(80, 8, 0, 0))
        for _ in range(3):
            self.add_run("pay", "backend", tokens=(200, 20, 10, 2))
        self.add_run("pay", "backend", tokens=(50, 5, None, None), completeness="partial")
        self.add_run("pay", "reviewer", tokens=None)
        self.add_handoff("pay", "reviewer", True)
        self.add_run("other", "backend", tokens=(999, 9, 9, 9))
        result = usage_report.feature_usage(self.context, "features/pay")
        self.assertEqual((result["feature"], result["type"], result["completed"], result["runs"]), ("features/pay", "full", False, 6))
        self.assertEqual(result["by_backend"]["claude"]["missing"], 2)
        self.assertEqual(result["total"], {"input_tokens": 680, "output_tokens": 68, "cache_read_tokens": 30, "cache_write_tokens": 6})
        self.assertEqual(result["by_role"]["backend"], {"runs": 4, "reworks": 3, "missing": 1, "input_tokens": 600,
                                                        "input_tokens_by_backend": {"claude": 600}})
        self.assertEqual(result["by_role"]["reviewer"]["input_tokens"], None)
        self.assertIsNone(result["unattributed_runs"])

    def test_multiple_backends_have_no_single_total(self):
        self.add_run("fix/bug", "backend", "claude")
        self.add_run("fix/bug", "reviewer", "codex", tokens=(300, 30, 200, 0))
        result = usage_report.feature_usage(self.context, "fix/bug")
        self.assertIsNone(result["total"])
        self.assertEqual(result["by_backend"]["codex"]["tokens"]["input_tokens"], 300)
        self.assertEqual(result["type"], None)

    def test_cost_from_recorded_snapshot_or_missing_cost(self):
        self.add_run("pay", "backend", model="priced", tokens=(1_000_000, 0, 0, 0))
        self.add_run("pay", "backend", model="unpriced")
        result = usage_report.feature_usage(self.context, "pay")
        self.assertEqual((result["cost"], result["missing_cost"]), ({"USD": "2"}, 1))

    def test_unknown_feature_and_since(self):
        with self.assertRaisesRegex(ValueError, "^no runs or docs for feature: features/none$"):
            usage_report.feature_usage(self.context, "none")
        self.add_run("pay", "backend", ts="2026-10-01T00:00:00+00:00")
        self.add_run("pay", "backend", ts="2026-11-05T00:00:00+00:00")
        self.assertEqual(usage_report.feature_usage(self.context, "pay", since="2026-11-01")["runs"], 1)
        with self.assertRaisesRegex(ValueError, "since must be YYYY-MM-DD"):
            usage_report.feature_usage(self.context, "pay", since="yesterday")

    def test_other_projects_are_not_counted(self):
        self.add_run("pay", "backend", project="proj-b")
        write_doc(self.project, "features/pay", "PRD.md", "draft", "planner")
        self.assertEqual(usage_report.feature_usage(self.context, "pay")["runs"], 0)


class TypeAndRoleStatsTest(StoreFixture):
    def test_completed_only_mean_median_max_and_insufficient_sample(self):
        for index, tokens in enumerate((100, 200, 600)):
            key = f"features/done-{index}"
            complete(self.project, key)
            self.add_run(key.split("/")[1], "backend", tokens=(tokens, 1, 0, 0))
        complete(self.project, "fix/one")
        self.add_run("fix/one", "backend", tokens=(70, 1, 0, 0))
        self.add_run("fix/one", "qa", tokens=None)
        write_doc(self.project, "features/open", "PRD.md", "draft", "planner")
        self.add_run("open", "backend", tokens=(5000, 1, 0, 0))
        self.add_run("ghost", "backend")
        result = usage_report.type_stats(self.context)
        full = result["types"]["full"]["claude"]
        self.assertEqual((full["n"], full["input_tokens"], full.get("status")), (3, {"mean": 300, "median": 200, "max": 600}, None))
        light = result["types"]["light"]["claude"]
        self.assertEqual((light["n"], light["missing_runs"], light["status"]), (1, 1, "insufficient_sample"))
        self.assertEqual(result["types"]["work"], {"n": 0, "status": "no_data"})
        self.assertEqual((result["in_progress_excluded"], result["no_docs_excluded"]), (1, 1))
        self.assertEqual(result["scope"], "completed features only")
        widened = usage_report.type_stats(self.context, include_incomplete=True)
        self.assertEqual(widened["types"]["full"]["claude"]["input_tokens"]["max"], 5000)

    def test_role_and_model_stats_include_in_progress_runs(self):
        self.add_run("aa", "backend", tokens=(100, 1, 0, 0))
        self.add_run("bb", "backend", tokens=(300, 1, 0, 0))
        self.add_run("bb", "backend", "codex", tokens=None, model="gpt")
        self.add_handoff("bb", "reviewer", True)
        roles = usage_report.group_stats(self.context, "role")
        self.assertEqual(roles["roles"]["backend"]["claude"]["input_tokens"], {"mean": 200, "median": 200, "max": 300})
        self.assertEqual(roles["roles"]["backend"]["codex"]["missing_runs"], 1)
        self.assertNotIn("orchestrator", roles["roles"])
        models = usage_report.group_stats(self.context, "model")
        self.assertEqual(set(models["models"]), {"m", "gpt"})


class PerformanceTest(StoreFixture):
    def test_ten_thousand_runs_under_one_second(self):
        rows, usage = [], []
        for index in range(10_000):
            task = f"feat-{index % 200:03d}"
            event = self.event(task, ("planner", "backend", "reviewer")[index % 3], ts=f"2026-11-01T00:00:00.{index:06d}+00:00")
            rows.append((event.run_id, json.dumps(asdict(event)), "proj-a", task, event.ts))
            usage.append((event.run_id, json.dumps(asdict(events.Usage(100, 10, 1, 1, "fixture", "full")))))
        for index in range(0, 200, 2):
            complete(self.project, f"features/feat-{index:03d}")
        with store.open() as db, db.connection:
            db.connection.executemany("INSERT INTO runs(run_id,event_json,project_id,task_id,started_at) VALUES(?,?,?,?,?)", rows)
            db.connection.executemany("INSERT INTO usage VALUES(?,?)", usage)
        started = time.perf_counter()
        result = usage_report.type_stats(self.context)
        elapsed = time.perf_counter() - started
        self.assertEqual(result["types"]["full"]["claude"]["n"], 100)
        self.assertLess(elapsed, 1.0)


if __name__ == "__main__":
    unittest.main()
