"""Descriptive fixture comparisons only; no statistical superiority claims."""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import run_task


def summarize(records: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for record in records:
        if record.get("status") == "checked":
            groups[(record["task"], record["ai"], record.get("instruction_mode"), record.get("task_hash"))].append(record)
    output = []
    for (task, ai, mode, task_hash), rows in sorted(groups.items(), key=lambda item: str(item[0])):
        durations = [row["ai_duration_sec"] for row in rows if row.get("ai_duration_sec") is not None]
        token_fields = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
        values = {key: [row["usage"][key] for row in rows if row.get("usage") and row["usage"].get(key) is not None] for key in token_fields}
        output.append({"task": task, "ai": ai, "instruction_mode": mode, "task_hash": task_hash,
                       "n": len(rows), "passed": sum(row["passed"] for row in rows),
                       "sample_insufficient": len(rows) < 3,
                       "failures": dict(Counter(row.get("failure_reason") or "evaluator" for row in rows if not row["passed"])),
                       "failure_stages": dict(Counter(row.get("evaluator_stage") or "unavailable" for row in rows if not row["passed"])),
                       "ai_duration_mean_sec": sum(durations) / len(durations) if durations else None,
                       "ai_duration_max_sec": max(durations) if durations else None,
                       "tokens": {key: sum(counts) if counts else None for key, counts in values.items()},
                       "token_missing_fields": {key: len(rows) - len(counts) for key, counts in values.items()},
                       "human_interventions": sum(row.get("human_interventions", 0) for row in rows),
                       "cost_estimated": None, "cost_reason": "use state usage for recorded price snapshots; no guessed eval price",
                       "usage_missing": sum(not row.get("usage") or row["usage"].get("completeness") == "unavailable" for row in rows),
                       "platform_revisions": sorted({row.get("platform_revision") or "unknown" for row in rows}),
                       "model_unverified": any(row.get("model") is None for row in rows)})
    return output


def regress(records: list[dict], baseline: dict) -> list[str]:
    latest = {}
    for row in sorted(records, key=lambda item: item.get("checked_at", "")):
        if row.get("status") == "checked":
            latest[(row["task"], row["ai"], row.get("instruction_mode"))] = row
    failures = []
    for expected in baseline["cases"]:
        key = (expected["task"], expected["ai"], expected["instruction_mode"])
        actual = latest.get(key)
        if expected["passed"] and (not actual or not actual["passed"] or actual["task_hash"] != expected["task_hash"]):
            failures.append(":".join(key))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task")
    parser.add_argument("--ai")
    parser.add_argument("--since")
    parser.add_argument("--regress", action="store_true")
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    records = [json.loads(path.read_text()) for path in run_task.RESULTS.glob("*.json")]
    records = [row for row in records if (not args.task or row.get("task") == args.task) and
               (not args.ai or row.get("ai") == args.ai) and
               (not args.since or row.get("started_at", row.get("recorded_at", "")) >= args.since)]
    report = {"groups": summarize(records)}
    if args.regress:
        if args.baseline is None:
            parser.error("--regress requires --baseline")
        report["regressions"] = regress(records, json.loads(args.baseline.read_text()))
    print(json.dumps(report, indent=2))
    return 1 if report.get("regressions") else 0


if __name__ == "__main__":
    raise SystemExit(main())
