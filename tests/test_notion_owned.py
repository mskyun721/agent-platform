"""Owned SPEC/INDEX page upsert on Notion (BR-7, AC-7, AC-12) against the in-memory fake API."""

from __future__ import annotations

import re

import httpx
import pytest

from agent_platform_mcp.tools import notion
from test_notion import PARENT, PARENT_ID, TOKEN, FakeNotion, _add_page

OWNER = {"project_id": "demo-svc", "slug": "payment"}
TITLE = "Payment"
CONFLICT = {"error": "page 'Payment' exists and is not owned by agent-platform", "code": "title_conflict",
            "title": TITLE}


class OwnedFakeNotion(FakeNotion):
    """FakeNotion plus the fields the owned upsert reads (page parent, paragraph text, in_trash),
    the title PATCH, and lookups by the compact ids the client normalises mapped ids to."""

    def _dashed(self, match: re.Match) -> str:
        return self.key(match.group(0))

    def key(self, page_id: str) -> str:
        """Fake block key (dashed uuid) of a compact id the client returns."""
        return next((b for b in self.blocks if b.replace("-", "") == page_id.replace("-", "")), page_id)

    def __call__(self, method: str, url: str, **kwargs) -> httpx.Response:
        url = re.sub(r"(?<=/)[0-9a-f]{32}(?=/|$)", self._dashed, url)
        path = url.removeprefix(notion.API_BASE)
        match = re.fullmatch(r"/pages/([\w-]+)", path)
        if method == "PATCH" and match and match.group(1) in self.blocks:
            self.calls.append((method, path))
            self.blocks[match.group(1)]["title"] = kwargs["json"]["properties"]["title"]["title"][0]["text"]["content"]
            return httpx.Response(200, json={"id": match.group(1)})
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
                block = self.blocks.get(item["id"]) or {}
                if block.get("type") == "paragraph":
                    item["paragraph"] = block["payload"]
            return httpx.Response(200, json=data)
        return response

    def first_text(self, page_id: str) -> str:
        live = [c for c in self.blocks[self.key(page_id)]["children"] if not self.blocks[c]["archived"]]
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
    assert fake.blocks[fake.key(result["page_id"])]["parent"] == PARENT_ID


def test_mapped_owned_page_is_updated_in_place(fake):
    page_id = upsert()["page_id"]
    fake.calls.clear()
    result = upsert(known=page_id)
    assert result == {"action": "updated", "page_id": page_id, "url": f"https://notion.test/{fake.key(page_id)}"}
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
    assert upsert() == {**CONFLICT, "page_id": human}
    assert writes(fake) == []


def test_marker_after_a_kept_sub_page_is_still_recognised(fake):
    """M4a-1 (reviewer probe): created → human adds a sub-page → updated → updated again."""
    page_id = upsert()["page_id"]
    sub = _add_page(fake, fake.key(page_id), "Human notes")
    assert upsert(known=page_id)["action"] == "updated"
    live = [c for c in fake.blocks[fake.key(page_id)]["children"] if not fake.blocks[c]["archived"]]
    assert live[0] == sub  # the rewritten marker now follows the kept sub-page
    for known in (page_id, None):
        assert upsert(known=known) == {"action": "updated", "page_id": page_id,
                                       "url": f"https://notion.test/{fake.key(page_id)}"}
    assert fake.blocks[sub]["archived"] is False and len(fake.pages(TITLE)) == 1


def test_trashed_owned_page_never_redirects_the_write_to_a_human_page(fake):
    """M4a-2 / security M-1: no title-only fallback after ownership was decided."""
    human = _add_page(fake, PARENT_ID, TITLE)
    note = fake._new(human, {"type": "paragraph", "paragraph": {"rich_text": []}})
    owned = _add_page(fake, PARENT_ID, TITLE)
    fake.mark(owned, OWNER)
    fake.blocks[owned]["in_trash"] = True  # still listed under the parent, but trashed
    fake.calls.clear()
    assert upsert(known=owned) == {**CONFLICT, "page_id": human}
    assert writes(fake) == [] and fake.blocks[note]["archived"] is False


def test_owned_page_is_picked_among_same_title_pages(fake):
    _add_page(fake, PARENT_ID, TITLE)
    owned = _add_page(fake, PARENT_ID, TITLE)
    fake.mark(owned, OWNER)
    assert fake.key(upsert()["page_id"]) == owned


def test_update_also_sets_the_title(fake):
    page_id = upsert()["page_id"]
    result = notion.upsert_owned_page(PARENT, "Payment v2", "body", OWNER, known_page_id=page_id)
    assert result["action"] == "updated" and fake.blocks[fake.key(page_id)]["title"] == "Payment v2"


def test_mapped_page_lookup_error_is_returned_without_writes(fake):
    page_id = upsert()["page_id"]
    fake.force("GET", r"/pages/[\w-]+", httpx.Response(500, json={}), times=4)
    fake.calls.clear()
    assert upsert(known=page_id) == {"error": "Notion API error: HTTP 500", "http_status": 500}
    assert writes(fake) == []


def test_accept_owner_exception_is_an_error_without_writes(fake):
    page_id = _add_page(fake, PARENT_ID, TITLE)
    fake.mark(page_id, {"project_id": "old-id", "slug": "payment"})
    fake.calls.clear()
    assert upsert(accept_owner=lambda found: 1 / 0) == {"error": "accept_owner callback failed"}
    assert writes(fake) == []


def test_malformed_child_ids_from_the_api_are_skipped(fake):
    fake.force("GET", rf"/blocks/{PARENT_ID}/children", httpx.Response(200, json={
        "results": [{"id": "../../users", "type": "child_page", "child_page": {"title": TITLE}}],
        "has_more": False, "next_cursor": None}))
    assert upsert()["action"] == "created"
    assert not any("users" in p for m, p in fake.calls)


def test_mapping_to_another_parent_is_ignored(fake):
    other_parent = _add_page(fake, PARENT_ID, "Archive")
    moved = _add_page(fake, other_parent, TITLE)
    fake.mark(moved, OWNER)
    fake.calls.clear()
    result = upsert(known=moved)
    assert result["action"] == "created" and fake.key(result["page_id"]) != moved
    assert not any(moved in p for m, p in writes(fake))


def test_trashed_mapping_creates_a_new_page_and_never_restores(fake):
    page_id = fake.key(upsert()["page_id"])
    fake.blocks[page_id]["archived"] = True
    result = upsert(known=page_id)
    assert result["action"] == "created" and fake.key(result["page_id"]) != page_id
    assert fake.blocks[page_id]["archived"] is True


def test_foreign_marker_with_same_slug_needs_explicit_acceptance(fake):
    page_id = _add_page(fake, PARENT_ID, TITLE)
    fake.mark(page_id, {"project_id": "old-id", "slug": "payment"})
    assert upsert()["code"] == "title_conflict"
    result = upsert(accept_owner=lambda found: found["project_id"] == "old-id")
    assert result["action"] == "updated" and fake.key(result["page_id"]) == page_id
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
