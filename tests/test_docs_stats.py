from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

from test_feature_tools import ActiveProjectTestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from docs_stats import collect
from agent_platform_mcp.tools import feature


class DocsStatsTest(ActiveProjectTestCase):
    def test_counts_and_gates_explicit_project_including_nested_items(self):
        self.write_artifact("pay", "PRD.md")
        other = self.resolved_target / "other"
        other.mkdir()
        feature.scaffold("features/pay", root=other)
        (other / "docs/features/pay/PRD.md").write_text("# no metadata")
        feature.scaffold("refactor/db/fix", root=other)
        before = dict(os.environ)
        result = collect(other)
        self.assertEqual(result["items"], 2)
        self.assertEqual(result["gate_pass"], 1)
        self.assertEqual(result["gate_fail"], ["pay"])
        self.assertEqual(before, dict(os.environ))
        self.assertFalse(result["verification_executed"])

    def test_explicit_root_must_be_allowed(self):
        with patch.dict(os.environ, {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": "/nonexistent"}):
            with self.assertRaises(RuntimeError):
                collect(self.resolved_target)
