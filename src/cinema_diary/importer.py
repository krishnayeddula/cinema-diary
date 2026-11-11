"""TMDB -> PocketBase import worker.

Usage:
    uv run python -m cinema_diary.importer "Satyajit Ray" "David Fincher"
    uv run python -m cinema_diary.importer --person-id 12160

For each director: find them on TMDB, list the movies they directed, then
for each movie fetch details + credits (one TMDB call) and upsert into
PocketBase: movies, people, credits.

Rerun-safe: every record id is derived from a TMDB id, so a second run
updates the same rows instead of adding new ones.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from cinema_diary.pb_client import PocketBaseClient, derived_id
from cinema_diary.tmdb_client import TMDBClient

log = logging.getLogger("cinema_diary.importer")

# Cast: the top-billed actors are enough for taste signals.
MAX_CAST = 20

# Crew: the jobs that shape taste (incl. music), not the whole unit list.
KEY_CREW_JOBS = frozenset(
    {
        "Director",
        "Screenplay",
        "Writer",
        "Story",
        "Dialogue",
        "Original Music Composer",
        "Music",
        "Music Director",
        "Songs",
        "Lyricist",
        "Director of Photography",
        "Editor",
        "Producer",
    }
)


class RecordStore(Protocol):
    def upsert(self, collection: str, record_id: str, data: dict) -> dict: ...


# --- TMDB json -> PocketBase record (pure functions, easy to test) ----------


def now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.000Z")


def movie_record(m: dict, synced_at: str) -> dict:
    release = m.get("release_date") or ""
    return {
        "tmdb_id": m["id"],
        "title": m.get("title") or m.get("original_title") or "",
        "original_title": m.get("original_title") or "",
        "original_language": m.get("original_language") or "",
        "release_date": release,
        "year": int(release[:4]) if release[:4].isdigit() else 0,
        "runtime": m.get("runtime") or 0,
        "genres": [g["name"] for g in m.get("genres", [])],
        "overview": m.get("overview") or "",
        "poster_path": m.get("poster_path") or "",
        "tmdb_synced_at": synced_at,
    }


def person_record(p: dict, synced_at: str) -> dict:
    return {
        "tmdb_id": p["id"],
        "name": p.get("name") or "",
        "known_for_department": p.get("known_for_department") or "",
        "profile_path": p.get("profile_path") or "",
        "tmdb_synced_at": synced_at,
    }


def credit_record(c: dict, kind: str, movie_rid: str, person_rid: str) -> dict:
    return {
        "tmdb_credit_id": c["credit_id"],
        "movie": movie_rid,
        "person": person_rid,
        "kind": kind,
        "character": c.get("character") or "",
        "job": c.get("job") or "",
        "department": c.get("department") or "",
        "order": c.get("order") or 0,
    }


def select_credits(credits: dict) -> list[tuple[str, dict]]:
    """Top-billed cast plus key crew, as (kind, credit) pairs."""
    cast = sorted(credits.get("cast", []), key=lambda c: c.get("order", 999))
    chosen = [("cast", c) for c in cast[:MAX_CAST]]
    chosen += [
        ("crew", c) for c in credits.get("crew", []) if c.get("job") in KEY_CREW_JOBS
    ]
    return chosen


# --- the worker -------------------------------------------------------------


@dataclass
class Stats:
    movies: int = 0
    people: int = 0
    credits: int = 0


class Importer:
    def __init__(self, tmdb: TMDBClient, pb: RecordStore) -> None:
        self.tmdb = tmdb
        self.pb = pb
        self.stats = Stats()
        self._people_done: set[int] = set()

    def resolve_person(self, name: str) -> dict:
        hits = self.tmdb.search_person(name)
        if not hits:
            raise LookupError(f"No TMDB person found for {name!r}")
        top = hits[0]
        log.info(
            "%r -> TMDB %s %s (%s)",
            name,
            top["id"],
            top["name"],
            top.get("known_for_department"),
        )
        return top

    def directed_movie_ids(self, person_id: int) -> list[int]:
        crew = self.tmdb.person_movie_credits(person_id).get("crew", [])
        return sorted({c["id"] for c in crew if c.get("job") == "Director"})

    def import_director(self, person_id: int) -> None:
        movie_ids = self.directed_movie_ids(person_id)
        log.info("person %s: %d directed movies", person_id, len(movie_ids))
        for i, movie_id in enumerate(movie_ids, 1):
            self.import_movie(movie_id)
            log.info("  [%d/%d] movie %s done", i, len(movie_ids), movie_id)

    def import_movie(self, movie_id: int) -> None:
        synced = now_utc()
        m = self.tmdb.movie(movie_id)
        movie_rid = derived_id("movie", m["id"])
        self.pb.upsert("movies", movie_rid, movie_record(m, synced))
        self.stats.movies += 1

        for kind, c in select_credits(m.get("credits", {})):
            person_rid = derived_id("person", c["id"])
            if c["id"] not in self._people_done:
                self.pb.upsert("people", person_rid, person_record(c, synced))
                self._people_done.add(c["id"])
                self.stats.people += 1
            self.pb.upsert(
                "credits",
                derived_id("credit", c["credit_id"]),
                credit_record(c, kind, movie_rid, person_rid),
            )
            self.stats.credits += 1


# --- CLI --------------------------------------------------------------------


def _require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        sys.exit(f"{name} is not set. Run: set -a; source .env; set +a")
    return value


def _count(pb: PocketBaseClient, collection: str) -> int:
    return pb.list_page(collection, per_page=1)["totalItems"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import directors' films from TMDB.")
    parser.add_argument("names", nargs="*", help="director names, e.g. 'Satyajit Ray'")
    parser.add_argument(
        "--person-id", type=int, action="append", default=[], help="TMDB person id"
    )
    args = parser.parse_args(argv)
    if not args.names and not args.person_id:
        parser.error("give at least one name or --person-id")

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    with (
        TMDBClient.from_env() as tmdb,
        PocketBaseClient(_require_env("PB_URL")) as pb,
    ):
        pb.auth_with_password(
            "service_accounts",
            _require_env("PB_SA_EMAIL"),
            _require_env("PB_SA_PASSWORD"),
        )
        importer = Importer(tmdb, pb)

        person_ids = list(args.person_id)
        person_ids += [importer.resolve_person(n)["id"] for n in args.names]
        for pid in person_ids:
            importer.import_director(pid)

        s = importer.stats
        log.info(
            "\nUpserted this run: %d movies, %d people, %d credits",
            s.movies,
            s.people,
            s.credits,
        )
        log.info(
            "Now in PocketBase:  %d movies, %d people, %d credits",
            _count(pb, "movies"),
            _count(pb, "people"),
            _count(pb, "credits"),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
