"""Token usage report: budget config, feature type/completion, aggregation, quality, budget warning."""

import json
import os
import sqlite3
import tempfile
import time
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from agent_platform_mcp import config, events
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


def complete(project: Path, key: str, track: str | None = None) -> None:
    """Approve every cicd gate prerequisite of the track (ready for release handoff)."""
    track = track or ("light" if key.startswith(config.LIGHT_TRACK_PREFIXES) else "full")
    for file in config.AGENT_PREREQUISITES_BY_TRACK[track]["cicd"]:
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

    def completed(self, key):
        return usage_report.feature_kind(self.project, key)["completed"]

    def test_completed_requires_all_cicd_prerequisites_approved(self):
        write_doc(self.project, "features/big", "PRD.md", "approved", "planner")
        self.assertFalse(self.completed("features/big"))
        complete(self.project, "features/big")
        write_doc(self.project, "features/big", "TEST-PLAN.md", "draft", "qa")
        self.assertFalse(self.completed("features/big"))
        write_doc(self.project, "features/big", "TEST-PLAN.md")
        self.assertTrue(self.completed("features/big"))
        complete(self.project, "fix/small")
        self.assertTrue(self.completed("fix/small"))
        write_doc(self.project, "fix/small", "DB-REVIEW.md", "draft", "dba")
        self.assertFalse(self.completed("fix/small"))

    def test_work_item_is_completed_only_when_ready_for_release_handoff(self):
        """H-3: an approved WORK.md alone starts implementation; it is not completion."""
        write_doc(self.project, "refactor/tiny", "WORK.md", "approved", "backend", "risk: low\n")
        self.assertFalse(self.completed("refactor/tiny"))
        write_doc(self.project, "refactor/tiny", "REVIEW.md", "approved", "reviewer")
        self.assertFalse(self.completed("refactor/tiny"))
        write_doc(self.project, "refactor/tiny", "DB-REVIEW.md", "approved", "dba")
        self.assertTrue(self.completed("refactor/tiny"))
        complete(self.project, "refactor/risky", "work")
        write_doc(self.project, "refactor/risky", "WORK.md", "approved", "backend", "risk: high\nrisk_reason: auth\n")
        self.assertFalse(self.completed("refactor/risky"))
        write_doc(self.project, "refactor/risky", "SECURITY-AUDIT.md", "approved", "security")
        self.assertTrue(self.completed("refactor/risky"))

    def test_archived_is_completed(self):
        write_doc(self.project, "features/old", "PRD.md", "draft", "planner", "archived: true\n")
        self.assertTrue(self.completed("features/old"))
        write_doc(self.project, "refactor/old", "WORK.md", "draft", "backend", "archived: true\n")
        self.assertTrue(self.completed("refactor/old"))

    def test_oversized_doc_reads_as_absent(self):
        path = write_doc(self.project, "features/big", "PRD.md", "draft", "planner", "archived: true\n")
        path.write_text(path.read_text() + "x" * usage_report.MAX_DOC_BYTES, encoding="utf-8")
        self.assertFalse(self.completed("features/big"))

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
        self.assertEqual((result["complete"], result["by_backend"]["claude"]["complete"]), (False, False))
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
        self.assertEqual((full["n"], full["input_tokens"], full.get("status")),
                         (3, {"n": 3, "mean": 300, "median": 200, "max": 600}, None))
        light = result["types"]["light"]["claude"]
        self.assertEqual((light["n"], light["n_total"], light["partially_measured"], light["missing_runs"], light["status"]),
                         (0, 1, 1, 1, "insufficient_sample"))
        self.assertIsNone(light["input_tokens"])
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
        self.assertEqual(roles["roles"]["backend"]["claude"]["input_tokens"], {"n": 2, "mean": 200, "median": 200, "max": 300})
        codex = roles["roles"]["backend"]["codex"]
        self.assertEqual((codex["n"], codex["n_total"], codex["missing_runs"], codex["input_tokens"]), (0, 1, 1, None))
        self.assertNotIn("orchestrator", roles["roles"])
        models = usage_report.group_stats(self.context, "model")
        self.assertEqual(set(models["models"]), {"m", "gpt"})

    def test_partially_measured_feature_is_excluded_from_type_stats(self):
        """H-1 reviewer reproduction: planner 100 + backend 900 per feature, one backend run unmeasured."""
        for index in range(3):
            complete(self.project, f"features/p-{index}")
            self.add_run(f"p-{index}", "planner", tokens=(100, 1, 0, 0))
            self.add_run(f"p-{index}", "backend", tokens=None if index == 2 else (900, 1, 0, 0))
        result = usage_report.type_stats(self.context)
        full = result["types"]["full"]["claude"]
        self.assertEqual(full["input_tokens"], {"n": 2, "mean": 1000, "median": 1000, "max": 1000})
        self.assertEqual((full["n"], full["n_measured"], full["n_total"], full["partially_measured"], full["missing_runs"]),
                         (2, 2, 3, 1, 1))
        self.assertEqual(full["status"], "insufficient_sample")
        self.assertEqual(result["partially_measured"], 1)
        partial = usage_report.feature_usage(self.context, "p-2")
        self.assertEqual((partial["total"]["input_tokens"], partial["complete"]), (100, False))
        self.assertTrue(usage_report.feature_usage(self.context, "p-0")["complete"])

    def test_n_counts_measured_samples_only(self):
        """H-2: n>=3 rows with fewer than 3 measurements are insufficient."""
        for index in range(4):
            complete(self.project, f"features/m-{index}")
            self.add_run(f"m-{index}", "backend", tokens=(100 * (index + 1), 1, 0, 0) if index < 3 else None)
        full = usage_report.type_stats(self.context)["types"]["full"]["claude"]
        self.assertEqual((full["n"], full["n_total"], full.get("status")), (3, 4, None))
        for tokens in ((50, 1, 0, 0), None, None):
            self.add_run("open", "security", tokens=tokens)
        security = usage_report.group_stats(self.context, "role")["roles"]["security"]["claude"]
        self.assertEqual((security["n"], security["n_measured"], security["n_total"], security["missing_runs"], security["status"]),
                         (1, 1, 3, 2, "insufficient_sample"))
        self.assertEqual(security["input_tokens"], {"n": 1, "mean": 50, "median": 50, "max": 50})

    def test_stat_edges_even_median_and_per_key_n(self):
        for index, tokens in enumerate(((100, 1, None, None), (201, 1, 4, 0), (300, 1, 6, 0), (1000, 1, 8, 0))):
            complete(self.project, f"features/e-{index}")
            self.add_run(f"e-{index}", "backend", tokens=tokens)
        full = usage_report.type_stats(self.context)["types"]["full"]["claude"]
        self.assertEqual(full["input_tokens"], {"n": 4, "mean": 400, "median": 250, "max": 1000})
        self.assertEqual(full["cache_read_tokens"], {"n": 3, "mean": 6, "median": 6, "max": 8})
        self.assertEqual(full["n"], 4)

    def test_multi_backend_feature_counts_per_backend_and_exclusions(self):
        for index in range(3):
            complete(self.project, f"features/b-{index}")
            self.add_run(f"b-{index}", "backend", tokens=(100, 1, 0, 0))
            self.add_run(f"b-{index}", "reviewer", "codex", tokens=(300, 1, 0, 0) if index else None)
        types = usage_report.type_stats(self.context)["types"]["full"]
        self.assertEqual((types["claude"]["n"], types["claude"]["partially_measured"]), (2, 1))
        self.assertEqual((types["codex"]["n"], types["codex"]["input_tokens"]["mean"]), (2, 300))

    def test_symlinked_feature_is_skipped_not_fatal(self):
        complete(self.project, "features/ok")
        self.add_run("ok", "backend")
        outside = self.project.parent / "outside"
        complete(outside, "features/link")
        (self.project / "docs" / "features" / "link").symlink_to(outside / "docs" / "features" / "link")
        self.add_run("link", "backend")
        result = usage_report.type_stats(self.context)
        self.assertEqual((result["unsafe_path_excluded"], result["types"]["full"]["claude"]["n_total"]), (1, 1))


class QualityTest(StoreFixture):
    def review(self, task, role, attempt, decision, cycle):
        result = events.ReviewResult(str(uuid4()), cycle, str(uuid4()), "human", role, attempt, decision, "a" * 64, None,
                                     "docs/features/pay/REVIEW.md")
        with store.open() as db:
            db.record_review(result, "proj-a", task)

    def test_quality_from_recorded_sources(self):
        key = "features/pay"
        prd = write_doc(self.project, key, "PRD.md", "approved", "planner")
        prd.write_text(prd.read_text() + "\n## 검토 요청\n\n| # | 항목 | 결정 |\n|---|---|---|\n| A-1 | x | [x] 승인 |\n"
                       "| A-2 | y | [x] 승인 |\n| A-3 | z | [ ] |\n", encoding="utf-8")
        write_doc(self.project, key, "bugs/BUG-001.md", "draft", "qa", "severity: P1\n")
        write_doc(self.project, key, "bugs/BUG-002.md", "draft", "qa", "severity: P3\n")
        write_doc(self.project, key, "bugs/BUG-003.md", "draft", "qa", "severity: P0 | P1 | P2 | P3\n")
        cycle = str(uuid4())
        for attempt, decision in enumerate(("rejected", "rejected", "rejected", "approved"), 1):
            self.review("pay", "reviewer", attempt, decision, cycle)
        for attempt in range(5, 9):  # a second streak of the same role counts again (L-2)
            self.review("pay", "reviewer", attempt, "rejected", cycle)
        self.review("pay", "security", 1, "approved", cycle)
        self.add_handoff("pay", "reviewer", False)
        self.add_handoff("pay", "reviewer", True)
        self.add_handoff("pay", "qa", True)
        self.add_run("pay", "backend")
        result = usage_report.feature_usage(self.context, key)["quality"]
        self.assertEqual(result["rejections"], {"reviewer": 7, "security": 0, "dba": "unknown", "qa": "unknown"})
        self.assertEqual(result["review_cycles"], 8)
        self.assertEqual(result["first_pass_gates"], {"backend": "unknown", "reviewer": False, "security": "unknown",
                                                      "dba": "unknown", "qa": True, "cicd": "unknown"})
        self.assertEqual(result["bugs"], {"P0": 0, "P1": 1, "other": 2})
        self.assertEqual((result["human_interventions"], result["intervention_recommended"]), (4, 2))

    def test_missing_sources_are_unknown_not_zero(self):
        self.add_run("pay", "backend")
        result = usage_report.feature_usage(self.context, "pay")["quality"]
        self.assertEqual(result["review_cycles"], "unknown")
        self.assertEqual(result["bugs"], "unknown")
        self.assertEqual(result["human_interventions"], "unknown")
        self.assertEqual(set(result["first_pass_gates"].values()), {"unknown"})
        write_doc(self.project, "features/pay", "TEST-PLAN.md", "approved", "qa")
        write_doc(self.project, "features/pay", "PRD.md", "approved", "planner")
        result = usage_report.feature_usage(self.context, "pay")["quality"]
        self.assertEqual((result["bugs"], result["human_interventions"]), ({"P0": 0, "P1": 0, "other": 0}, 0))
        self.assertNotIn("score", json.dumps(result))

    def test_type_stats_report_quality_beside_tokens(self):
        for index, reworks in enumerate((0, 1, 3)):
            key = f"features/q-{index}"
            complete(self.project, key)
            write_doc(self.project, key, "TEST-PLAN.md", "approved", "qa")
            for _ in range(reworks + 1):
                self.add_run(f"q-{index}", "backend")
        self.add_handoff("q-0", "qa", True)
        self.add_handoff("q-1", "qa", False)
        result = usage_report.type_stats(self.context)
        self.assertEqual(result["quality"]["full"]["reworks"], {"n": 3, "mean": 1.33, "median": 1, "max": 3})
        self.assertEqual(result["quality"]["full"]["bugs"]["n"], 3)
        self.assertEqual(result["quality"]["full"]["rejections"], {"n": 0})
        self.assertEqual(result["quality"]["full"]["first_pass_gates"], {"n": 2, "passed": 1})
        self.assertEqual(result["types"]["full"]["claude"]["n"], 3)


class ReportEntryTest(StoreFixture):
    """CLI `observe usage` and MCP `usage_report` over an unregistered (allowlisted) root."""

    def setUp(self):
        super().setUp()
        allow = patch.dict(os.environ, {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": str(self.project)})
        allow.start()
        self.addCleanup(allow.stop)
        self.context = projects.ProjectContext(None, self.project)

    def test_cli_feature_and_default_type(self):
        import contextlib
        import io
        from agent_platform_mcp import cli
        self.add_run("fix/bug", "backend", project=None)
        complete(self.project, "fix/bug")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["observe", "usage", "--root", str(self.project), "--feature", "fix/bug"]), 0)
        result = json.loads(out.getvalue())
        self.assertEqual((result["feature"], result["type"], result["completed"], result["runs"]), ("fix/bug", "light", True, 1))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["observe", "usage", "--root", str(self.project)]), 0)
        self.assertEqual(json.loads(out.getvalue())["types"]["light"]["claude"]["n"], 1)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["observe", "usage", "--root", str(self.project), "--since", "bad"]), 1)
            with self.assertRaises(SystemExit):
                cli.main(["observe", "usage", "--root", str(self.project), "--by", "cost"])

    def test_mcp_tool_routes_and_reports_errors(self):
        import asyncio
        from agent_platform_mcp import server
        self.assertIn("usage_report", {tool.name for tool in asyncio.run(server.mcp.list_tools())})
        self.add_run("pay", "backend", project=None)
        self.add_run("pay", "backend", project=None)
        self.assertEqual(server.usage_report(str(self.project), by="role")["roles"]["backend"]["claude"]["n"], 2)
        self.assertEqual(server.usage_report(str(self.project), by="model")["scope"], "all runs")
        self.assertEqual(server.usage_report(str(self.project), feature="pay")["runs"], 2)
        self.assertEqual(server.usage_report(str(self.project), feature="none"), {"error": "no runs or docs for feature: features/none"})
        self.assertEqual(server.usage_report(str(self.project), feature="pay", by="type"), {"error": "use either feature or by, not both"})
        self.assertEqual(server.usage_report(str(self.project), by="cost"), {"error": "by must be one of type, role, model"})
        with patch.object(usage_report, "group_stats", side_effect=sqlite3.OperationalError("disk detail")):
            self.assertEqual(server.usage_report(str(self.project), by="role"), {"error": "OperationalError"})


class BudgetWarningTest(StoreFixture):
    def budget(self, value):
        from agent_platform_mcp import config
        settings = {**config.agent_config(), "token_budget": value}
        mock = patch.object(config, "agent_config", lambda: settings)
        mock.start()
        self.addCleanup(mock.stop)

    def status(self, kind, runs_spec, budget):
        for role, backend, tokens in runs_spec:
            self.add_run("pay", role, backend, tokens=tokens)
        with store.open() as db:
            runs = usage_report._runs(db.connection, self.context, None, "pay")
        return usage_report.budget_status(kind, usage_report.aggregate(runs), runs, {"token_budget": budget})

    def test_status_rules(self):
        cases = [
            ("over", "full", [("backend", "claude", (900, 1, 0, 0))], {"types": {"full": 800}}),
            ("within", "full", [("backend", "claude", (700, 1, 0, 0))], {"types": {"full": 800}}),
            ("over", "full", [("backend", "claude", (500, 1, 0, 0)), ("backend", "codex", None)], {"roles": {"backend": 400}}),
            ("unknown", "full", [("backend", "claude", (700, 1, 0, 0))], {}),
            ("unknown", "full", [("backend", "claude", (700, 1, 0, 0)), ("qa", "claude", None)], {"types": {"full": 800}}),
            ("unknown", "full", [("backend", "claude", (100, 1, 0, 0)), ("qa", "codex", (1, 1, 0, 0))], {"types": {"full": 800}}),
            ("within", "work", [("backend", "claude", (100, 1, 0, 0))], {"roles": {"backend": 400}}),
            ("unknown", "work", [("qa", "claude", (100, 1, 0, 0))], {"roles": {"backend": 400}}),
            ("unknown", "full", [("backend", "claude", (1, 1, 0, 0))], {"types": {"full": -1}}),
        ]
        for expected, kind, runs_spec, budget in cases:
            with self.subTest(expected=expected, budget=budget, runs=runs_spec):
                with store.open() as db, db.connection:
                    db.connection.execute("DELETE FROM runs")
                self.assertEqual(self.status(kind, runs_spec, budget)["status"], expected)
        self.assertEqual(self.status("full", [], {"types": {"full": -1}})["reason"], "invalid token_budget: types.full")

    def test_role_over_and_feature_report_budget(self):
        self.budget({"types": {"full": 1000}, "roles": {"backend": 150}})
        write_doc(self.project, "features/pay", "PRD.md", "draft", "planner")
        self.add_run("pay", "backend", tokens=(200, 1, 0, 0))
        self.add_run("pay", "planner", tokens=(100, 1, 0, 0))
        budget = usage_report.feature_usage(self.context, "pay")["budget"]
        self.assertEqual(budget, {"status": "over", "feature_input_tokens": 300, "limit": 1000, "role_over": ["backend"]})

    def gate(self, **kwargs):
        from agent_platform_mcp.tools import feature, handoff
        import subprocess
        subprocess.run(["git", "init", "-q", str(self.project)], check=True, capture_output=True)
        (self.project / "ARCHITECTURE.md").write_text("# Structure\n", encoding="utf-8")
        for file, agent in (("PRD.md", "planner"), ("TASK.md", "planner"), ("API-SPEC.md", "backend"), ("DECISIONS.md", "backend")):
            write_doc(self.project, "features/pay", file, "approved", agent)
        with patch.dict(os.environ, {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": str(self.project)}):
            gate = feature.gate_check("features/pay", agent="reviewer", root=str(self.project))
            moved = handoff.validate("backend", "reviewer", "features/pay", root=str(self.project), verify=False)
        return gate, moved

    def test_gate_and_handoff_report_usage_without_changing_passed(self):
        gate, moved = self.gate()
        self.assertEqual(gate["usage"]["status"], "unknown")
        baseline = (gate["passed"], moved["passed"], moved["handoff_allowed"])
        self.context = projects.ProjectContext(None, self.project)
        self.add_run("pay", "backend", project=None, tokens=(5000, 1, 0, 0))
        self.budget({"types": {"full": 1000}})
        gate, moved = self.gate()
        self.assertEqual((gate["usage"]["status"], moved["usage"]["status"]), ("over", "over"))
        self.assertEqual((gate["passed"], moved["passed"], moved["handoff_allowed"]), baseline)
        self.budget({"types": {"full": "lots"}})
        gate, _ = self.gate()
        self.assertEqual((gate["usage"]["status"], gate["usage"]["reason"]), ("unknown", "invalid token_budget: types.full"))
        self.assertEqual(gate["passed"], baseline[0])

    def test_gate_without_budget_does_not_create_state_db(self):
        from agent_platform_mcp.tools import feature
        db = Path(os.environ["AGENT_PLATFORM_STATE_DB"])
        write_doc(self.project, "features/pay", "PRD.md", "draft", "planner")
        with patch.dict(os.environ, {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": str(self.project)}):
            self.assertEqual(feature.gate_check("features/pay", root=str(self.project))["usage"]["status"], "unknown")
        self.assertFalse(db.exists())


class ReadOnlyStateTest(StoreFixture):
    """Security L-1: reports and the gate open state.db read-only and never create or migrate it."""

    budget = BudgetWarningTest.budget

    def snapshot(self, db: Path):
        if not db.exists():
            return None
        with sqlite3.connect(db) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        return db.stat().st_mtime_ns, db.stat().st_size, version

    def run_all(self):
        write_doc(self.project, "features/pay", "PRD.md", "draft", "planner")
        self.budget({"types": {"full": 1000}})
        from agent_platform_mcp.tools import feature  # gate only: a handoff records its own point event
        with patch.dict(os.environ, {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": str(self.project)}):
            gate = feature.gate_check("features/pay", root=str(self.project))
        return (gate["usage"], usage_report.feature_usage(self.context, "pay"),
                usage_report.type_stats(self.context), usage_report.group_stats(self.context, "role"))

    def test_missing_db_is_no_data_and_not_created(self):
        db = Path(os.environ["AGENT_PLATFORM_STATE_DB"])
        gate, feature, types, roles = self.run_all()
        self.assertEqual((gate["status"], gate["reason"]), ("unknown", "no state db"))
        self.assertEqual({feature["status"], types["status"], roles["status"]}, {"no_data"})
        self.assertFalse(db.exists())

    def test_old_schema_is_unknown_and_unchanged(self):
        db = Path(os.environ["AGENT_PLATFORM_STATE_DB"])
        with sqlite3.connect(db) as connection:
            connection.execute("PRAGMA user_version=3")
        before = self.snapshot(db)
        gate, feature, types, roles = self.run_all()
        self.assertEqual((gate["status"], gate["reason"]), ("unknown", "state schema not current"))
        self.assertEqual({feature["status"], types["status"], roles["status"]}, {"no_data"})
        self.assertEqual(self.snapshot(db), before)
        self.assertEqual(sorted(Path(db).parent.glob("state.db*")), [db])

    def test_current_db_is_read_without_writes(self):
        db = Path(os.environ["AGENT_PLATFORM_STATE_DB"])
        self.add_run("pay", "backend", project=None, tokens=(5000, 1, 0, 0))
        before = self.snapshot(db)
        self.context = projects.ProjectContext(None, self.project)
        gate, feature, *_ = self.run_all()
        self.assertEqual((gate["status"], feature["runs"]), ("over", 1))
        self.assertEqual(self.snapshot(db), (before[0], before[1], store.SCHEMA_VERSION))


class PerformanceTest(StoreFixture):
    def test_ten_thousand_runs_under_one_second(self):
        rows, usage, event_rows = [], [], []
        for index in range(12_000):
            task = f"feat-{index % 200:03d}"
            point = index >= 10_000  # 2,000 handoff point runs beside 10,000 LLM runs
            event = self.event(task, "orchestrator" if point else ("planner", "backend", "reviewer")[index % 3],
                               ts=f"2026-11-01T00:00:00.{index:06d}+00:00")
            rows.append((event.run_id, json.dumps(asdict(event)), "proj-a", task, event.ts))
            kinds = ("run_started", "handoff") if point else ("run_started", "usage", "run_ended")
            for kind in kinds:
                payload = {"from_agent": "backend", "to_agent": "reviewer", "purpose": "implementation_complete",
                           "passed": True} if kind == "handoff" else {}
                event_rows.append((str(uuid4()), event.run_id, kind, event.ts,
                                   json.dumps(asdict(replace(event, event_type=kind, payload=payload)))))
            if not point:
                usage.append((event.run_id, json.dumps(asdict(events.Usage(100, 10, 1, 1, "fixture", "full")))))
        for index in range(0, 200, 2):
            complete(self.project, f"features/feat-{index:03d}")
        with store.open() as db, db.connection:
            db.connection.executemany("INSERT INTO runs(run_id,event_json,project_id,task_id,started_at) VALUES(?,?,?,?,?)", rows)
            db.connection.executemany("INSERT INTO usage VALUES(?,?)", usage)
            db.connection.executemany("INSERT INTO events VALUES(?,?,?,?,?)", event_rows)
        started = time.perf_counter()
        result = usage_report.type_stats(self.context)
        elapsed = time.perf_counter() - started
        self.assertEqual(result["types"]["full"]["claude"]["n"], 100)
        self.assertEqual(result["quality"]["full"]["first_pass_gates"]["n"], 100)
        self.assertLess(elapsed, 1.0)
        started = time.perf_counter()
        roles = usage_report.group_stats(self.context, "role")["roles"]
        self.assertLess(time.perf_counter() - started, 1.0)
        self.assertNotIn("orchestrator", roles)


if __name__ == "__main__":
    unittest.main()
