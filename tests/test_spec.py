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
