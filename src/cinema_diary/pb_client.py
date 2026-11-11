"""Small PocketBase REST client for Cinema Diary's Python side.

Used by the TMDB import worker now, and later by the MCP server and agents.

Design:
- Auth token goes in the Authorization header, never in the URL.
- Retry with exponential backoff on network errors and 429/5xx (temporary).
- Fail fast on other 4xx (bad request / denied: retrying will not help).
- list_all() walks every page for you.
- upsert() with a derived id makes imports rerun-safe (idempotent).
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable, Iterator
from typing import Any, Self

import httpx

log = logging.getLogger(__name__)

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class PocketBaseError(Exception):
    """A PocketBase API call failed with an HTTP error status."""

    def __init__(self, status: int, message: str, data: Any = None) -> None:
        super().__init__(f"PocketBase {status}: {message}")
        self.status = status
        self.message = message
        self.data = data


def derived_id(*parts: str | int) -> str:
    """Deterministic 15-char PocketBase record id from stable parts.

    derived_id("movie", 550) always returns the same id, so re-running an
    import updates the same record instead of creating a duplicate.
    sha256 hex is [0-9a-f], which fits PocketBase's id format ^[a-z0-9]{15}$.
    """
    key = ":".join(str(p) for p in parts)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:15]


class PocketBaseClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 10.0,
        max_retries: int = 4,
        backoff: float = 0.5,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout, transport=transport
        )
        self._token: str | None = None
        self._max_retries = max_retries
        self._backoff = backoff
        self._sleep = sleep

    # --- lifecycle -------------------------------------------------------

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- auth ------------------------------------------------------------

    def auth_with_password(self, collection: str, identity: str, password: str) -> None:
        """Log in as a record of an auth collection (e.g. service_accounts)."""
        data = self._request(
            "POST",
            f"/api/collections/{collection}/auth-with-password",
            json={"identity": identity, "password": password},
        )
        self._token = data["token"]

    @property
    def is_authenticated(self) -> bool:
        return self._token is not None

    # --- records ---------------------------------------------------------

    def get(self, collection: str, record_id: str) -> dict | None:
        """Return the record, or None if it does not exist (or is not visible)."""
        try:
            return self._request(
                "GET", f"/api/collections/{collection}/records/{record_id}"
            )
        except PocketBaseError as exc:
            if exc.status == 404:
                return None
            raise

    def list_page(
        self,
        collection: str,
        *,
        page: int = 1,
        per_page: int = 200,
        filter: str | None = None,
        sort: str | None = None,
    ) -> dict:
        params: dict[str, Any] = {"page": page, "perPage": per_page}
        if filter:
            params["filter"] = filter
        if sort:
            params["sort"] = sort
        return self._request(
            "GET", f"/api/collections/{collection}/records", params=params
        )

    def list_all(
        self,
        collection: str,
        *,
        filter: str | None = None,
        sort: str | None = None,
        per_page: int = 200,
    ) -> Iterator[dict]:
        """Yield every matching record, walking all pages."""
        page = 1
        while True:
            data = self.list_page(
                collection, page=page, per_page=per_page, filter=filter, sort=sort
            )
            yield from data["items"]
            if page >= data["totalPages"]:
                return
            page += 1

    def create(self, collection: str, data: dict) -> dict:
        return self._request(
            "POST", f"/api/collections/{collection}/records", json=data
        )

    def update(self, collection: str, record_id: str, data: dict) -> dict:
        return self._request(
            "PATCH", f"/api/collections/{collection}/records/{record_id}", json=data
        )

    def upsert(self, collection: str, record_id: str, data: dict) -> dict:
        """Update the record if it exists, otherwise create it with this id.

        Rerun-safe: with a derived id, running the same import twice
        converges to the same rows.
        """
        try:
            return self.update(collection, record_id, data)
        except PocketBaseError as exc:
            if exc.status != 404:
                raise
        return self.create(collection, {**data, "id": record_id})

    # --- transport -------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = dict(kwargs.pop("headers", None) or {})
        if self._token:
            headers["Authorization"] = self._token

        for attempt in range(self._max_retries + 1):
            last_try = attempt == self._max_retries
            try:
                resp = self._http.request(method, path, headers=headers, **kwargs)
            except httpx.TransportError as exc:
                if last_try:
                    raise
                log.warning("%s %s: %s (retry %d)", method, path, exc, attempt + 1)
                self._wait(attempt)
                continue

            if resp.status_code in RETRY_STATUSES and not last_try:
                log.warning(
                    "%s %s: HTTP %d (retry %d)",
                    method,
                    path,
                    resp.status_code,
                    attempt + 1,
                )
                self._wait(attempt)
                continue

            if resp.is_error:
                try:
                    body = resp.json()
                except ValueError:
                    body = {}
                raise PocketBaseError(
                    resp.status_code,
                    body.get("message", resp.reason_phrase),
                    body.get("data"),
                )

            return resp.json() if resp.content else None

        raise AssertionError("unreachable")  # pragma: no cover

    def _wait(self, attempt: int) -> None:
        self._sleep(self._backoff * (2**attempt))
