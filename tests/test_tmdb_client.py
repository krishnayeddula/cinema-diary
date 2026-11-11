"""Unit tests for tmdb_client. httpx.MockTransport plays TMDB, so no token
or network is needed."""

import httpx
import pytest

from cinema_diary.tmdb_client import TMDBClient, TMDBError


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def make_client(handler, **kw):
    sleeps = []
    clock = FakeClock()
    client = TMDBClient(
        "test-token",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        clock=clock,
        min_interval=0.0,
        **kw,
    )
    return client, sleeps, clock


def test_bearer_token_in_header_never_in_url():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"results": []})

    client, _, _ = make_client(handler)
    client.search_person("Satyajit Ray")

    req = seen[0]
    assert req.headers["Authorization"] == "Bearer test-token"
    assert "test-token" not in str(req.url)
    assert req.url.params["query"] == "Satyajit Ray"


def test_movie_fetches_credits_in_same_request():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200, json={"id": 550, "credits": {"cast": [], "crew": []}}
        )

    client, _, _ = make_client(handler)
    data = client.movie(550)

    assert len(seen) == 1
    assert seen[0].url.path == "/3/movie/550"
    assert seen[0].url.params["append_to_response"] == "credits"
    assert "credits" in data


def test_429_waits_for_retry_after_then_succeeds():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        return httpx.Response(200, json={"id": 1})

    client, sleeps, _ = make_client(handler)
    assert client.person(1) == {"id": 1}
    assert sleeps == [3.0]  # honoured the server's Retry-After


def test_5xx_uses_exponential_backoff():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"id": 1})

    client, sleeps, _ = make_client(handler)
    client.person(1)
    assert sleeps == [1.0, 2.0]


def test_401_fails_fast():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, json={"status_message": "Invalid API key"})

    client, sleeps, _ = make_client(handler)
    with pytest.raises(TMDBError) as err:
        client.person(1)
    assert err.value.status == 401
    assert "Invalid API key" in str(err.value)
    assert len(calls) == 1
    assert sleeps == []


def test_throttle_spaces_out_requests():
    client, sleeps, clock = make_client(
        lambda r: httpx.Response(200, json={"id": 1}), max_retries=0
    )
    client._min_interval = 0.25

    client.person(1)  # first request: no wait
    clock.now += 0.05  # next call comes 50 ms later
    client.person(1)  # must wait the remaining 200 ms

    assert sleeps == [pytest.approx(0.20)]


def test_from_env_requires_token(monkeypatch):
    monkeypatch.delenv("TMDB_READ_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="TMDB_READ_TOKEN"):
        TMDBClient.from_env()


def test_empty_token_rejected():
    with pytest.raises(ValueError):
        TMDBClient("")
