"""Owned SPEC/INDEX page upsert on Confluence (BR-7, AC-7, AC-12) against an in-memory fake.

httpx.get/post/put are replaced; no test reaches the network.
"""

from __future__ import annotations

import re

import httpx
import pytest

from agent_platform_mcp.tools import confluence
from agent_platform_mcp.tools import spec_publish_map as pmap
from agent_platform_mcp.tools.spec_publish_map import OWNER_LABEL, OWNER_PROPERTY

BASE = "https://example.atlassian.net"
SPACE_KEY = "PROJ"
SPACE_ID = "~sp1"
PARENT_TITLE = "Specs"
PARENT_ID = "100"
OWNER = {"project_id": "demo-svc", "slug": "payment"}
TITLE = "Payment"
CONFLICT = {"error": "page 'Payment' exists and is not owned by agent-platform", "code": "title_conflict",
            "title": TITLE}


class FakeConfluence:
    """Routes httpx.get/post/put for the endpoints confluence.py uses; records every call.
    Like Confluence, a title is unique in the space: a POST reusing one (even a trashed page's)
    is a 400 (M4a-3)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.pages: dict[str, dict] = {}
        self.forced: list[tuple[str, str, httpx.Response]] = []
        self.page_size = 2
        self._next_id = 1000
        self.add(PARENT_TITLE, parent=None, page_id=PARENT_ID)

    def add(self, title: str, parent: str | None = PARENT_ID, *, owner: dict | None = None,
            status: str = "current", page_id: str | None = None, version: int = 1) -> str:
        if page_id is None:
            self._next_id += 1
            page_id = str(self._next_id)
        properties = {}
        if owner is not None:
            self._next_id += 1
            properties[OWNER_PROPERTY] = {"id": str(self._next_id), "key": OWNER_PROPERTY,
                                          "value": dict(owner), "version": {"number": 1}}
        self.pages[page_id] = {"title": title, "parentId": parent, "status": status, "version": version,
                               "properties": properties, "labels": set(), "body": ""}
        return page_id

    def force(self, method: str, pattern: str, response: httpx.Response, times: int = 1) -> None:
        self.forced += [(method, pattern, response)] * times

    def count(self, method: str, pattern: str) -> int:
        return sum(1 for m, p, _ in self.calls if m == method and re.fullmatch(pattern, p))

    def _page_json(self, page_id: str) -> dict:
        page = self.pages[page_id]
        return {"id": page_id, "title": page["title"], "parentId": page["parentId"], "status": page["status"],
                "spaceId": SPACE_ID, "version": {"number": page["version"]}}

    def handle(self, method: str, url: str, **kwargs) -> httpx.Response:
        assert url.startswith(BASE)
        assert kwargs["timeout"] == 30
        assert kwargs["headers"]["Authorization"].startswith("Basic ")
        path = url.removeprefix(BASE)
        params = kwargs.get("params") or {}
        body = kwargs.get("json")
        self.calls.append((method, path, {"params": params, "json": body}))
        for index, (m, pattern, response) in enumerate(self.forced):
            if m == method and re.fullmatch(pattern, path):
                del self.forced[index]
                return response

        if method == "GET" and path == "/wiki/api/v2/spaces":
            return httpx.Response(200, json={"results": [{"id": SPACE_ID, "key": params["keys"]}]})
        if method == "GET" and path == "/wiki/api/v2/pages":  # space-wide title search
            hits = [{"id": i, "title": p["title"]} for i, p in self.pages.items()
                    if p["title"] == params["title"] and p["status"] == "current"]
            return httpx.Response(200, json={"results": hits[:1]})
        if method == "POST" and path == "/wiki/api/v2/pages":
            assert body["status"] == "current" and body["spaceId"] == SPACE_ID
            if any(p["title"] == body["title"] for p in self.pages.values()):
                return httpx.Response(400, json={"errors": [{"title": "A page with this title already exists"}]})
            page_id = self.add(body["title"], body["parentId"])
            self.pages[page_id]["body"] = body["body"]["value"]
            return httpx.Response(200, json={"id": page_id, "title": body["title"]})
        match = re.fullmatch(r"/wiki/api/v2/pages/(\d+)", path)
        if match:
            page_id = match.group(1)
            if page_id not in self.pages:
                return httpx.Response(404, json={})
            if method == "GET":
                return httpx.Response(200, json=self._page_json(page_id))
            if method == "PUT":
                page = self.pages[page_id]
                if body["version"]["number"] != page["version"] + 1:
                    return httpx.Response(409, json={})
                page.update(version=body["version"]["number"], title=body["title"], status=body["status"],
                            body=body["body"]["value"])
                return httpx.Response(200, json=self._page_json(page_id))
        match = re.fullmatch(r"/wiki/api/v2/pages/(\d+)/children", path)
        if method == "GET" and match:
            live = [i for i, p in self.pages.items() if p["parentId"] == match.group(1) and p["status"] == "current"]
            start = int(params.get("cursor") or 0)
            window = live[start:start + self.page_size]
            data: dict = {"results": [{"id": i, "title": self.pages[i]["title"], "status": "current"} for i in window],
                          "_links": {}}
            if start + self.page_size < len(live):
                data["_links"]["next"] = f"/wiki/api/v2/pages/{match.group(1)}/children?cursor={start + self.page_size}&limit=250"
            return httpx.Response(200, json=data)
        match = re.fullmatch(r"/wiki/api/v2/pages/(\d+)/properties(?:/(\d+))?", path)
        if match:
            props = self.pages[match.group(1)]["properties"]
            if method == "GET":
                return httpx.Response(200, json={"results": [p for k, p in props.items() if k == params.get("key")]})
            if method == "POST":
                self._next_id += 1
                props[body["key"]] = {"id": str(self._next_id), "key": body["key"], "value": body["value"],
                                      "version": {"number": 1}}
                return httpx.Response(200, json=props[body["key"]])
            if method == "PUT":
                current = props[body["key"]]
                assert current["id"] == match.group(2)
                assert body["version"]["number"] == current["version"]["number"] + 1
                current.update(value=body["value"], version=body["version"])
                return httpx.Response(200, json=current)
        match = re.fullmatch(r"/wiki/rest/api/content/(\d+)/label", path)
        if method == "POST" and match:
            self.pages[match.group(1)]["labels"].update(item["name"] for item in body)
            return httpx.Response(200, json={"results": body})
        raise AssertionError(f"unexpected call {method} {path}")


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_URL", BASE)
    monkeypatch.setenv("CONFLUENCE_EMAIL", "user@example.com")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "fake-token-SECRET")
    api = FakeConfluence()
    for method in ("get", "post", "put"):
        monkeypatch.setattr(confluence.httpx, method,
                            lambda url, _m=method.upper(), **kw: api.handle(_m, url, **kw))
    return api


def upsert(known=None, owner=OWNER, title=TITLE, **kwargs):
    return confluence.upsert_owned_page(SPACE_KEY, PARENT_TITLE, title, "# Payment\n\nbody", owner,
                                        known_page_id=known, **kwargs)


def spec_title_searched(fake) -> bool:
    return any(p == "/wiki/api/v2/pages" and c["params"].get("title") != PARENT_TITLE
               for m, p, c in fake.calls if m == "GET")


# --- created / updated ---------------------------------------------------------

def test_first_publish_creates_a_marked_page_under_the_parent(fake):
    result = upsert()
    assert result["action"] == "created" and "warning" not in result
    page = fake.pages[result["page_id"]]
    assert page["parentId"] == PARENT_ID and page["title"] == TITLE
    assert page["properties"][OWNER_PROPERTY]["value"] == OWNER
    assert page["labels"] == {OWNER_LABEL}
    assert "agent-platform" not in page["body"]  # the marker is never visible body text
    assert fake.count("PUT", r"/wiki/api/v2/pages/\d+") == 0
    assert not spec_title_searched(fake)


def test_mapped_owned_page_is_updated_with_version_plus_one(fake):
    page_id = fake.add(TITLE, owner=OWNER, version=4)
    result = upsert(known=page_id, title="Payment v2")
    assert result["action"] == "updated" and result["page_id"] == page_id and result["version"] == 5
    assert fake.pages[page_id]["version"] == 5 and fake.pages[page_id]["title"] == "Payment v2"
    assert fake.count("GET", r"/wiki/api/v2/pages/\d+/children") == 0  # mapping was enough
    assert fake.count("POST", r"/wiki/api/v2/pages") == 0


def test_without_mapping_the_owned_child_is_found_across_cursor_pages(fake):
    for name in ("A", "B", "C"):
        fake.add(name)
    page_id = fake.add(TITLE, owner=OWNER)
    result = upsert()
    assert result["action"] == "updated" and result["page_id"] == page_id
    assert fake.count("GET", r"/wiki/api/v2/pages/100/children") == 2
    cursors = [c["params"].get("cursor") for m, p, c in fake.calls if p.endswith("/children")]
    assert cursors == [None, "2"]
    assert not spec_title_searched(fake)


def test_cursor_is_taken_from_the_next_link_only(fake):
    fake.force("GET", r"/wiki/api/v2/pages/100/children", httpx.Response(200, json={
        "results": [], "_links": {"next": "https://evil.example/x?cursor=2&limit=250"}}))
    for name in ("A", "B", "C"):
        fake.add(name)
    assert upsert()["action"] == "created"  # the fake asserts every request stays on BASE
    cursors = [c["params"].get("cursor") for m, p, c in fake.calls if p.endswith("/children")]
    assert cursors == [None, "2"]


def test_repeated_cursor_stops_with_an_error(fake):
    looping = httpx.Response(200, json={"results": [], "_links": {"next": "/wiki/api/v2/pages/100/children?cursor=x"}})
    fake.force("GET", r"/wiki/api/v2/pages/100/children", looping, times=3)
    assert upsert() == {"error": "Confluence child listing did not advance"}
    assert fake.count("POST", r"/wiki/api/v2/pages") == 0


# --- title_conflict / outside parent / parent mismatch ------------------------

def test_same_title_without_marker_is_title_conflict_and_untouched(fake):
    human = fake.add(TITLE)
    result = upsert()
    assert result == {**CONFLICT, "page_id": human}
    assert fake.pages[human]["version"] == 1
    assert fake.count("PUT", r".*") == 0 and fake.count("POST", r".*") == 0


def test_mapped_page_whose_marker_was_removed_is_title_conflict(fake):
    page_id = fake.add(TITLE)  # e.g. a human deleted the property
    assert upsert(known=page_id)["code"] == "title_conflict"
    assert fake.count("PUT", r".*") == 0


DUPLICATE = {"error": "Confluence rejected page creation: A page with this title already exists", "http_status": 400,
             "code": "duplicate_title"}


def test_same_title_outside_the_parent_is_never_searched_or_touched(fake):
    """R-2 (a): Confluence keeps titles unique per space, so the create is a safe 400."""
    elsewhere = fake.add(TITLE, parent="555", owner=OWNER)
    before = dict(fake.pages[elsewhere])
    assert upsert() == DUPLICATE
    assert fake.pages[elsewhere] == before and len(fake.pages) == 2
    assert fake.count("PUT", r".*") == 0
    assert not spec_title_searched(fake)


def test_mapping_to_another_parent_is_ignored(fake):
    moved = fake.add("Payment (moved)", parent="777", owner=OWNER)  # titles are unique per space
    result = upsert(known=moved)
    assert result["action"] == "created" and result["page_id"] != moved
    assert fake.pages[result["page_id"]]["parentId"] == PARENT_ID
    assert fake.count("PUT", rf"/wiki/api/v2/pages/{moved}") == 0


# --- trashed / missing mapping --------------------------------------------------

def test_trashed_mapping_is_never_restored_and_its_title_blocks_the_create(fake):
    """R-2 (a): the trashed page still holds the title, so the create is a 400 (qa checks real Confluence)."""
    trashed = fake.add(TITLE, owner=OWNER, status="trashed")
    assert upsert(known=trashed) == DUPLICATE
    assert fake.pages[trashed]["status"] == "trashed" and len(fake.pages) == 2
    assert fake.count("PUT", r".*") == 0


def test_trashed_mapping_with_a_renamed_spec_creates_a_new_page(fake):
    trashed = fake.add("Payment (old)", owner=OWNER, status="trashed")
    result = upsert(known=trashed)
    assert result["action"] == "created" and result["page_id"] != trashed
    assert fake.pages[trashed]["status"] == "trashed"


def test_missing_mapped_page_falls_back_to_search(fake):
    page_id = fake.add(TITLE, owner=OWNER)
    result = upsert(known="999999")
    assert result["action"] == "updated" and result["page_id"] == page_id


# --- 409 / 401 / structured errors ---------------------------------------------

def test_409_rereads_once_and_retries(fake):
    page_id = fake.add(TITLE, owner=OWNER, version=2)
    fake.force("PUT", rf"/wiki/api/v2/pages/{page_id}", httpx.Response(409, json={}))
    result = upsert(known=page_id)
    assert result["action"] == "updated" and result["version"] == 3
    assert fake.count("PUT", rf"/wiki/api/v2/pages/{page_id}") == 2


def test_second_409_is_a_structured_error_without_a_third_put(fake):
    page_id = fake.add(TITLE, owner=OWNER)
    fake.force("PUT", rf"/wiki/api/v2/pages/{page_id}", httpx.Response(409, json={}), times=2)
    result = upsert(known=page_id)
    assert result == {"error": f"Confluence version conflict on {TITLE}", "http_status": 409,
                      "code": "confluence_conflict"}
    assert fake.count("PUT", rf"/wiki/api/v2/pages/{page_id}") == 2


def test_401_is_structured_and_hides_the_token(fake):
    fake.force("GET", r"/wiki/api/v2/spaces", httpx.Response(401, json={"message": "fake-token-SECRET"}))
    result = upsert()
    assert result == {"error": confluence.AUTH_FAILED, "http_status": 401}
    assert "SECRET" not in str(result)


def test_401_on_the_mapped_page_stops_before_any_write(fake):
    page_id = fake.add(TITLE, owner=OWNER)
    fake.force("GET", rf"/wiki/api/v2/pages/{page_id}", httpx.Response(401, json={}))
    assert upsert(known=page_id) == {"error": confluence.AUTH_FAILED, "http_status": 401}
    assert fake.count("PUT", r".*") == 0 and fake.count("POST", r".*") == 0


def test_404_parent_children_is_structured(fake):
    fake.force("GET", r"/wiki/api/v2/pages/100/children", httpx.Response(404, json={}))
    assert upsert() == {"error": "Page 100 not found", "http_status": 404}


def test_create_rejection_carries_http_status(fake):
    fake.force("POST", r"/wiki/api/v2/pages", httpx.Response(400, json={"errors": [{"title": "duplicate title"}]}))
    assert upsert() == {"error": "Confluence rejected page creation: duplicate title", "http_status": 400,
                        "code": "duplicate_title"}


@pytest.mark.parametrize("message", [
    "A page with this title already exists", "A page already exists with the same TITLE in this space",
    "Title is not unique in this space", "Page title already in use", "Duplicate page title",
    "title conflict with an existing page",
])
def test_title_clash_wordings_get_duplicate_title(fake, message):
    """Review 4b L-3: several server phrasings, any case; the 400 stays a structured failure."""
    fake.force("POST", r"/wiki/api/v2/pages", httpx.Response(400, json={"errors": [{"title": message}]}))
    assert upsert() == {"error": f"Confluence rejected page creation: {message}", "http_status": 400,
                        "code": "duplicate_title"}
    assert fake.count("PUT", r".*") == 0


def test_other_create_rejection_has_no_duplicate_code(fake):
    """N4a-3: only a title clash gets `duplicate_title`; any other 400 stays code-less."""
    fake.force("POST", r"/wiki/api/v2/pages", httpx.Response(400, json={"errors": [{"title": "Invalid body"}]}))
    assert upsert() == {"error": "Confluence rejected page creation: Invalid body", "http_status": 400}


def test_without_known_id_the_map_entry_is_used_and_kept(fake):
    """The caller does not know the resolved parent id: the map entry is the mapping (N4a-4)."""
    page_id = upsert()["page_id"]
    fake.pages[page_id]["title"] = "Renamed by a human"  # no title search could find it now
    fake.calls.clear()
    result = upsert()
    assert result["action"] == "updated" and result["page_id"] == page_id
    assert fake.pages[page_id]["title"] == TITLE
    assert pmap.load_page_id("demo-svc", "payment", target="confluence", parent=PARENT_ID) == page_id


def test_marker_failure_after_create_is_an_error_naming_the_page(fake):
    fake.force("POST", r"/wiki/api/v2/pages/\d+/properties", httpx.Response(403, json={}))
    result = upsert()
    assert result["error"].startswith("ownership marker not saved") and result["http_status"] == 403
    assert result["page_id"] in fake.pages
    assert pmap.pending_marker_page("demo-svc", "payment", target="confluence", parent=PARENT_ID) == result["page_id"]


@pytest.mark.parametrize("pass_known", [True, False])
def test_page_left_unmarked_by_a_failed_marker_write_is_recovered(fake, pass_known):
    """L-4: the map records the create before the marker write; the next publish adopts it."""
    fake.force("POST", r"/wiki/api/v2/pages/\d+/properties", httpx.Response(500, json={}))
    page_id = upsert()["page_id"]
    result = upsert(known=page_id if pass_known else None)
    assert result["action"] == "updated" and result["page_id"] == page_id and "warning" not in result
    assert fake.pages[page_id]["properties"][OWNER_PROPERTY]["value"] == OWNER
    assert fake.count("POST", r"/wiki/api/v2/pages") == 1
    assert pmap.pending_marker_page("demo-svc", "payment", target="confluence", parent=PARENT_ID) is None
    assert pmap.load_page_id("demo-svc", "payment", target="confluence", parent=PARENT_ID) == page_id


def test_pending_page_is_not_adopted_after_a_rename(fake):
    fake.force("POST", r"/wiki/api/v2/pages/\d+/properties", httpx.Response(500, json={}))
    page_id = upsert()["page_id"]
    fake.pages[page_id]["title"] = "Renamed by a human"
    result = upsert(known=page_id)
    assert result["action"] == "created" and result["page_id"] != page_id
    assert fake.pages[page_id]["version"] == 1 and fake.pages[page_id]["properties"] == {}


def test_successful_create_leaves_no_pending_entry(fake):
    page_id = upsert()["page_id"]
    assert pmap.pending_marker_page("demo-svc", "payment", target="confluence", parent=PARENT_ID) is None
    assert pmap.load_page_id("demo-svc", "payment", target="confluence", parent=PARENT_ID) == page_id


def test_label_failure_is_only_a_warning(fake):
    fake.force("POST", r"/wiki/rest/api/content/\d+/label", httpx.Response(500, json={}))
    result = upsert()
    assert result["action"] == "created" and result["warning"] == "label not added: HTTP 500"


# --- validation / adoption ------------------------------------------------------

@pytest.mark.parametrize("bad", ["../1", "12/children", "abc", "0", "", " 12"])
def test_invalid_known_page_id_makes_no_call(fake, bad):
    assert upsert(known=bad) == {"error": "invalid page id"}
    assert fake.calls == []


@pytest.mark.parametrize("owner", [{}, {"project_id": "Bad ID", "slug": "x"}, {"project_id": "demo-svc", "slug": "a/b"}, None])
def test_invalid_owner_makes_no_call(fake, owner):
    assert "error" in upsert(owner=owner)
    assert fake.calls == []


def test_foreign_marker_with_same_slug_needs_explicit_acceptance(fake):
    page_id = fake.add(TITLE, owner={"project_id": "old-id", "slug": "payment"})
    assert upsert()["code"] == "title_conflict"
    result = upsert(accept_owner=lambda found: found["project_id"] == "old-id")
    assert result["action"] == "updated" and result["page_id"] == page_id
    assert fake.pages[page_id]["properties"][OWNER_PROPERTY]["value"] == OWNER


def test_accept_owner_is_not_asked_for_another_slug(fake):
    fake.add(TITLE, owner={"project_id": "demo-svc", "slug": "other"})
    asked = []
    assert upsert(accept_owner=lambda found: asked.append(found) or True)["code"] == "title_conflict"
    assert asked == []


def test_accept_owner_exception_is_an_error_without_writes(fake):
    fake.add(TITLE, owner={"project_id": "old-id", "slug": "payment"})
    assert upsert(accept_owner=lambda found: {}["boom"]) == {"error": "accept_owner callback failed"}
    assert fake.count("PUT", r".*") == 0 and fake.count("POST", r".*") == 0


# --- re-reads, filters and limits (L-3, L-8) -------------------------------------

def test_searched_target_trashed_before_the_write_is_not_restored(fake):
    page_id = fake.add(TITLE, owner=OWNER)
    fake.force("GET", rf"/wiki/api/v2/pages/{page_id}", httpx.Response(200, json={
        "id": page_id, "title": TITLE, "parentId": PARENT_ID, "status": "trashed", "version": {"number": 1}}))
    result = upsert()
    assert result["page_status"] == "trashed" and fake.count("PUT", r".*") == 0


def test_409_reread_showing_trashed_stops_without_a_second_put(fake):
    page_id = fake.add(TITLE, owner=OWNER)
    page = rf"/wiki/api/v2/pages/{page_id}"
    live = {"id": page_id, "title": TITLE, "parentId": PARENT_ID, "status": "current", "version": {"number": 1}}
    fake.force("GET", page, httpx.Response(200, json=live))  # mapped-path read
    fake.force("GET", page, httpx.Response(200, json={**live, "status": "trashed"}))  # 409 re-read
    fake.force("PUT", page, httpx.Response(409, json={}))
    result = upsert(known=page_id)
    assert result["page_status"] == "trashed"
    assert fake.count("PUT", page) == 1


def test_409_reread_rechecks_the_marker(fake):
    page_id = fake.add(TITLE, owner=OWNER, version=2)
    props = rf"/wiki/api/v2/pages/{page_id}/properties"
    marker = {"id": "9", "key": OWNER_PROPERTY, "value": OWNER, "version": {"number": 1}}
    fake.force("GET", props, httpx.Response(200, json={"results": [marker]}))  # mapped-path check
    fake.force("GET", props, httpx.Response(200, json={"results": []}))  # after the 409: marker removed
    fake.force("PUT", rf"/wiki/api/v2/pages/{page_id}", httpx.Response(409, json={}))
    assert upsert(known=page_id) == {**CONFLICT, "page_id": page_id}
    assert fake.count("PUT", rf"/wiki/api/v2/pages/{page_id}") == 1


def test_children_that_are_not_current_are_ignored(fake):
    fake.force("GET", r"/wiki/api/v2/pages/100/children", httpx.Response(200, json={
        "results": [{"id": "5000", "title": TITLE, "status": "trashed"}], "_links": {}}))
    assert upsert()["action"] == "created"


def test_marker_rewrite_failure_after_adoption_is_a_warning(fake):
    page_id = fake.add(TITLE, owner={"project_id": "old-id", "slug": "payment"})
    fake.force("PUT", rf"/wiki/api/v2/pages/{page_id}/properties/\d+", httpx.Response(500, json={}))
    result = upsert(accept_owner=lambda found: True)
    assert result["action"] == "updated"
    assert result["warning"] == "ownership marker not updated: Confluence API error: HTTP 500"


def test_marker_with_extra_keys_matches_and_is_rewritten_exactly(fake):
    page_id = fake.add(TITLE, owner={**OWNER, "note": "extra"})
    assert upsert()["action"] == "updated"
    assert fake.pages[page_id]["properties"][OWNER_PROPERTY]["value"] == OWNER


def test_child_listing_stops_at_the_request_cap(fake, monkeypatch):
    monkeypatch.setattr(confluence, "MAX_CHILD_REQUESTS", 2)
    for name in ("A", "B", "C", "D", "E"):
        fake.add(name)
    assert upsert() == {"error": "Confluence parent has more than 500 child pages"}
    assert fake.count("GET", r"/wiki/api/v2/pages/100/children") == 2


def test_invalid_ids_in_api_responses_are_refused(fake):
    fake.force("GET", r"/wiki/api/v2/pages", httpx.Response(200, json={"results": [{"id": "1/../2"}]}))
    assert upsert() == {"error": confluence.INVALID_PAGE_ID}
    fake.force("POST", r"/wiki/api/v2/pages", httpx.Response(200, json={"id": "../x"}))
    assert upsert() == {"error": confluence.INVALID_PAGE_ID}
    assert fake.count("POST", r"/wiki/api/v2/pages/.*") == 0


@pytest.mark.parametrize("exc, message", [(httpx.InvalidURL("bad"), "Confluence request failed"),
                                           (httpx.ConnectError("down"), "Confluence request failed"),
                                           (httpx.ReadTimeout("slow"), confluence.TIMED_OUT)])
def test_send_turns_transport_errors_into_results(fake, monkeypatch, exc, message):
    def boom(url, **kwargs):
        raise exc
    monkeypatch.setattr(confluence.httpx, "get", boom)
    assert confluence.update_page("123", "x") == {"error": message}


# --- update_page structuring (M-5) ----------------------------------------------

def test_update_page_refuses_a_trashed_page(fake):
    page_id = fake.add("Old", status="trashed")
    result = confluence.update_page(page_id, "x")
    assert result["page_status"] == "trashed" and "not restored" in result["error"]
    assert fake.count("PUT", r".*") == 0


def test_update_page_validates_the_id_and_structures_404(fake):
    assert confluence.update_page("1/../2", "x") == {"error": "invalid page id"}
    assert confluence.update_page("424242", "x") == {"error": "Page 424242 not found", "http_status": 404}


def test_update_page_retries_409_once(fake):
    page_id = fake.add("Doc", version=7)
    fake.force("PUT", rf"/wiki/api/v2/pages/{page_id}", httpx.Response(409, json={}))
    assert confluence.update_page(page_id, "x")["version"] == 8


def test_update_page_refuses_an_archived_page(fake):
    page_id = fake.add("Old", status="archived")
    assert confluence.update_page(page_id, "x")["page_status"] == "archived"
    assert fake.count("PUT", r".*") == 0


def test_update_page_retry_keeps_the_title_read_again(fake):
    page_id = fake.add("Doc", version=1)
    fake.force("PUT", rf"/wiki/api/v2/pages/{page_id}", httpx.Response(409, json={}))
    fake.pages[page_id].update(title="Renamed meanwhile", version=2)  # visible to the re-read only
    fake.force("GET", rf"/wiki/api/v2/pages/{page_id}", httpx.Response(200, json={
        "id": page_id, "title": "Doc", "status": "current", "version": {"number": 1}}))
    result = confluence.update_page(page_id, "x")
    assert result["title"] == "Renamed meanwhile" and fake.pages[page_id]["title"] == "Renamed meanwhile"


def test_update_page_second_409_uses_the_prd_message(fake):
    page_id = fake.add("Doc")
    fake.force("PUT", rf"/wiki/api/v2/pages/{page_id}", httpx.Response(409, json={}), times=2)
    assert confluence.update_page(page_id, "x") == {"error": "Confluence version conflict on Doc",
                                                    "http_status": 409, "code": "confluence_conflict"}


def test_next_cursor_reads_only_the_query():
    data = {"_links": {"next": "/wiki/api/v2/pages/1/children?cursor=abc%3D&limit=250"}}
    assert confluence._next_cursor(data) == "abc="
    assert confluence._next_cursor({"_links": {}}) is None
    assert confluence._next_cursor({"_links": {"next": "/x?limit=1"}}) is None
