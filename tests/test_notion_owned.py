"""Owned SPEC/INDEX page upsert on Notion (BR-7, AC-7, AC-12) against the in-memory fake API."""

from __future__ import annotations

import re

import httpx
import pytest

from agent_platform_mcp.tools import notion
from test_notion import PARENT, PARENT_ID, TOKEN, FakeNotion, _add_page

OWNER = {"project_id": "demo-svc", "slug": "payment"}
TITLE = "Payment"


class OwnedFakeNotion(FakeNotion):
    """FakeNotion plus the fields the owned upsert reads: page parent and paragraph text."""

    def __call__(self, method: str, url: str, **kwargs) -> httpx.Response:
        path = url.removeprefix(notion.API_BASE)
        response = super().__call__(method, url, **kwargs)
        match = re.fullmatch(r"/pages/([\w-]+)", path)
        if method == "GET" and match and response.status_code == 200:
            block = self.blocks[match.group(1)]
            return httpx.Response(200, json={**response.json(), "in_trash": block.get("in_trash", False),
                                             "parent": {"type": "page_id", "page_id": block.get("parent")}})
        match = re.fullmatch(r"/blocks/([\w-]+)/children", path)
        if method == "GET" and match and response.status_code == 200:
            data = response.json()
            for item in data["results"]:
                block = self.blocks[item["id"]]
                if block["type"] == "paragraph":
                    item["paragraph"] = block["payload"]
            return httpx.Response(200, json=data)
        return response

    def first_text(self, page_id: str) -> str:
        live = [c for c in self.blocks[page_id]["children"] if not self.blocks[c]["archived"]]
        rich = self.blocks[live[0]]["payload"]["rich_text"]
        return "".join(r["text"]["content"] for r in rich)

    def mark(self, page_id: str, owner: dict) -> None:
        self._new(page_id, notion.marker_block(owner))


@pytest.fixture
def fake(monkeypatch):
    api = OwnedFakeNotion()
    monkeypatch.setattr(notion.httpx, "request", api)
    monkeypatch.setattr(notion, "_sleep", lambda _: None)
    monkeypatch.setenv("NOTION_TOKEN", TOKEN)
    return api


def upsert(known=None, owner=OWNER, **kwargs):
    return notion.upsert_owned_page(PARENT, TITLE, "# Payment\n\nbody", owner, known_page_id=known, **kwargs)


def writes(fake) -> list[tuple[str, str]]:
    return [(m, p) for m, p in fake.calls if m in ("POST", "PATCH", "DELETE")]


def test_first_publish_creates_a_page_with_the_marker_first(fake):
    result = upsert()
    assert result["action"] == "created"
    assert fake.first_text(result["page_id"]) == "agent-platform:demo-svc/payment"
    assert fake.blocks[result["page_id"]]["parent"] == PARENT_ID


def test_mapped_owned_page_is_updated_in_place(fake):
    page_id = upsert()["page_id"]
    fake.calls.clear()
    result = upsert(known=page_id)
    assert result == {"action": "updated", "page_id": page_id, "url": f"https://notion.test/{page_id}"}
    assert len(fake.pages(TITLE)) == 1
    assert fake.first_text(page_id) == "agent-platform:demo-svc/payment"


def test_without_mapping_the_owned_child_is_found_by_title(fake):
    for name in ("A", "B", "C"):
        _add_page(fake, PARENT_ID, name)  # page_size 2 → the owned page is on a later cursor page
    page_id = upsert()["page_id"]
    assert upsert()["page_id"] == page_id
    assert len(fake.pages(TITLE)) == 1


def test_same_title_without_marker_is_title_conflict(fake):
    human = _add_page(fake, PARENT_ID, TITLE)
    fake.calls.clear()
    assert upsert() == {"error": "title_conflict", "title": TITLE, "page_id": human}
    assert writes(fake) == []


def test_mapping_to_another_parent_is_ignored(fake):
    other_parent = _add_page(fake, PARENT_ID, "Archive")
    moved = _add_page(fake, other_parent, TITLE)
    fake.mark(moved, OWNER)
    fake.calls.clear()
    result = upsert(known=moved)
    assert result["action"] == "created" and result["page_id"] != moved
    assert not any(moved in p for m, p in writes(fake))


def test_trashed_mapping_creates_a_new_page_and_never_restores(fake):
    page_id = upsert()["page_id"]
    fake.blocks[page_id]["archived"] = True
    result = upsert(known=page_id)
    assert result["action"] == "created" and result["page_id"] != page_id
    assert fake.blocks[page_id]["archived"] is True


def test_foreign_marker_with_same_slug_needs_explicit_acceptance(fake):
    page_id = _add_page(fake, PARENT_ID, TITLE)
    fake.mark(page_id, {"project_id": "old-id", "slug": "payment"})
    assert upsert()["error"] == "title_conflict"
    result = upsert(accept_owner=lambda found: found["project_id"] == "old-id")
    assert result["action"] == "updated" and result["page_id"] == page_id
    assert fake.first_text(page_id) == "agent-platform:demo-svc/payment"


def test_401_is_structured_and_hides_the_token(fake):
    fake.force("GET", r"/blocks/[\w-]+/children", httpx.Response(401, json={"message": TOKEN}))
    result = upsert()
    assert result == {"error": "Notion auth failed. Check NOTION_TOKEN", "http_status": 401}


@pytest.mark.parametrize("known", ["../x", "not-an-id"])
def test_invalid_ids_make_no_call(fake, known):
    assert upsert(known=known) == {"error": "invalid page id"}
    assert notion.upsert_owned_page("bad", TITLE, "x", OWNER) == {"error": "Invalid parent_page_id"}
    assert fake.calls == []


def test_missing_token_is_an_error_without_calls(fake, monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN")
    assert upsert() == {"error": "Missing env var: NOTION_TOKEN"}
    assert fake.calls == []
