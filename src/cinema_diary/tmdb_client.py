"""Read-only TMDB API client (v3 endpoints, v4 read token).

Design:
- Token goes in the "Authorization: Bearer" header, never in the URL.
- Client-side throttle: at most one request per min_interval seconds,
  so we stay well under TMDB's rate limit instead of bouncing off it.
- 429: wait for the Retry-After the server asks for, then retry.
- 5xx / network errors: retry with exponential backoff.
- Other 4xx (401 bad token, 404 unknown id): fail fast.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import Any, Self

import httpx

log = logging.getLogger(__name__)

TMDB_BASE_URL = "https://api.themoviedb.org/3"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class TMDBError(Exception):
    """A TMDB API call failed with an HTTP error status."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"TMDB {status}: {message}")
        self.status = status
        self.message = message


class TMDBClient:
    def __init__(
        self,
        token: str,
        *,
        base_url: str = TMDB_BASE_URL,
        timeout: float = 15.0,
        max_retries: int = 4,
        backoff: float = 1.0,
        min_interval: float = 0.1,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not token:
            raise ValueError("TMDB token is empty")
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        self._max_retries = max_retries
        self._backoff = backoff
        self._min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None

    @classmethod
    def from_env(cls, **kwargs: Any) -> Self:
        """Build a client from TMDB_READ_TOKEN in the environment."""
        token = os.environ.get("TMDB_READ_TOKEN", "")
        if not token:
            raise RuntimeError(
                "TMDB_READ_TOKEN is not set. Run: set -a; source .env; set +a"
            )
        return cls(token, **kwargs)

    # --- lifecycle -------------------------------------------------------

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- endpoints -------------------------------------------------------

    def search_person(self, name: str) -> list[dict]:
        """People matching a name, most popular first (TMDB's order)."""
        data = self._get("/search/person", params={"query": name})
        return data["results"]

    def person(self, person_id: int) -> dict:
        return self._get(f"/person/{person_id}")

    def person_movie_credits(self, person_id: int) -> dict:
        """{"cast": [...], "crew": [...]} for every movie this person worked on."""
        return self._get(f"/person/{person_id}/movie_credits")

    def movie(self, movie_id: int) -> dict:
        """Movie details with full cast and crew, in one request."""
        return self._get(f"/movie/{movie_id}", params={"append_to_response": "credits"})

    # --- transport -------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        for attempt in range(self._max_retries + 1):
            last_try = attempt == self._max_retries
            self._throttle()
            try:
                resp = self._http.get(path, params=params)
            except httpx.TransportError as exc:
                if last_try:
                    raise
                log.warning("GET %s: %s (retry %d)", path, exc, attempt + 1)
                self._sleep(self._backoff * (2**attempt))
                continue

            if resp.status_code in RETRY_STATUSES and not last_try:
                wait = self._retry_after(resp) or self._backoff * (2**attempt)
                log.warning(
                    "GET %s: HTTP %d, waiting %.1fs (retry %d)",
                    path,
                    resp.status_code,
                    wait,
                    attempt + 1,
                )
                self._sleep(wait)
                continue

            if resp.is_error:
                try:
                    message = resp.json().get("status_message", resp.reason_phrase)
                except ValueError:
                    message = resp.reason_phrase
                raise TMDBError(resp.status_code, message)

            return resp.json()

        raise AssertionError("unreachable")  # pragma: no cover

    def _throttle(self) -> None:
        now = self._clock()
        if self._last_request is not None:
            gap = self._min_interval - (now - self._last_request)
            if gap > 0:
                self._sleep(gap)
                now += gap
        self._last_request = now

    @staticmethod
    def _retry_after(resp: httpx.Response) -> float | None:
        value = resp.headers.get("Retry-After")
        try:
            return float(value) if value else None
        except ValueError:
            return None
