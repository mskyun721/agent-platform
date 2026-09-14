"""Explicit Claude-owned direct-session recording walkthrough in a temporary project."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import auto
import run_task

sys.path.insert(0, str(run_task.ROOT / "mcp-server/src"))
from agent_platform_mcp.tools import fingerprint, projects, store


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="direct-observation-") as temp:
        root = Path(temp).resolve()
        (root / "app.py").write_text("def subtract(a, b):\n    return a - b\n")
        item = root / "docs/features/observation-smoke"
        item.mkdir(parents=True)
        project_id = "observation-" + uuid4().hex
        decision_id = str(uuid4())
        db_path = root / ".local/state.db"
        command = str(Path(sys.executable).parent / "agent-platform-agent")
        with patch.dict(os.environ, {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": str(root), "AGENT_PLATFORM_STATE_DB": str(db_path)}):
            projects.register(str(root), project_id)
            try:
                code = fingerprint.code_fingerprint(root)["fingerprint"]
                prompt = (
                    f"Direct observation walkthrough. Work only in {root}; no other AI/MCP/delegation or credential access. "
                    f"Use Bash to run {command} state start observation-smoke --role reviewer --backend claude --root {project_id}. "
                    "Read app.py and review whether subtract(a,b) implements a-b. Use the returned run_id to record your owning "
                    f"decision with {command} state review-record observation-smoke --role reviewer --decision approved "
                    f"--artifact docs/features/observation-smoke/REVIEW.md --code-fingerprint {code} --reviewer-id claude-smoke "
                    f"--decision-id {decision_id} --root {project_id} --run-id RUN_ID if correct (rejected if incorrect). "
                    f"Then run {command} state end RUN_ID completed. Do not edit source or launch another process except these CLI commands."
                )
                result = auto.execute(["claude", "-p", prompt, "--strict-mcp-config", "--no-session-persistence",
                                       "--tools", "Read,Bash", "--allowedTools", "Read", f"Bash({command} state *)"], root, 120)
                with store.open(db_path) as db:
                    runs = db.runs(project_id)
                    decisions = db.review_status(project_id, "observation-smoke")
                passed = (result["exit_code"] == 0 and len(runs) == 1 and runs[0]["outcome"] == "completed" and
                          decisions.get("reviewer", {}).get("last_decision") == "approved" and
                          fingerprint.code_fingerprint(root)["fingerprint"] == code)
                print(json.dumps({"passed": passed, "exit_code": result["exit_code"], "reason": result["reason"],
                                  "runs": len(runs), "review_status": decisions, "raw_output_retained": False,
                                  "usage": "unavailable", "source_unchanged": fingerprint.code_fingerprint(root)["fingerprint"] == code}, indent=2))
                return 0 if passed else 1
            finally:
                projects.unregister(project_id)


if __name__ == "__main__":
    raise SystemExit(main())
