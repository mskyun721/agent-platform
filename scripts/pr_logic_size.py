#!/usr/bin/env python3
"""Conservative committed-PR logic size report; never reads excluded file bodies."""

import argparse
import ast
import difflib
import io
import json
import subprocess
import tokenize
from pathlib import Path

CONFIG_SUFFIXES = {".json", ".yaml", ".yml", ".toml", ".ini", ".properties", ".xml", ".lock"}
DOCUMENT_SUFFIXES = {".md", ".txt", ".rst", ".mmd"}


def excluded(path: str) -> str | None:
    name = Path(path).name.lower()
    if any(word in name for word in (".env", ".pem", ".key", "secret", "credential")):
        return "protected; body not read"
    if any(part.lower() in {"tests", "test", "__tests__", "testfixtures"} for part in Path(path).parts) or name.startswith("test_") or name.endswith(("test.kt", "test.java", ".test.ts", ".spec.ts")):
        return "test"
    if Path(path).suffix.lower() in CONFIG_SUFFIXES or name in {".gitignore", "dockerfile", ".dockerignore"}:
        return "configuration"
    if Path(path).suffix.lower() in DOCUMENT_SUFFIXES:
        return "documentation"
    return None


def logic_lines(source: str, suffix: str) -> tuple[set[int], str]:
    if not source:
        return set(), "exact"
    if suffix != ".py":
        return {i for i, line in enumerate(source.splitlines(), 1) if line.strip()}, "conservative; manual classification needed"
    try:
        tree = ast.parse(source)
        ignored = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
                ignored.append(((node.lineno, node.col_offset), (node.end_lineno, node.end_col_offset)))
        lines = source.splitlines(keepends=True)
        def byte_position(position):
            row, column = position
            return row, len(lines[row - 1][:column].encode("utf-8")) if row <= len(lines) else column
        code = set()
        skip = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER, tokenize.ENCODING}
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type in skip or token.string == ";":
                continue
            start, end = byte_position(token.start), byte_position(token.end)
            if any(left <= start and end <= right for left, right in ignored):
                continue
            code.update(range(token.start[0], token.end[0] + 1))
        return code, "exact"
    except (SyntaxError, tokenize.TokenError, IndentationError):
        return {i for i, line in enumerate(source.splitlines(), 1) if line.strip()}, "conservative; parse error"


def compare(path: str, old: str, new: str) -> dict:
    old_logic, old_mode = logic_lines(old, Path(path).suffix)
    new_logic, new_mode = logic_lines(new, Path(path).suffix)
    added = deleted = 0
    for tag, a, b, c, d in difflib.SequenceMatcher(None, old.splitlines(), new.splitlines(), autojunk=False).get_opcodes():
        if tag in {"delete", "replace"}:
            deleted += len(old_logic.intersection(range(a + 1, b + 1)))
        if tag in {"insert", "replace"}:
            added += len(new_logic.intersection(range(c + 1, d + 1)))
    return {"path": path, "added_logic": added, "deleted_logic": deleted, "logic_lines": added + deleted,
            "classification": "exact" if old_mode == new_mode == "exact" else f"{old_mode}; {new_mode}"}


def report(repo: Path, base: str, head: str = "HEAD", limit: int = 500) -> dict:
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be positive")
    def git(*args):
        result = subprocess.run(["git", *args], cwd=repo, capture_output=True, timeout=15, check=False)
        if result.returncode:
            raise ValueError(f"Git {args[0]} failed; check revisions and repository")
        return result.stdout
    base_revision = git("rev-parse", "--verify", "--end-of-options", base + "^{commit}").decode().strip()
    head_revision = git("rev-parse", "--verify", "--end-of-options", head + "^{commit}").decode().strip()
    comparison = git("merge-base", base_revision, head_revision).decode().strip()
    def paths(revision):
        return {name.decode("utf-8") for name in git("ls-tree", "-r", "--name-only", "-z", revision).split(b"\0") if name}
    old_paths, new_paths = paths(comparison), paths(head_revision)
    changed = [value.decode("utf-8") for value in git("diff", "--no-ext-diff", "--no-renames", "--name-only", "-z", comparison, head_revision).split(b"\0") if value]
    rows, exclusions = [], []
    for path in changed:
        reason = excluded(path)
        if reason:
            exclusions.append({"path": path, "reason": reason})
            continue
        old = git("cat-file", "blob", f"{comparison}:{path}") if path in old_paths else b""
        new = git("cat-file", "blob", f"{head_revision}:{path}") if path in new_paths else b""
        try:
            if b"\0" in old or b"\0" in new:
                raise UnicodeError()
            rows.append(compare(path, old.decode("utf-8"), new.decode("utf-8")))
        except UnicodeError:
            rows.append({"path": path, "logic_lines": None, "classification": "binary/unclassified"})
    total = sum(row["logic_lines"] or 0 for row in rows)
    unknown = any(row["logic_lines"] is None for row in rows)
    return {"scope": "committed_pr", "base_ref": base, "comparison_revision": comparison, "head_revision": head_revision,
            "logic_lines": total, "limit": limit, "within_limit": None if unknown else total <= limit,
            "manual_review_required": any(row["classification"] != "exact" for row in rows),
            "files": rows, "excluded": exclusions, "pending_changes_included": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args()
    result = report(args.repo, args.base, args.head)
    print(json.dumps(result, indent=2))
    return 0 if result["within_limit"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
