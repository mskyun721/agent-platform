"""Feature specs (features/living-feature-spec): slug, work keys, front-matter writer, registry flag."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_platform_mcp import cli, config, frontmatter
from agent_platform_mcp.tools import feature, projects, publish, spec

HOOK = Path(__file__).resolve().parents[1] / "scripts/hooks/platform_hook.py"


@pytest.fixture
def project(tmp_path, monkeypatch):
    base = tmp_path / "projects"
    service = base / "svc"
    (service / "docs").mkdir(parents=True)
    monkeypatch.setenv("AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS", str(base))
    projects.register(str(service), "demo-svc")
    return {"root": "demo-svc", "path": service.resolve(), "base": base}


# --- slug and work keys (BR-14, AC-14) ------------------------------------------------

@pytest.mark.parametrize("slug", ["ab", "payment-cancel", "a1-b2", "x" * 64])
def test_valid_slugs(slug):
    assert spec.validate_slug(slug) == slug


@pytest.mark.parametrize("slug", ["a", "Payment", "1abc", "a/b", "a_b", "x" * 65, "", None, "ab ", "../ab"])
def test_invalid_slugs(slug):
    with pytest.raises(spec.SpecError) as caught:
        spec.validate_slug(slug)
    assert caught.value.code == "invalid_spec_slug"


def test_slug_rule_is_one_feature_name_segment():
    assert feature.FEATURE_NAME_RE.pattern == rf"^{spec.SLUG_RE.pattern}(?:/{spec.SLUG_RE.pattern})*$"


def test_work_key_normalization():
    assert spec.normalize_work_key("pay") == "features/pay"
    assert spec.normalize_work_key("features/pay") == "features/pay"
    assert spec.normalize_work_key("fix/login-bug") == "fix/login-bug"
    with pytest.raises(spec.SpecError) as caught:
        spec.normalize_work_key("specs/pay")
    assert caught.value.code == "reserved_type"
    with pytest.raises(spec.SpecError) as caught:
        spec.normalize_work_key("Bad Name")
    assert caught.value.code == "invalid_work"


def test_specs_type_is_reserved_for_scaffold_gate_and_publish(project):
    with pytest.raises(ValueError, match="reserved for feature specs"):
        feature.scaffold("specs/pay", root=project["root"])
    with pytest.raises(ValueError, match="reserved for feature specs"):
        feature.gate_check("specs/pay", root=project["root"])
    assert "reserved for feature specs" in publish.publish_feature("specs/pay", root=project["root"])["error"]
    assert not (project["path"] / "docs" / "specs").exists()
    # A bare `specs` is an ordinary feature name (docs/features/specs).
    assert feature.scaffold("specs", root=project["root"])["feature"] == "specs"


def test_linked_spec_and_archived_flags():
    assert spec.linked_spec({"spec": "pay"}) == ("pay", None)
    assert spec.linked_spec({}) == (None, None)
    assert spec.linked_spec(None) == (None, None)
    slug, error = spec.linked_spec({"spec": "Pay Ment"})
    assert slug is None and error == "invalid spec slug: Pay Ment"
    assert spec.is_archived({"archived": "true"}) and spec.is_archived({"archived": "True"})
    assert not spec.is_archived({"archived": "false"}) and not spec.is_archived({}) and not spec.is_archived(None)


# --- front-matter writer (L-1) ----------------------------------------------------------

DOC = "---\nagent: planner\nstatus: draft\nlinks:\n  task: docs/x/TASK.md\nupdated: 2026-01-01\n---\n\n# Body\nstatus: not front-matter\n"


def test_frontmatter_update_sets_adds_and_removes_keeping_other_bytes():
    out = frontmatter.update(DOC, {"status": "approved", "archived": "true"})
    assert out == DOC.replace("status: draft", "status: approved").replace("updated: 2026-01-01\n",
                                                                         "updated: 2026-01-01\narchived: true\n")
    assert frontmatter.parse(out)["links"] == {"task": "docs/x/TASK.md"}
    assert frontmatter.update(out, {"archived": None}) == DOC.replace("status: draft", "status: approved")
    assert frontmatter.update(DOC, {"missing": None}) == DOC  # removing an absent key is a no-op


def test_frontmatter_update_refuses_unsafe_changes():
    with pytest.raises(ValueError, match="front-matter missing"):
        frontmatter.update("# no front-matter\n", {"status": "draft"})
    with pytest.raises(ValueError, match="is a block"):
        frontmatter.update(DOC, {"links": "x"})
    for value in ("two\nlines", "", '"quoted"'):
        with pytest.raises(ValueError):
            frontmatter.update(DOC, {"title": value})
    with pytest.raises(ValueError, match="invalid front-matter key"):
        frontmatter.update(DOC, {"bad key": "x"})


def test_frontmatter_update_drops_duplicate_keys():
    text = "---\nstatus: draft\nstatus: review\n---\n"
    assert frontmatter.update(text, {"status": "approved"}) == "---\nstatus: approved\n---\n"


# --- atomic, contained writes (BR-15, AC-15) -----------------------------------------------

def test_write_inside_replaces_atomically_and_keeps_mode(tmp_path):
    base = tmp_path / "docs"
    base.mkdir()
    target = base / "a.md"
    target.write_text("old", encoding="utf-8")
    os.chmod(target, 0o640)
    spec.write_inside(target, "new", tmp_path, base)
    assert target.read_text(encoding="utf-8") == "new"
    assert target.stat().st_mode & 0o777 == 0o640
    assert sorted(p.name for p in base.iterdir()) == ["a.md"]


def test_interrupted_write_keeps_the_original(tmp_path, monkeypatch):
    base = tmp_path / "docs"
    base.mkdir()
    target = base / "a.md"
    target.write_text("old", encoding="utf-8")

    def crash(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(spec.os, "replace", crash)
    with pytest.raises(OSError):
        spec.write_inside(target, "new", tmp_path, base)
    assert target.read_text(encoding="utf-8") == "old"
    assert sorted(p.name for p in base.iterdir()) == ["a.md"]  # no temp file left


def test_write_inside_refuses_symlinks_and_escapes(tmp_path):
    base = tmp_path / "docs"
    base.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("keep", encoding="utf-8")
    link = base / "link.md"
    link.symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        spec.write_inside(link, "x", tmp_path, base)
    with pytest.raises(spec.SpecError, match="escapes"):
        spec.write_inside(tmp_path / "other.md", "x", tmp_path, base)
    linked_dir = base / "dir"
    linked_dir.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        spec.write_inside(linked_dir / "outside.md", "x", tmp_path, base)
    assert outside.read_text(encoding="utf-8") == "keep"


# --- per-project spec_required (BR-3, BR-16, N-1) --------------------------------------------

def test_spec_required_defaults_false_and_is_set_per_project(project, tmp_path):
    other = project["base"] / "other"
    other.mkdir()
    projects.register(str(other), "other-svc")
    assert projects.spec_required("demo-svc") is False
    assert projects.spec_required(None) is False
    assert projects.set_spec_required("demo-svc", True) == {"project_id": "demo-svc", "spec_required": True}
    assert projects.spec_required("demo-svc") is True and projects.spec_required("other-svc") is False
    assert projects.list_projects()["projects"][0]["spec_required"] is True
    projects.set_spec_required("demo-svc", False)
    assert projects.spec_required("demo-svc") is False
    with pytest.raises(ValueError, match="unknown project_id"):
        projects.set_spec_required("missing", True)
    with pytest.raises(ValueError, match="true or false"):
        projects.set_spec_required("demo-svc", "true")


def test_project_spec_set_cli(project, capsys):
    assert cli.main(["project-spec-set", "demo-svc", "--required", "true"]) == 0
    assert json.loads(capsys.readouterr().out) == {"project_id": "demo-svc", "spec_required": True}
    assert projects.spec_required("demo-svc") is True
    assert cli.main(["project-spec-set", "nope", "--required", "false"]) == 1


def test_project_spec_set_asks_the_user_in_the_hook():
    for command in ("agent-platform-agent project-spec-set svc --required false",
                    "uv --directory mcp-server run agent-platform-agent project-spec-set svc --required true"):
        payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}})
        result = subprocess.run([sys.executable, str(HOOK)], input=payload, text=True, capture_output=True, check=True)
        assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "ask", command


# --- resolution errors by type (BR-16, N-4) -------------------------------------------------

def test_no_default_target_raises_project_not_found():
    with pytest.raises(projects.ProjectNotFound) as caught:
        projects.resolve(None)
    assert isinstance(caught.value, RuntimeError)  # old `except RuntimeError` handlers still match


def test_ambiguous_folder_name_raises_project_ambiguous(tmp_path, monkeypatch):
    first, second = tmp_path / "a" / "svc", tmp_path / "b" / "svc"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    monkeypatch.setenv("AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS", os.pathsep.join([str(tmp_path / "a"), str(tmp_path / "b")]))
    projects.register(str(first), "svc-a")
    projects.register(str(second), "svc-b")
    with pytest.raises(projects.ProjectAmbiguous) as caught:
        projects.resolve("svc")
    assert isinstance(caught.value, RuntimeError)
    assert config.ProjectAmbiguous is projects.ProjectAmbiguous


# --- helpers for work items ---------------------------------------------------------------------

def write_doc(path: Path, body: str = "# doc\n", **meta: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = {"agent": "planner", "feature": "x", "status": "draft", "created": "2026-01-01",
              "updated": "2026-01-02", **meta}
    path.write_text("---\n" + "".join(f"{k}: {v}\n" for k, v in fields.items()) + "---\n\n" + body,
                    encoding="utf-8")
    return path


def work(project_path: Path, key: str, **meta: str) -> Path:
    item = project_path / "docs" / key
    write_doc(item / "PRD.md", **meta)
    return item


# --- spec new / list (AC-1) -------------------------------------------------------------------

def test_spec_new_creates_the_six_section_skeleton(project, capsys):
    result = spec.spec_new("payment-cancel", "결제 취소", root=project["root"])
    assert result == {"spec": "payment-cancel", "path": "docs/specs/payment-cancel/SPEC.md", "status": "created"}
    text = (project["path"] / result["path"]).read_text(encoding="utf-8")
    meta = frontmatter.parse(text)
    assert meta["spec"] == "payment-cancel" and meta["title"] == "결제 취소" and meta["status"] == "draft"
    assert spec.DATE_RE.fullmatch(meta["created"]) and spec.DATE_RE.fullmatch(meta["updated"])
    for heading in ("## 1. 개요·목적", "## 2. 업무 규칙", "## 3. API", "## 4. DB", "## 5. 서비스 로직", "## 6. 변경 이력"):
        assert f"\n{heading}\n" in text
    assert "# SPEC: 결제 취소" in text and "<title>" not in text and "<spec-slug>" not in text
    assert spec.history_table(text.split("\n"))[1] == []
    assert spec.spec_new("payment-cancel", "again", root=project["root"]) == {
        "error": "spec already exists: payment-cancel", "code": "spec_exists"}
    assert spec.spec_new("Bad", "x", root=project["root"])["code"] == "invalid_spec_slug"
    assert spec.spec_new("ok-slug", "two\nlines", root=project["root"])["code"] == "invalid_title"
    assert cli.main(["spec", "new", "refund", "--title", "환불", "--root", project["root"]]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "created"
    assert cli.main(["spec", "new", "refund", "--title", "환불", "--root", project["root"]]) == 1


def test_spec_new_refuses_a_symlinked_specs_dir(project, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (project["path"] / "docs" / "specs").symlink_to(elsewhere, target_is_directory=True)
    assert "symlink" in spec.spec_new("pay", "Pay", root=project["root"])["error"]
    assert list(elsewhere.iterdir()) == []


def test_spec_list_groups_work_items_by_front_matter(project, capsys):
    spec.spec_new("pay", "결제", root=project["root"])
    work(project["path"], "features/pay-cancel", spec="pay", status="approved")
    work(project["path"], "fix/pay-bug", spec="pay")
    work(project["path"], "features/old", spec="pay", archived="true")
    work(project["path"], "features/loose")
    work(project["path"], "features/gone", archived="true")
    work(project["path"], "features/ghost", spec="nope")
    work(project["path"], "features/bad", spec="Not Valid")
    (project["path"] / "docs" / "db").mkdir()
    write_doc(project["path"] / "docs" / "db" / "DB-CATALOG.md")  # not a work item: no PRD/WORK folder
    result = spec.spec_list(root=project["root"])
    assert result["specs"] == [{"spec": "pay", "title": "결제", "status": "draft", "updated": result["specs"][0]["updated"],
                                "work_items": [{"key": "features/old", "status": "draft", "archived": True},
                                               {"key": "features/pay-cancel", "status": "approved", "archived": False},
                                               {"key": "fix/pay-bug", "status": "draft", "archived": False}]}]
    assert result["unlinked_work_items"] == ["features/bad", "features/loose"]
    assert result["unknown_spec_work_items"] == [
        {"key": "features/bad", "spec": None, "error": "invalid spec slug: Not Valid"},
        {"key": "features/ghost", "spec": "nope", "error": None}]
    assert cli.main(["spec", "list", "--root", project["root"]]) == 0
    assert json.loads(capsys.readouterr().out) == result


# --- spec history-add (AC-4, AC-14) ---------------------------------------------------------

PR = "https://github.com/acme/svc/pull/12"


def test_history_add_appends_once_per_work_and_pr(project):
    spec.spec_new("pay", "결제", root=project["root"])
    path = project["path"] / "docs/specs/pay/SPEC.md"
    added = spec.spec_history_add("pay", "pay-cancel", "취소 API 추가", pr=PR, date="2026-11-20", root=project["root"])
    assert added["status"] == "added"
    assert added["row"] == f"| 2026-11-20 | features/pay-cancel | 취소 API 추가 | [#12]({PR}) |"
    before = path.read_bytes()
    # The same work item under its normalized and bare key, same PR → duplicate, no write.
    for key in ("pay-cancel", "features/pay-cancel"):
        assert spec.spec_history_add("pay", key, "다시", pr=PR, root=project["root"])["status"] == "duplicate"
    assert path.read_bytes() == before
    spec.spec_history_add("pay", "pay-cancel", "후속", pr=PR.replace("12", "13"), date="2026-11-21", root=project["root"])
    spec.spec_history_add("pay", "fix/pay-bug", "a | b\nc", date="2026-11-22", root=project["root"])
    end, rows = spec.history_table(path.read_text(encoding="utf-8").split("\n"))
    assert [row[1] for row in rows] == ["features/pay-cancel", "features/pay-cancel", "fix/pay-bug"]
    assert rows[2] == ["2026-11-22", "fix/pay-bug", "a \\| b c", "-"]
    assert spec.spec_history_add("pay", "fix/pay-bug", "x", root=project["root"])["status"] == "duplicate"
    meta = frontmatter.read(path)
    assert meta["updated"] == spec._today() and meta["status"] == "draft"


def test_history_add_validates_input(project):
    spec.spec_new("pay", "결제", root=project["root"])
    path = project["path"] / "docs/specs/pay/SPEC.md"
    before = path.read_bytes()
    for bad in ("http://github.com/a/b/pull/1", "javascript:alert(1)", "https://x/a b", "https://x/(a)"):
        assert spec.spec_history_add("pay", "w-x", "s", pr=bad, root=project["root"]) == {
            "error": "invalid pr url", "code": "invalid_pr_url"}
    assert spec.spec_history_add("pay", "w-x", "s" * 201, root=project["root"])["code"] == "invalid_summary"
    assert spec.spec_history_add("pay", "w-x", "  ", root=project["root"])["code"] == "invalid_summary"
    assert spec.spec_history_add("pay", "w-x", "s", date="2026-13-40", root=project["root"])["code"] == "invalid_date"
    assert spec.spec_history_add("pay", "specs/pay", "s", root=project["root"])["code"] == "reserved_type"
    assert spec.spec_history_add("nope", "w-x", "s", root=project["root"]) == {
        "error": "spec not found: nope", "code": "spec_not_found"}
    assert path.read_bytes() == before
    path.write_text(before.decode().replace("| 날짜 | 작업 | 요약 | PR |\n|---|---|---|---|\n", ""), encoding="utf-8")
    assert spec.spec_history_add("pay", "w-x", "s", root=project["root"]) == {
        "error": "SPEC change-history table not found", "code": "history_table_missing"}


def test_history_table_ignores_fenced_examples():
    lines = ["## 5. x", "```", "## 6. 변경 이력", "| a | b | c | d |", "|---|---|---|---|", "```", "## 6. 변경 이력",
             "", "| 날짜 | 작업 | 요약 | PR |", "|---|---|---|---|", "| 1 | 2 | 3 | 4 |", "", "## 7. 다음"]
    assert spec.history_table(lines) == (11, [["1", "2", "3", "4"]])


def test_history_add_cli(project, capsys):
    spec.spec_new("pay", "결제", root=project["root"])
    argv = ["spec", "history-add", "pay", "--work", "fix/a-b", "--summary", "s", "--pr", PR, "--root", project["root"]]
    assert cli.main(argv) == 0 and json.loads(capsys.readouterr().out)["status"] == "added"
    assert cli.main(argv) == 0 and json.loads(capsys.readouterr().out)["status"] == "duplicate"


# --- feature-archive (AC-10, AC-15) ------------------------------------------------------------

def finish(item: Path) -> None:
    for name in ("RELEASE-NOTE.md", "PR-BODY.md", "DEPLOY-CHECKLIST.md"):
        write_doc(item / name, agent="cicd", status="approved")


def test_archive_refuses_unfinished_work_unless_forced(project, capsys):
    item = work(project["path"], "features/pay-cancel", status="approved")
    before = (item / "PRD.md").read_bytes()
    assert spec.feature_archive("pay-cancel", root=project["root"]) == {
        "error": "work item is not finished; pass --force", "code": "archive_in_progress"}
    write_doc(item / "RELEASE-NOTE.md", agent="cicd", status="draft")
    assert spec.feature_archive("pay-cancel", root=project["root"])["code"] == "archive_in_progress"
    assert (item / "PRD.md").read_bytes() == before
    assert cli.main(["feature-archive", "pay-cancel", "--force", "--root", project["root"]]) == 0
    assert json.loads(capsys.readouterr().out)["archived"] is True
    assert spec.is_archived(frontmatter.read(item / "PRD.md"))


def test_archive_marks_every_doc_keeps_updated_and_undoes(project):
    item = work(project["path"], "features/pay-cancel", status="approved")
    finish(item)
    (item / "notes.md").write_text("no front-matter\n", encoding="utf-8")
    result = spec.feature_archive("features/pay-cancel", root=project["root"])
    assert result["feature"] == "features/pay-cancel" and result["archived"] is True
    assert result["changed"] == ["DEPLOY-CHECKLIST.md", "PR-BODY.md", "PRD.md", "RELEASE-NOTE.md"]
    assert result["skipped_no_frontmatter"] == ["notes.md"]
    for name in result["changed"]:
        meta = frontmatter.read(item / name)
        assert meta["archived"] == "true" and meta["updated"] == "2026-01-02"
    assert spec.feature_archive("pay-cancel", root=project["root"])["changed"] == []  # idempotent
    original = (item / "PRD.md").read_text(encoding="utf-8")
    assert spec.feature_archive("pay-cancel", undo=True, root=project["root"])["archived"] is False
    assert "archived" not in frontmatter.read(item / "PRD.md")
    assert (item / "PRD.md").read_text(encoding="utf-8") == original.replace("archived: true\n", "")


def test_archive_work_contract_uses_work_md(project):
    item = project["path"] / "docs/features/small"
    write_doc(item / "WORK.md", status="draft", contract="work-v1")
    assert spec.feature_archive("small", root=project["root"])["code"] == "archive_in_progress"
    write_doc(item / "WORK.md", status="approved", contract="work-v1")
    assert spec.feature_archive("small", root=project["root"])["changed"] == ["WORK.md"]


def test_archive_refuses_symlinks_reserved_and_missing(project, tmp_path):
    item = work(project["path"], "features/pay-cancel")
    outside = write_doc(tmp_path / "outside.md")
    before = outside.read_bytes()
    (item / "LINK.md").symlink_to(outside)
    assert "symlink" in spec.feature_archive("pay-cancel", force=True, root=project["root"])["error"]
    assert outside.read_bytes() == before
    assert spec.feature_archive("specs/pay", force=True, root=project["root"])["code"] == "reserved_type"
    assert spec.feature_archive("nothing", force=True, root=project["root"])["code"] == "feature_not_found"


def test_mcp_lists_spec_tools():
    import asyncio

    from agent_platform_mcp import server

    names = {tool.name for tool in asyncio.run(server.mcp.list_tools())}
    assert {"spec_new", "spec_list", "spec_history_add", "feature_archive"} <= names


# --- spec index (BR-5, AC-5) ----------------------------------------------------------------------

def index_fixture(project):
    spec.spec_new("pay", "결제 | 취소", root=project["root"])
    spec.spec_new("refund", "환불", root=project["root"])
    spec.spec_history_add("pay", "pay-cancel", "취소", pr=PR, date="2026-11-20", root=project["root"])
    spec.spec_history_add("pay", "hotfix/pay-crash", "긴급", date="2026-11-21", root=project["root"])
    item = work(project["path"], "features/pay-cancel", spec="pay", status="approved")
    write_doc(item / "TASK.md")
    work(project["path"], "fix/pay-bug", spec="pay")
    work(project["path"], "features/old", spec="refund", archived="true")
    work(project["path"], "fix/old-bug", archived="true")
    work(project["path"], "features/loose")
    work(project["path"], "features/ghost", spec="nope")


def test_spec_index_writes_front_matter_view(project, capsys):
    index_fixture(project)
    result = spec.spec_index(root=project["root"])
    assert result == {"path": "docs/specs/INDEX.md", "specs": 2, "work_items": 6, "archived": 2}
    path = project["path"] / "docs/specs/INDEX.md"
    text = path.read_text(encoding="utf-8")
    assert text == "\n".join([
        "<!-- generated by spec index; do not edit -->", "# 기능 목록", "",
        "| 기능 | 상태 | 최근 변경 | 진행 중 작업 |", "|---|---|---|---|",
        "| [결제 \\| 취소](pay/SPEC.md) | draft | 2026-11-21 · hotfix/pay-crash | "
        "features/pay-cancel (PRD: approved, TASK: draft); fix/pay-bug (PRD: draft) |",
        "| [환불](refund/SPEC.md) | draft | - | - |", "",
        "## 연결 안 된 작업", "", "| 작업 | spec 값 | 문서 상태 |", "|---|---|---|",
        "| features/ghost | nope | PRD: draft |", "| features/loose | - | PRD: draft |", "",
        "## 보관", "", "| 작업 | 기능 |", "|---|---|", "| features/old | refund |", "| fix/old-bug | - |", ""])
    # No machine-specific values: no absolute paths, no page links; the same input → same bytes.
    assert str(project["path"]) not in text and "notion.so" not in text and "atlassian" not in text
    assert spec.spec_index(root=project["root"]) == result and path.read_text(encoding="utf-8") == text
    assert cli.main(["spec", "index", "--root", project["root"]]) == 0
    assert json.loads(capsys.readouterr().out) == result


def approve(project, *slugs):
    for slug in slugs:
        path = project["path"] / "docs/specs" / slug / "SPEC.md"
        path.write_text(path.read_text(encoding="utf-8").replace("status: draft", "status: approved", 1),
                        encoding="utf-8")


def test_remote_index_leaves_out_fix_and_hotfix_names(project):
    index_fixture(project)
    approve(project, "pay", "refund")
    spec.spec_history_add("pay", "pay-cancel", "후속", pr=PR.replace("12", "14"), date="2026-11-22", root=project["root"])
    text, _ = spec.index_markdown(project["path"], remote=True)
    for name in ("fix/pay-bug", "fix/old-bug", "hotfix/pay-crash"):
        assert name not in text
    assert "](pay/SPEC.md)" not in text and "| 결제 \\| 취소 | approved | 2026-11-22 · features/pay-cancel · #14 |" in text
    assert "비공개 결함 작업(fix/·hotfix/) 2건" in text
    spec.spec_history_add("pay", "hotfix/again", "긴급", date="2026-11-23", root=project["root"])
    assert "2026-11-23 · (비공개)" in spec.index_markdown(project["path"], remote=True)[0]


def test_spec_index_refuses_a_symlinked_index(project, tmp_path):
    spec.spec_new("pay", "결제", root=project["root"])
    outside = tmp_path / "outside.md"
    outside.write_text("keep", encoding="utf-8")
    (project["path"] / "docs/specs/INDEX.md").symlink_to(outside)
    assert "symlink" in spec.spec_index(root=project["root"])["error"]
    assert outside.read_text(encoding="utf-8") == "keep"


def test_spec_index_scales_to_100_specs_and_500_work_items(project):
    import time

    docs = project["path"] / "docs"
    for number in range(100):
        slug = f"spec-{number:03d}"
        directory = docs / "specs" / slug
        directory.mkdir(parents=True)
        text = (config.TEMPLATES_DIR / "SPEC.md").read_text(encoding="utf-8").replace("<spec-slug>", slug)
        (directory / "SPEC.md").write_text(text + f"| 2026-11-20 | features/w-{number:03d} | s | - |\n", encoding="utf-8")
    for number in range(500):
        item = work(project["path"], f"features/w-{number:03d}", spec=f"spec-{number % 100:03d}",
                    **({"archived": "true"} if number % 5 == 0 else {}))
        write_doc(item / "TASK.md")
    started = time.perf_counter()
    result = spec.spec_index(root=project["root"])
    elapsed = time.perf_counter() - started
    assert result == {"path": "docs/specs/INDEX.md", "specs": 100, "work_items": 500, "archived": 100}
    assert elapsed < 2.0, elapsed


# --- gate `spec` report (BR-3, AC-3) -----------------------------------------------------------

def backend_ready(project):
    (project["path"] / "ARCHITECTURE.md").write_text("# arch\n", encoding="utf-8")
    item = work(project["path"], "features/pay-cancel", feature="pay-cancel", status="approved")
    write_doc(item / "TASK.md", feature="pay-cancel", status="approved")
    return item


def test_gate_reports_spec_status_without_blocking_by_default(project):
    item = backend_ready(project)
    report = feature.gate_check("pay-cancel", root=project["root"])["spec"]
    assert report == {"status": "not_applicable", "spec": None, "required": False, "blocks_backend": False}
    spec.spec_new("pay", "결제", root=project["root"])
    result = feature.gate_check("pay-cancel", agent="backend", root=project["root"])
    assert result["spec"]["status"] == "missing" and result["passed"] is True
    write_doc(item / "PRD.md", feature="pay-cancel", status="approved", spec="refund")
    assert feature.gate_check("pay-cancel", root=project["root"])["spec"]["status"] == "unknown_spec"
    write_doc(item / "PRD.md", feature="pay-cancel", status="approved", spec="Bad Slug")
    report = feature.gate_check("pay-cancel", root=project["root"])["spec"]
    assert report["status"] == "unknown_spec" and report["reason"] == "invalid spec slug: Bad Slug"
    write_doc(item / "PRD.md", feature="pay-cancel", status="approved", spec="pay")
    report = feature.gate_check("pay-cancel", root=project["root"])["spec"]
    assert report == {"status": "ok", "spec": "pay", "required": False, "blocks_backend": False}


def test_spec_required_blocks_only_the_backend_handoff(project):
    from agent_platform_mcp.tools import handoff

    item = backend_ready(project)
    spec.spec_new("pay", "결제", root=project["root"])
    projects.set_spec_required("demo-svc", True)
    result = feature.gate_check("pay-cancel", agent="backend", root=project["root"])
    assert result["passed"] is False and result["spec"]["blocks_backend"] is True
    assert result["agent_gate"]["passed"] is False
    assert any("spec link" in entry for entry in result["agent_gate"]["missing"])
    assert feature.gate_check("pay-cancel", root=project["root"])["passed"] is True  # report-only without agent
    assert handoff.validate("planner", "backend", "pay-cancel", root=project["root"])["passed"] is False
    write_doc(item / "PRD.md", feature="pay-cancel", status="approved", spec="pay")
    assert feature.gate_check("pay-cancel", agent="backend", root=project["root"])["passed"] is True
    assert handoff.validate("planner", "backend", "pay-cancel", root=project["root"])["passed"] is True
    projects.set_spec_required("demo-svc", False)
    write_doc(item / "PRD.md", feature="pay-cancel", status="approved")
    assert feature.gate_check("pay-cancel", agent="backend", root=project["root"])["passed"] is True


def test_gate_spec_is_not_applicable_on_the_platform_root():
    root = config.ROOT.resolve()
    item = root / "docs" / "features" / "spec-probe"
    try:
        write_doc(item / "PRD.md", feature="spec-probe")
        (root / "docs" / "specs").mkdir(exist_ok=True)
        assert feature.gate_check("spec-probe", root=str(root))["spec"]["status"] == "not_applicable"
    finally:
        import shutil

        shutil.rmtree(item)
        if (root / "docs" / "specs").is_dir() and not any((root / "docs" / "specs").iterdir()):
            (root / "docs" / "specs").rmdir()


# --- spec bootstrap (BR-9, AC-9, AC-17) --------------------------------------------------------

def tree_hashes(root: Path) -> dict[str, str]:
    import hashlib

    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file() and not path.is_symlink()}


def bootstrap_fixture(project):
    base = project["path"]
    item = work(base, "features/pay-cancel", status="approved")
    write_doc(item / "API-SPEC.md", status="approved", body=(
        "| Method | `POST` |\n| Path | `/v1/payments/{id}/cancel` |\n\n"
        "- GET /api/v1/payments/{id} returns it.\n- curl -X POST https://api.example.com/v1/x\n"))
    write_doc(item / "TASK.md", status="draft")
    linked = work(base, "features/refund-flow", status="approved", spec="refund")
    write_doc(linked / "API-SPEC.md", status="approved", body="`DELETE /refunds/{id}`\n")
    work(base, "features/old", status="approved", archived="true")
    work(base, "fix/draft-only", status="draft")
    write_doc(base / "docs/db/DB-CATALOG.md", agent="dba", body=(
        "## 2. 테이블\n| 테이블 | 역할 |\n|---|---|\n| `payment` | 결제 |\n| `refund` | 환불 |\n| `audit_log` | 감사 |\n\n"
        "## 3. 인덱스 대비 쿼리\n| 쿼리 | 테이블 |\n|---|---|\n| `findAll` | payment |\n"))
    migration = base / "src/main/resources/db/migration"
    migration.mkdir(parents=True)
    for name in ("V1__create_payment.sql", "V2__create_refunds.sql", "V3__audit.sql"):
        (migration / name).write_text("-- ddl\n", encoding="utf-8")
    (base / "build/db/migration").mkdir(parents=True)
    (base / "build/db/migration/V9__generated.sql").write_text("-- ignored\n", encoding="utf-8")
    (base / "src/main/kotlin").mkdir(parents=True)
    (base / "src/main/kotlin/App.kt").write_text("fun main() {}\n", encoding="utf-8")


def test_spec_bootstrap_groups_sources_without_writing(project, capsys):
    bootstrap_fixture(project)
    spec.spec_new("refund", "환불", root=project["root"])
    before = tree_hashes(project["path"])
    result = spec.spec_bootstrap(root=project["root"])
    assert tree_hashes(project["path"]) == before  # docs/ and source tree unchanged, nothing added
    assert result["candidates"] == [
        {"suggested_slug": "payments", "existing_spec": False,
         "work_items": [{"key": "features/pay-cancel", "docs": ["docs/features/pay-cancel/API-SPEC.md",
                                                                 "docs/features/pay-cancel/PRD.md"]}],
         "operations": [{"method": "GET", "path": "/api/v1/payments/{id}",
                         "source": "docs/features/pay-cancel/API-SPEC.md"},
                        {"method": "POST", "path": "/v1/payments/{id}/cancel",
                         "source": "docs/features/pay-cancel/API-SPEC.md"}],
         "migrations": ["src/main/resources/db/migration/V1__create_payment.sql"], "tables": ["payment"]},
        {"suggested_slug": "refund", "existing_spec": True,
         "work_items": [{"key": "features/refund-flow", "docs": ["docs/features/refund-flow/API-SPEC.md",
                                                                  "docs/features/refund-flow/PRD.md"]}],
         "operations": [{"method": "DELETE", "path": "/refunds/{id}",
                         "source": "docs/features/refund-flow/API-SPEC.md"}],
         "migrations": ["src/main/resources/db/migration/V2__create_refunds.sql"], "tables": ["refund"]}]
    assert result["unassigned"] == {"work_items": ["fix/draft-only"],
                                    "migrations": ["src/main/resources/db/migration/V3__audit.sql"],
                                    "tables": ["audit_log"]}
    assert "# doc" not in json.dumps(result, ensure_ascii=False)  # identifiers only, no bodies
    assert cli.main(["spec", "bootstrap", "--root", project["root"]]) == 0
    assert json.loads(capsys.readouterr().out) == result
    assert tree_hashes(project["path"]) == before


def test_spec_bootstrap_on_an_empty_project(project):
    assert spec.spec_bootstrap(root=project["root"])["candidates"] == []


def test_mcp_lists_index_and_bootstrap():
    import asyncio

    from agent_platform_mcp import server

    names = {tool.name for tool in asyncio.run(server.mcp.list_tools())}
    assert {"spec_index", "spec_bootstrap"} <= names


# --- REVIEW-core / SECURITY-AUDIT-core fixes (T-1) ---------------------------------------------

def snapshot(item: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(item.iterdir()) if not path.is_symlink()}


def test_archive_with_a_symlinked_file_changes_nothing(project, tmp_path):
    # Review M-1 (repro 1): API-SPEC.md and DECISIONS.md sort before LINK.md, PRD.md after it.
    item = work(project["path"], "features/pay", status="approved")
    write_doc(item / "API-SPEC.md")
    write_doc(item / "DECISIONS.md")
    outside = write_doc(tmp_path / "outside.md")
    (item / "LINK.md").symlink_to(outside)
    before, outside_before = snapshot(item), outside.read_bytes()
    result = spec.feature_archive("pay", force=True, root=project["root"])
    assert result["code"] == "archive_invalid" and result["file"] == "LINK.md" and result["changed"] == []
    assert "symlink" in result["error"] and "no file was changed" in result["error"]
    assert snapshot(item) == before and outside.read_bytes() == outside_before


def test_archive_with_a_block_style_archived_key_changes_nothing(project):
    # Review M-1 (repro 2): `archived:` as a block in PRD.md, API-SPEC.md sorts first.
    item = work(project["path"], "features/pay", status="approved")
    write_doc(item / "API-SPEC.md")
    prd = item / "PRD.md"
    prd.write_text(prd.read_text(encoding="utf-8").replace("status: approved\n", "status: approved\narchived:\n  x: y\n"),
                   encoding="utf-8")
    before = snapshot(item)
    result = spec.feature_archive("pay", force=True, root=project["root"])
    assert result["code"] == "archive_invalid" and result["file"] == "PRD.md" and "is a block" in result["error"]
    assert snapshot(item) == before


def test_archive_rolls_back_when_a_write_fails(project, monkeypatch):
    item = work(project["path"], "features/pay", status="approved")
    for name in ("API-SPEC.md", "DECISIONS.md", "TASK.md"):
        write_doc(item / name)
    before = snapshot(item)
    real = spec.write_inside
    calls = []

    def flaky(path, text, *args):
        calls.append(path.name)
        if path.name == "PRD.md" and len(calls) == 3:
            raise OSError("disk full")
        return real(path, text, *args)

    monkeypatch.setattr(spec, "write_inside", flaky)
    result = spec.feature_archive("pay", force=True, root=project["root"])
    assert result["code"] == "archive_write_failed" and result["file"] == "PRD.md"
    assert result["rolled_back"] == ["API-SPEC.md", "DECISIONS.md"] and result["changed"] == []
    assert snapshot(item) == before

    def broken(path, text, *args):  # every write after the first fails, rollback included
        calls.append(path.name)
        if len(calls) > 1:
            raise OSError("read-only")
        return real(path, text, *args)

    calls.clear()
    monkeypatch.setattr(spec, "write_inside", broken)
    result = spec.feature_archive("pay", force=True, root=project["root"])
    assert result["code"] == "archive_write_failed" and result["file"] == "DECISIONS.md"
    assert result["rolled_back"] == [] and result["changed"] == ["API-SPEC.md"]  # exactly what is left changed


@pytest.mark.parametrize("key", ["experience/security", "db/catalog", "specs-x/pay", "other/pay"])
def test_archive_accepts_only_work_types(project, key):
    item = work(project["path"], key)
    before = snapshot(item)
    result = spec.feature_archive(key, force=True, root=project["root"])
    assert result["code"] == "invalid_work_type" and snapshot(item) == before


def test_archive_allows_every_work_type(project):
    for key in ("features/a-b", "fix/a-b", "hotfix/a-b", "refactor/a-b", "research/a-b"):
        work(project["path"], key)
        assert spec.feature_archive(key, force=True, root=project["root"])["changed"] == ["PRD.md"], key


def test_archive_and_history_add_keep_crlf(project):
    item = work(project["path"], "features/pay")
    prd = item / "PRD.md"
    prd.write_bytes(prd.read_bytes().replace(b"\n", b"\r\n"))
    original = prd.read_bytes()
    spec.feature_archive("pay", force=True, root=project["root"])
    text = prd.read_bytes()
    assert b"archived: true\r\n" in text and b"\n" not in text.replace(b"\r\n", b"")
    spec.feature_archive("pay", undo=True, root=project["root"])
    assert prd.read_bytes() == original
    spec.spec_new("pay", "결제", root=project["root"])
    path = project["path"] / "docs/specs/pay/SPEC.md"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert spec.spec_history_add("pay", "pay", "s", root=project["root"])["status"] == "added"
    text = path.read_bytes()
    assert b"| features/pay | s | - |\r\n" in text and b"\n" not in text.replace(b"\r\n", b"")
    assert spec.spec_history_add("pay", "pay", "s", root=project["root"])["status"] == "duplicate"


def test_spec_required_blocks_even_without_a_specs_directory(project):
    # Review M-2, option (b).
    item = backend_ready(project)
    assert not (project["path"] / "docs/specs").exists()
    report = feature.gate_check("pay-cancel", agent="backend", root=project["root"])
    assert report["spec"]["status"] == "not_applicable" and report["passed"] is True  # report-only default
    projects.set_spec_required("demo-svc", True)
    result = feature.gate_check("pay-cancel", agent="backend", root=project["root"])
    assert result["spec"] == {"status": "missing", "spec": None, "required": True, "blocks_backend": True}
    assert result["passed"] is False
    write_doc(item / "PRD.md", feature="pay-cancel", status="approved", spec="pay")
    report = feature.gate_check("pay-cancel", agent="backend", root=project["root"])
    assert report["spec"]["status"] == "unknown_spec" and report["passed"] is False
    assert not (project["path"] / "docs/specs").exists()  # the gate never creates it


def test_remote_index_hides_the_pr_link_of_a_defect_row(project):
    spec.spec_new("pay", "결제", root=project["root"])
    approve(project, "pay")
    spec.spec_history_add("pay", "hotfix/leak-token", "긴급", pr="https://github.com/acme/svc/pull/99",
                          date="2026-11-23", root=project["root"])
    remote, _ = spec.index_markdown(project["path"], remote=True)
    assert "| 결제 | approved | 2026-11-23 · (비공개) | - |" in remote
    assert "#99" not in remote and "github.com" not in remote and "leak-token" not in remote
    local, _ = spec.index_markdown(project["path"])
    assert "hotfix/leak-token · [#99](https://github.com/acme/svc/pull/99)" in local  # git copy unchanged


@pytest.mark.parametrize("cell", ["Fix/x-y", "HOTFIX/x-y", "[fix/x-y](https://github.com/a/b/pull/1)",
                                  "`hotfix/x-y`", "**fix/x-y**", "<b>fix/x-y</b>", "작업 메모"])
def test_remote_index_hides_hand_edited_defect_rows(project, cell):
    spec.spec_new("pay", "결제", root=project["root"])
    approve(project, "pay")
    path = project["path"] / "docs/specs/pay/SPEC.md"
    path.write_text(path.read_text(encoding="utf-8") + f"| 2026-11-23 | {cell} | s | [#7](https://github.com/a/b/pull/7) |\n",
                    encoding="utf-8")
    remote, _ = spec.index_markdown(project["path"], remote=True)
    assert "2026-11-23 · (비공개) |" in remote and "x-y" not in remote and "#7" not in remote


@pytest.mark.parametrize("day, pr", [
    ("<img src=x onerror=a()>", "[x](javascript:alert(1))"),
    ("2026-11-23 <b>x</b>", "<a href=https://e.test>PR</a>"),
    ("2026/11/23", "[#7](http://github.com/a/b/pull/7)"),
    ("2026-11-23", "![i](https://e.test/i.png)"),
])
def test_remote_index_drops_hand_edited_date_and_pr_cells(project, day, pr):
    """N-1: in remote mode only a YYYY-MM-DD date and a history-add PR link survive."""
    spec.spec_new("pay", "결제", root=project["root"])
    approve(project, "pay")
    path = project["path"] / "docs/specs/pay/SPEC.md"
    path.write_text(path.read_text(encoding="utf-8") + f"| {day} | features/ok | s | {pr} |\n", encoding="utf-8")
    remote, _ = spec.index_markdown(project["path"], remote=True)
    row = next(line for line in remote.splitlines() if line.startswith("| 결제 |"))
    expected = "2026-11-23 · features/ok" if day == "2026-11-23" else "features/ok"
    assert row == f"| 결제 | approved | {expected} | - |"
    local, _ = spec.index_markdown(project["path"])
    assert pr in local  # the git copy is unchanged


def test_remote_index_keeps_history_add_cells(project):
    """Security 4b L-2: the kept PR cell is `#n` only, without the repository URL."""
    spec.spec_new("pay", "결제", root=project["root"])
    approve(project, "pay")
    spec.spec_history_add("pay", "features/ok", "s", pr="https://github.com/a/b/pull/7", date="2026-11-23",
                          root=project["root"])
    spec.spec_history_add("pay", "features/ok2", "s", pr="https://github.com/a/b/issues/8", date="2026-11-24",
                          root=project["root"])
    remote, _ = spec.index_markdown(project["path"], remote=True)
    assert "| 2026-11-24 · features/ok2 · #8 |" in remote and "github.com" not in remote


def test_remote_index_lists_approved_specs_only(project):
    """Security 4b L-3: a draft SPEC, its title and its work stay out of the remote INDEX."""
    index_fixture(project)
    approve(project, "refund")
    remote, _ = spec.index_markdown(project["path"], remote=True)
    assert "| 환불 | approved |" in remote and "features/old" in remote
    assert "결제" not in remote and "pay-cancel" not in remote and "| pay |" not in remote
    assert "승인 전 SPEC 1건과 그 작업은 표시하지 않는다." in remote
    local, _ = spec.index_markdown(project["path"])
    assert "결제" in local and "features/pay-cancel" in local  # the git copy lists every SPEC


def test_remote_history_hides_defect_rows_and_reduces_pr_cells():
    """Review 4b M-1: the published SPEC §6 follows the remote INDEX rule."""
    text = "\n".join([
        "# SPEC", "", "## 6. 변경 이력", "| 날짜 | 작업 | 요약 | PR |", "|---|---|---|---|",
        "| 2026-11-20 | features/pay | 결제 추가 | [#3](https://github.com/acme/svc/pull/3) |",
        "| 2026-11-21 | hotfix/leak-1 | token leak fix | [#9](https://github.com/acme/svc/pull/9) |",
        "| 2026-11-22 | Fix/x | 수동 | - |", "| bad row |", "", "## 7. 기타", "| a | b |"])
    remote = spec.remote_history(text)
    assert "| 2026-11-20 | features/pay | 결제 추가 | #3 |" in remote
    assert "| 2026-11-21 | (비공개) | - | - |" in remote and "| 2026-11-22 | (비공개) | - | - |" in remote
    assert "| - | (비공개) | - | - |" in remote
    for leaked in ("leak", "token", "github.com", "#9", "Fix/x", "bad row"):
        assert leaked not in remote, leaked
    assert remote.endswith("## 7. 기타\n| a | b |")
    assert spec.remote_history("# no history\n") == "# no history\n"
    with pytest.raises(spec.SpecError) as raised:
        spec.remote_history("## 6. 변경 이력\n- hotfix/leak-1 was a list\n")
    assert raised.value.code == "history_unparsed"


def test_remote_history_hides_rows_after_a_blank_line_and_under_a_second_heading():
    """Review 4b RL-1 / Security RA-L1: every `|` row of every §6 section is rewritten."""
    text = "\n".join([
        "## 6. 변경 이력", "| 날짜 | 작업 | 요약 | PR |", "|---|---|---|---|",
        "| 2026-01-01 | features/pay | 결제 | [#1](https://github.com/o/priv/pull/1) |", "",
        "| 2026-01-02 | hotfix/leak-token | leak detail | [#5](https://github.com/o/priv/pull/5) |", "",
        "## 6. 변경 이력 (계속)", "| 날짜 | 작업 | 요약 | PR |", "|---|---|---|---|",
        "| 2026-01-03 | fix/second-leak | second detail | [#6](https://github.com/o/priv/pull/6) |",
        "| 2026-01-04 | features/later | 후속 | [#7](https://github.com/o/priv/pull/7) |",
        "| 날짜 | fix/header-shaped | header leak | x |", "|---|---|---|---|",
        "", "## 7. 기타", "| hotfix/kept | outside §6 |"])
    remote = spec.remote_history(text)
    assert remote.count("| 날짜 | 작업 | 요약 | PR |") == 2
    assert "| 2026-01-01 | features/pay | 결제 | #1 |" in remote and "| 2026-01-04 | features/later | 후속 | #7 |" in remote
    assert "| 2026-01-02 | (비공개) | - | - |" in remote and "| 2026-01-03 | (비공개) | - | - |" in remote
    assert "| - | (비공개) | - | - |" in remote  # the header-shaped fix/ row is a row, not a header
    for leaked in ("leak-token", "leak detail", "second-leak", "second detail", "header leak", "github.com", "#5", "#6"):
        assert leaked not in remote, leaked
    assert remote.endswith("## 7. 기타\n| hotfix/kept | outside §6 |")  # other sections stay as written


@pytest.mark.parametrize("section, rows_only", [
    ("| 날짜 | 작업 | 요약 | PR |\n|---|---|---|---|\n\nhotfix/leak-1 was prose", False),
    ("| 날짜 | 작업 | 요약 | PR |\n|---|---|---|---|\n```\n| 2026-01-02 | hotfix/leak | x | - |\n```", False),
    ("| 날짜 | 작업 | 요약 | PR |\n|---|---|---|---|\n### 6.1 hotfix/leak-1", False),
    ("| 2026-01-02 | hotfix/leak | x | - |", True),  # rows, but no history table header anywhere
    ("| a | b | c |\n|---|---|---|", True),  # a table that is not the history table
])
def test_remote_history_stops_on_unparsed_section_content(section, rows_only):
    """Review 4b RL-1: §6 content that is not a history row is never sent."""
    with pytest.raises(spec.SpecError) as raised:
        spec.remote_history(f"# SPEC\n\n## 6. 변경 이력\n{section}\n")
    assert raised.value.code == "history_unparsed"
    second = f"## 6. 변경 이력\n| 날짜 | 작업 | 요약 | PR |\n|---|---|---|---|\n\n## 6. 이어서\n{section}\n"
    if rows_only:  # after a history header, `|` lines anywhere in §6 are rows and are hidden
        remote = spec.remote_history(second)
        assert "leak" not in remote and "| a |" not in remote
    else:  # a second §6 section is held to the same rule
        with pytest.raises(spec.SpecError):
            spec.remote_history(second)
    assert spec.remote_history("```\n## 6. in a fence\nprose\n```\n") == "```\n## 6. in a fence\nprose\n```\n"


def test_remote_history_cleans_the_date_of_hidden_rows():
    """Review 4b RL-3 (mutation H6): a hidden row keeps only a date history-add would write."""
    text = ("## 6. 변경 이력\n| 날짜 | 작업 | 요약 | PR |\n|---|---|---|---|\n"
            "| <b>x</b> | hotfix/leak | x | - |\n| 2026/01/02 | fix/leak | x | - |\n| 2026-01-03 | fix/ok | x | - |")
    remote = spec.remote_history(text)
    assert remote.count("| - | (비공개) | - | - |") == 2 and "| 2026-01-03 | (비공개) | - | - |" in remote
    assert "<b>" not in remote and "2026/01/02" not in remote


def test_defect_work_detection():
    for cell in ("features/pay", "refactor/pay-x", "pay", "features/prefix-fix"):
        assert spec.is_defect_work(cell) is False, cell
    for cell in ("fix/a-b", "Fix/a-b", "features/hotfix/a-b", "[fix/a-b](u)", "", "-"):
        assert spec.is_defect_work(cell) is True, cell


def test_markup_in_title_and_summary_is_neutralized(project):
    title = "<img src=https://t/p.gif> ![i](https://t/i.png) [a](javascript:alert(1)) end\\"
    spec.spec_new("pay", title, root=project["root"])
    path = project["path"] / "docs/specs/pay/SPEC.md"
    escaped = spec._escape_cell(title)
    assert escaped == ("\\<img src=https://t/p.gif\\> \\!\\[i\\](https://t/i.png) "
                       "\\[a\\](javascript:alert(1)) end\\\\")
    assert f"# SPEC: {escaped}\n" in path.read_text(encoding="utf-8")
    assert frontmatter.read(path)["title"] == title  # front-matter keeps the raw value
    row = spec.spec_history_add("pay", "pay", "<script>x</script> ![p](u) a\\", root=project["root"])["row"]
    assert row == "| " + spec._today() + " | features/pay | \\<script\\>x\\</script\\> \\!\\[p\\](u) a\\\\ | - |"
    assert len(spec.cells(row)) == 4  # the trailing backslash does not swallow the column
    text, _ = spec.index_markdown(project["path"])
    assert f"| [{escaped}](pay/SPEC.md) |" in text and "<img" not in text.replace("\\<img", "")


def test_escaped_backslash_pipe_never_adds_a_column(project):
    spec.spec_new("pay", "결제", root=project["root"])
    row = spec.spec_history_add("pay", "pay", "a\\|b | c\\\\", root=project["root"])["row"]
    assert "| a\\\\\\|b \\| c\\\\\\\\ |" in row
    assert spec.cells(row)[2] == "a\\\\\\|b \\| c\\\\\\\\"
    assert spec.cells("| a\\\\| b |") == ["a\\\\", "b"]  # `\\|`: escaped backslash, then a column
    assert spec.cells("| a\\| b |") == ["a\\| b"]
    assert spec.spec_history_add("pay", "pay", "다시", root=project["root"])["status"] == "duplicate"


def test_pr_url_variants_are_one_pr(project):
    spec.spec_new("pay", "결제", root=project["root"])
    assert spec.spec_history_add("pay", "pay", "s", pr=PR, root=project["root"])["status"] == "added"
    for variant in (PR + "/", PR + "#issuecomment-1", PR + "?w=1", PR + "/#x"):
        assert spec.spec_history_add("pay", "pay", "s", pr=variant, root=project["root"])["status"] == "duplicate"
    added = spec.spec_history_add("pay", "fix/a-b", "s", pr=PR + "/files#diff", root=project["root"])
    assert added["row"].endswith(f"| [PR]({PR}/files) |")
    added = spec.spec_history_add("pay", "fix/c-d", "s", pr=PR + "/", root=project["root"])
    assert added["row"].endswith(f"| [#12]({PR}) |")
    assert spec.spec_history_add("pay", "pay", "s", pr="https://#x", root=project["root"])["code"] == "invalid_pr_url"


def test_spec_new_failures_return_a_code_and_leave_no_directory(project, monkeypatch):
    assert spec.spec_new("pay", '"quoted"', root=project["root"])["code"] == "invalid_title"
    assert not (project["path"] / "docs/specs/pay").exists()

    def crash(*args, **kwargs):
        raise OSError("disk full")

    real = spec.write_inside
    monkeypatch.setattr(spec, "write_inside", crash)
    result = spec.spec_new("pay", "결제", root=project["root"])
    assert result == {"error": "disk full", "code": "write_failed"}
    assert not (project["path"] / "docs/specs/pay").exists()
    monkeypatch.setattr(spec, "write_inside", real)
    assert spec.spec_new("pay", "결제", root=project["root"])["status"] == "created"  # retry is not spec_exists


def test_bootstrap_reads_operations_only_from_approved_api_specs(project):
    item = work(project["path"], "features/pay-cancel", status="approved")
    write_doc(item / "API-SPEC.md", status="draft", body="- POST /v1/payments/{id}/cancel\n")
    (candidate,) = spec.spec_bootstrap(root=project["root"])["candidates"]
    assert candidate["operations"] == [] and candidate["suggested_slug"] == "pay-cancel"
    assert candidate["work_items"] == [{"key": "features/pay-cancel", "docs": ["docs/features/pay-cancel/PRD.md"]}]


def test_concurrent_history_adds_keep_every_row(project):
    import threading

    spec.spec_new("pay", "결제", root=project["root"])
    real_read = spec.read_raw

    def slow_read(path):  # widen the read-modify-write window
        text = real_read(path)
        threading.Event().wait(0.02)
        return text

    spec.read_raw = slow_read
    try:
        results = []
        threads = [threading.Thread(target=lambda n=n: results.append(
            spec.spec_history_add("pay", f"features/w-{n:02d}", "s", root=project["root"]))) for n in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        spec.read_raw = real_read
    assert [result["status"] for result in results] == ["added"] * 8
    rows = spec.history_table((project["path"] / "docs/specs/pay/SPEC.md").read_text(encoding="utf-8").split("\n"))[1]
    assert sorted(row[1] for row in rows) == [f"features/w-{n:02d}" for n in range(8)]


def test_register_keeps_an_existing_record_and_unregister_keeps_spec_required(project):
    projects.set_spec_required("demo-svc", True)
    with pytest.raises(ValueError, match="already registered"):
        projects.register(str(project["path"]), "demo-svc-2")
    with pytest.raises(ValueError, match="already registered"):
        projects.register(str(project["path"]), "demo-svc")
    with pytest.raises(RuntimeError, match="spec_required is on"):
        projects.unregister("demo-svc")
    assert projects.spec_required("demo-svc") is True
    projects.set_spec_required("demo-svc", False)
    assert projects.unregister("demo-svc")["removed"] is True
