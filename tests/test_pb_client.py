"""Unit tests for pb_client. No real PocketBase needed: httpx.MockTransport
plays the server, so these run in milliseconds and in CI."""

import json
import re

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from cinema_diary.pb_client import PocketBaseClient, PocketBaseError, derived_id

PB_ID = re.compile(r"^[a-z0-9]{15}$")


def make_client(handler, **kw):
    sleeps = []
    client = PocketBaseClient(
        "http://pb.test",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        **kw,
    )
    return client, sleeps


# --- derived_id --------------------------------------------------------------


def test_derived_id_is_stable():
    assert derived_id("movie", 550) == derived_id("movie", 550)


def test_derived_id_differs_by_input():
    assert derived_id("movie", 550) != derived_id("movie", 551)
    assert derived_id("movie", 550) != derived_id("person", 550)


@given(st.lists(st.one_of(st.text(), st.integers()), min_size=1))
def test_derived_id_always_valid_pocketbase_id(parts):
    assert PB_ID.match(derived_id(*parts))


# --- retries -----------------------------------------------------------------


def test_retries_on_503_then_succeeds():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"id": "abc"})

    client, sleeps = make_client(handler)
    assert client.get("movies", "abc") == {"id": "abc"}
    assert len(calls) == 3
    assert sleeps == [0.5, 1.0]  # exponential backoff


def test_retries_on_network_error():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json={"ok": True})

    client, _ = make_client(handler)
    assert client.get("movies", "abc") == {"ok": True}
    assert len(calls) == 2


def test_gives_up_after_max_retries():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500, json={"message": "boom"})

    client, _ = make_client(handler, max_retries=2)
    with pytest.raises(PocketBaseError) as err:
        client.create("movies", {"title": "x"})
    assert err.value.status == 500
    assert len(calls) == 3  # 1 try + 2 retries


def test_fails_fast_on_400():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            400, json={"message": "Failed to create record.", "data": {}}
        )

    client, sleeps = make_client(handler)
    with pytest.raises(PocketBaseError) as err:
        client.create("movies", {"title": "x"})
    assert err.value.status == 400
    assert len(calls) == 1
    assert sleeps == []


# --- auth --------------------------------------------------------------------


def test_token_sent_in_header_never_in_url():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("/auth-with-password"):
            return httpx.Response(200, json={"token": "secret-token"})
        return httpx.Response(200, json={"id": "abc"})

    client, _ = make_client(handler)
    client.auth_with_password("service_accounts", "importer@cinema.local", "pw")
    client.get("movies", "abc")

    last = seen[-1]
    assert last.headers["Authorization"] == "secret-token"
    assert "secret-token" not in str(last.url)


# --- reads -------------------------------------------------------------------


def test_get_returns_none_on_404():
    client, _ = make_client(
        lambda r: httpx.Response(404, json={"message": "not found"})
    )
    assert client.get("movies", "missing") is None


def test_list_all_walks_every_page():
    pages = {
        1: {"items": [{"id": "a"}, {"id": "b"}], "totalPages": 3},
        2: {"items": [{"id": "c"}], "totalPages": 3},
        3: {"items": [{"id": "d"}], "totalPages": 3},
    }

    def handler(request):
        page = int(request.url.params["page"])
        return httpx.Response(200, json=pages[page])

    client, _ = make_client(handler)
    assert [r["id"] for r in client.list_all("movies")] == ["a", "b", "c", "d"]


def test_list_all_empty_collection():
    client, _ = make_client(
        lambda r: httpx.Response(200, json={"items": [], "totalPages": 0})
    )
    assert list(client.list_all("movies")) == []


# --- upsert ------------------------------------------------------------------


def test_upsert_creates_with_given_id_when_missing():
    seen = []

    def handler(request):
        seen.append(request)
        if request.method == "PATCH":
            return httpx.Response(404, json={"message": "not found"})
        return httpx.Response(200, json=json.loads(request.content))

    client, _ = make_client(handler)
    rid = derived_id("movie", 550)
    result = client.upsert("movies", rid, {"tmdb_id": 550, "title": "Fight Club"})

    assert [r.method for r in seen] == ["PATCH", "POST"]
    assert result["id"] == rid


def test_upsert_updates_when_present():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"id": "x", "title": "updated"})

    client, _ = make_client(handler)
    client.upsert("movies", "x", {"title": "updated"})
    assert [r.method for r in seen] == ["PATCH"]  # no create on rerun
