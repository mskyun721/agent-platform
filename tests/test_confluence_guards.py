"""Confluence feature sync guards shared with Notion: symlink/outside paths (REVIEW re-review
issue 2, DECISIONS ADR-012) and the secret scan (SECURITY M-2, ADR-011). httpx is mocked;
existing outputs for ordinary files are covered unchanged by tests/test_confluence.py."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from agent_platform_mcp import config
from agent_platform_mcp.tools import confluence, projects, publish

AWS_KEY = "AKIA" + "Q3XZ7P2M9K4L8N5R"
_FLOW = (config.ROOT / "templates" / "FLOW.drawio").read_text(encoding="utf-8")


def _resp(status: int, body: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body
    return resp


class FakeConfluence:
    def __init__(self) -> None:
        self.posts: list[dict] = []
        self.next_id = 900

    def get(self, url, **kwargs):
        if url.endswith("/spaces"):
            return _resp(200, {"results": [{"id": "~s", "key": "PROJ"}]})
        return _resp(200, {"results": [{"id": "111", "title": "Sprint"}]})

    def post(self, url, **kwargs):
        self.posts.append({"url": url, **kwargs})
        if kwargs.get("files"):
            return _resp(200, {"results": [{"id": "att"}]})
        self.next_id += 1
        return _resp(201, {"id": str(self.next_id), "spaceId": "~s", "title": kwargs["json"]["title"]})

    def sent(self) -> str:
        out = []
        for call in self.posts:
            if call.get("json"):
                out.append(json.dumps(call["json"], ensure_ascii=False))
            for _, (name, data, _) in (call.get("files") or {}).items():
                out.append(name + data.decode("utf-8", "replace"))
        return "\n".join(out)

    def titles(self) -> list[str]:
        return [c["json"]["title"] for c in self.posts if c.get("json")]


@pytest.fixture
def remote(monkeypatch):
    fake = FakeConfluence()
    monkeypatch.setattr(confluence.httpx, "get", fake.get)
    monkeypatch.setattr(confluence.httpx, "post", fake.post)
    for name, value in (("CONFLUENCE_URL", "https://example.atlassian.net"),
                        ("CONFLUENCE_EMAIL", "user@example.com"), ("CONFLUENCE_API_TOKEN", "fake-token")):
        monkeypatch.setenv(name, value)
    return fake


@pytest.fixture
def feature(tmp_path, monkeypatch):
    base = tmp_path / "projects"
    service = base / "svc"
    feature_dir = service / "docs" / "features" / "demo"
    feature_dir.mkdir(parents=True)
    (feature_dir / "PRD.md").write_text("# PRD\n\n## 1. 개요\n- 요약\n", encoding="utf-8")
    (feature_dir / "TASK.md").write_text("# TASK\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS", str(base))
    projects.register(str(service), "demo-svc")
    return {"dir": feature_dir, "root": "demo-svc", "outside": tmp_path}


def run(feature, **kwargs):
    return confluence.sync_feature("PROJ", "Sprint", "demo", root=feature["root"], **kwargs)


def test_symlinked_or_outside_md_is_skipped_like_the_dry_run(feature, remote):
    outside = feature["outside"] / "outside.md"
    outside.write_text("OUTSIDE_SENTINEL\n", encoding="utf-8")
    (feature["dir"] / "LINK.md").symlink_to(outside)
    result = run(feature)
    by_file = {r["file"]: r for r in result["results"]}
    assert by_file["LINK.md"] == {"file": "LINK.md", "status": "skipped",
                                  "error": "symlink or outside feature directory"}
    assert [by_file[f]["status"] for f in ("PRD.md", "TASK.md")] == ["created", "created"]
    assert "OUTSIDE_SENTINEL" not in remote.sent() and "LINK" not in remote.titles()
    assert "- LINK" not in remote.posts[0]["json"]["body"]["value"]  # overview lists published pages only

    projects.set_publish("demo-svc", "confluence", confluence_space_key="PROJ", confluence_parent_title="Sprint")
    planned = publish.publish_feature("demo", root=feature["root"], dry_run=True)["result"]
    real = {f for f, r in by_file.items() if r["status"] == "skipped"}
    assert set(planned["skipped"]) == real and set(planned["files"]) == set(by_file) - real


def test_symlinked_flow_is_not_attached(feature, remote):
    outside = feature["outside"] / "outside.drawio"
    outside.write_text(_FLOW.replace("처리 성공?", "FLOW_SENTINEL", 1), encoding="utf-8")
    (feature["dir"] / "FLOW.drawio").symlink_to(outside)
    result = run(feature)
    assert result["attachments"] == [{"file": "FLOW.drawio", "status": "skipped",
                                      "error": "symlink or outside feature directory"}]
    assert "FLOW_SENTINEL" not in remote.sent()


def test_md_with_a_secret_is_skipped_and_never_sent(feature, remote):
    (feature["dir"] / "TASK.md").write_text(f"# TASK\nkey {AWS_KEY}\n", encoding="utf-8")
    result = run(feature)
    task = next(r for r in result["results"] if r["file"] == "TASK.md")
    assert task == {"file": "TASK.md", "status": "skipped", "error": "secret pattern detected: aws-access-key"}
    assert AWS_KEY not in remote.sent() and "TASK" not in remote.titles()


def test_prd_and_flow_secrets_stay_out_of_overview_and_attachment(feature, remote):
    (feature["dir"] / "PRD.md").write_text(f"# PRD\n\n## 1. 개요\n- {AWS_KEY}\n", encoding="utf-8")
    (feature["dir"] / "FLOW.drawio").write_text(_FLOW.replace("처리 성공?", AWS_KEY, 1), encoding="utf-8")
    result = run(feature)
    assert AWS_KEY not in remote.sent()
    assert result["attachments"] == [{"file": "FLOW.drawio", "status": "skipped",
                                      "error": "secret pattern detected: aws-access-key"}]
    assert "PRD.md 제외" in remote.posts[0]["json"]["body"]["value"]


def test_publish_feature_confluence_reports_secret_skip_and_stays_published(feature, remote):
    projects.set_publish("demo-svc", "confluence", confluence_space_key="PROJ", confluence_parent_title="Sprint")
    (feature["dir"] / "TASK.md").write_text(AWS_KEY, encoding="utf-8")
    planned = publish.publish_feature("demo", root=feature["root"], dry_run=True)
    assert planned["result"]["skipped"] == ["TASK.md"] and remote.posts == []
    result = publish.publish_feature("demo", root=feature["root"])
    assert result["status"] == "published"
    assert AWS_KEY not in json.dumps(result) and AWS_KEY not in remote.sent()


def test_ordinary_files_keep_the_previous_output(feature, remote):
    result = run(feature)
    assert result["attachments"] == []
    assert [(r["file"], r["status"]) for r in result["results"]] == [("PRD.md", "created"), ("TASK.md", "created")]
    assert set(result["results"][0]) == {"file", "status", "url"}
    assert remote.titles() == ["demo", "PRD", "TASK"]


# --- round 3: REVIEW R3-1/R3-2/R3-4, SECURITY L-3/L-4 ------------------------

def _secret_everywhere(feature):
    for name in ("PRD.md", "TASK.md"):
        (feature["dir"] / name).write_text(f"# {name}\n{AWS_KEY}\n", encoding="utf-8")


def test_no_publishable_md_makes_no_remote_call(feature, remote, monkeypatch):
    """R3-1: every .md skipped → no overview page, nothing sent, skipped reported."""
    gets = []
    monkeypatch.setattr(confluence.httpx, "get", lambda *a, **k: gets.append(a) or remote.get(*a, **k))
    _secret_everywhere(feature)
    result = run(feature)
    assert remote.posts == [] and gets == []
    assert "overview" not in result and result["warning"].startswith("No publishable .md files")
    assert [(r["file"], r["status"]) for r in result["results"]] == [("PRD.md", "skipped"), ("TASK.md", "skipped")]


def test_publish_feature_confluence_all_skipped_is_skipped_for_dry_run_and_real(feature, remote):
    projects.set_publish("demo-svc", "confluence", confluence_space_key="PROJ", confluence_parent_title="Sprint")
    _secret_everywhere(feature)
    planned = publish.publish_feature("demo", root=feature["root"], dry_run=True)
    real = publish.publish_feature("demo", root=feature["root"])
    for outcome in (planned, real):
        assert (outcome["status"], outcome["reason"]) == ("skipped", "no publishable .md files")
        assert AWS_KEY not in json.dumps(outcome)
    assert planned["result"]["skipped"] == real["result"]["skipped"]
    assert remote.posts == []


def test_symlinked_feature_directory_is_refused(feature, remote, tmp_path):
    """SECURITY L-3: the feature directory itself must stay inside the project."""
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "PRD.md").write_text("OUTSIDE_SENTINEL\n", encoding="utf-8")
    (feature["dir"].parent / "linked").symlink_to(outside)
    result = confluence.sync_feature("PROJ", "Sprint", "linked", root=feature["root"])
    assert set(result) == {"error"} and "symlink" in result["error"]
    assert remote.posts == []


@pytest.mark.parametrize("name", ["features/../../../outside", "../outside", "features/demo/.."])
def test_dotdot_feature_name_is_refused(feature, remote, name):
    (feature["outside"] / "outside").mkdir(exist_ok=True)
    result = confluence.sync_feature("PROJ", "Sprint", name, root=feature["root"])
    assert set(result) == {"error"} and "Invalid feature name" in result["error"]
    assert remote.posts == []


def test_non_utf8_md_is_a_per_file_error(feature, remote):
    """R3-4: UnicodeDecodeError is reported per file like Notion, never raised."""
    (feature["dir"] / "BIN.md").write_bytes(b"\xff\xfe# \x00bin\x00")
    result = run(feature)
    by_file = {r["file"]: r for r in result["results"]}
    assert by_file["BIN.md"] == {"file": "BIN.md", "status": "error",
                                 "error": "UnicodeDecodeError: could not read document"}
    assert [by_file[f]["status"] for f in ("PRD.md", "TASK.md")] == ["created", "created"]


def test_non_utf8_prd_fails_the_overview_only(feature, remote):
    (feature["dir"] / "PRD.md").write_bytes("# PRD\n".encode("utf-16"))
    result = run(feature)
    assert result["overview"]["status"] == "error"
    by_file = {r["file"]: r["status"] for r in result["results"]}
    assert by_file == {"PRD.md": "error", "TASK.md": "created"}


_COMPRESSED_FLOW = ('<mxfile host="app.diagrams.net"><diagram id="p" name="Page-1">'
                    'jZJNb4MwDIZ/DcdKQNauvbbrtsOkHSrtXIEBawkhC1D7+8RDtlXaS+L4ee3X'
                    '</diagram></mxfile>')


@pytest.mark.parametrize("write, reason", [
    (lambda p: p.write_bytes(_FLOW.encode("utf-16")), "cannot scan for secrets: not UTF-8 text"),
    (lambda p: p.write_text(_COMPRESSED_FLOW, encoding="utf-8"), "cannot scan for secrets: compressed diagram"),
    (lambda p: p.write_text("<mxfile><diagram", encoding="utf-8"), "cannot scan for secrets: not draw.io XML"),
])
def test_unscannable_flow_is_not_attached(feature, remote, write, reason):
    """SECURITY L-4: an attachment the scan cannot read is skipped (fail-closed)."""
    write(feature["dir"] / "FLOW.drawio")
    result = run(feature)
    assert result["attachments"] == [{"file": "FLOW.drawio", "status": "skipped", "error": reason}]
    assert not any(c.get("files") for c in remote.posts)
    assert [r["status"] for r in result["results"]] == ["created", "created"]


def test_dry_run_reports_flow_attachment_plan_and_skip_reasons(feature, remote):
    """R3-2: the dry-run shows whether FLOW.drawio would be attached and why not."""
    projects.set_publish("demo-svc", "confluence", confluence_space_key="PROJ", confluence_parent_title="Sprint")
    (feature["dir"] / "FLOW.drawio").write_text(_FLOW, encoding="utf-8")
    plan = publish.publish_feature("demo", root=feature["root"], dry_run=True)["result"]
    assert plan["attachments"] == [{"file": "FLOW.drawio", "status": "planned"}]
    assert plan["skipped_reasons"] == {}

    (feature["dir"] / "FLOW.drawio").write_text(_FLOW.replace("처리 성공?", AWS_KEY, 1), encoding="utf-8")
    (feature["dir"] / "TASK.md").write_text(AWS_KEY, encoding="utf-8")
    plan = publish.publish_feature("demo", root=feature["root"], dry_run=True)["result"]
    skipped_flow = {"file": "FLOW.drawio", "status": "skipped", "error": "secret pattern detected: aws-access-key"}
    assert plan["attachments"] == [skipped_flow]
    assert plan["skipped"] == ["TASK.md"]
    assert plan["skipped_reasons"] == {"TASK.md": "secret pattern detected: aws-access-key"}
    assert remote.posts == []
    assert run(feature)["attachments"] == [skipped_flow]  # the real run agrees


def test_dry_run_without_flow_plans_no_attachment(feature, remote):
    projects.set_publish("demo-svc", "confluence", confluence_space_key="PROJ", confluence_parent_title="Sprint")
    assert publish.publish_feature("demo", root=feature["root"], dry_run=True)["result"]["attachments"] == []


def test_md_changed_after_listing_is_rechecked_before_sending(feature, remote, monkeypatch):
    """R3-2: the per-file scan right before sending catches a change after the listing scan."""
    listed = confluence.publishable_files

    def list_then_change(feature_dir):
        out = listed(feature_dir)
        (feature_dir / "TASK.md").write_text(f"# TASK\n{AWS_KEY}\n", encoding="utf-8")
        return out

    monkeypatch.setattr(confluence, "publishable_files", list_then_change)
    result = run(feature)
    task = next(r for r in result["results"] if r["file"] == "TASK.md")
    assert task == {"file": "TASK.md", "status": "skipped", "error": "secret pattern detected: aws-access-key"}
    assert AWS_KEY not in remote.sent() and "TASK" not in remote.titles()
