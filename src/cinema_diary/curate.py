"""Rule-based curated list: films in the catalog that match a user's stated taste.

Usage (runs AS the user, so it only ever sees and writes that user's data):
    uv run python -m cinema_diary.curate              # build and save top 25
    uv run python -m cinema_diary.curate --dry-run    # print only, save nothing

Scoring (every point comes with a human-readable reason):
    +3  a favorite person worked on it in the role you love them for
    +2  in one of your languages
    +1  per matching genre (max 2)
    +1  from one of your eras
    +1  already on your watchlist
Films you have watched or reviewed are skipped. No AI here: the same input
always gives the same list. Ranking with a local model comes in P5.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field

from cinema_diary.importer import ROLE_JOBS
from cinema_diary.pb_client import PocketBaseClient

W_FAVORITE = 3
W_LANGUAGE = 2
W_GENRE = 1
MAX_GENRE_POINTS = 2
W_ERA = 1
W_WATCHLIST = 1
MIN_SCORE = 2
DEFAULT_TOP = 25

ROLE_VERB = {
    "director": "Directed by",
    "actor": "Starring",
    "composer": "Music by",
    "lyricist": "Lyrics by",
    "writer": "Written by",
    "cinematographer": "Shot by",
}
LANGUAGE_NAMES = {
    "te": "Telugu",
    "ta": "Tamil",
    "bn": "Bengali",
    "hi": "Hindi",
    "ml": "Malayalam",
    "kn": "Kannada",
    "mr": "Marathi",
    "en": "English",
    "fr": "French",
    "ja": "Japanese",
    "ko": "Korean",
}


@dataclass(frozen=True)
class Favorite:
    person_id: str
    role: str
    name: str


@dataclass
class Taste:
    languages: set[str] = field(default_factory=set)
    genres: set[str] = field(default_factory=set)
    eras: set[str] = field(default_factory=set)  # e.g. {"1980s"}


@dataclass
class Pick:
    movie_id: str
    title: str
    year: int
    score: int
    reasons: list[str]


# --- pure scoring (no I/O, easy to test) -------------------------------------


def era_of(year: int) -> str:
    return f"{year // 10 * 10}s" if year else ""


def credit_matches_role(credit: dict, role: str) -> bool:
    if role == "actor":
        return credit.get("kind") == "cast"
    return credit.get("kind") == "crew" and credit.get("job") in ROLE_JOBS.get(role, ())


def favorite_hits(
    credits: Iterable[dict], favorites: Iterable[Favorite]
) -> dict[str, list[str]]:
    """movie id -> reasons like 'Music by Ilaiyaraaja', from favorites' credits."""
    by_person: dict[str, list[Favorite]] = {}
    for fav in favorites:
        by_person.setdefault(fav.person_id, []).append(fav)

    hits: dict[str, list[str]] = {}
    for c in credits:
        for fav in by_person.get(c["person"], []):
            if credit_matches_role(c, fav.role):
                reason = f"{ROLE_VERB[fav.role]} {fav.name}"
                reasons = hits.setdefault(c["movie"], [])
                if reason not in reasons:
                    reasons.append(reason)
    return hits


def score_movies(
    movies: Iterable[dict],
    hits: dict[str, list[str]],
    taste: Taste,
    seen: set[str],
    watchlist: set[str],
    top: int = DEFAULT_TOP,
) -> list[Pick]:
    picks = []
    for m in movies:
        if m["id"] in seen:
            continue
        score, reasons = 0, []

        fav_reasons = hits.get(m["id"], [])
        score += W_FAVORITE * len(fav_reasons)
        reasons += fav_reasons

        lang = m.get("original_language", "")
        if lang in taste.languages:
            score += W_LANGUAGE
            reasons.append(LANGUAGE_NAMES.get(lang, lang))

        genres = [g for g in (m.get("genres") or []) if g in taste.genres]
        genres = genres[:MAX_GENRE_POINTS]
        score += W_GENRE * len(genres)
        reasons += genres

        era = era_of(m.get("year") or 0)
        if era and era in taste.eras:
            score += W_ERA
            reasons.append(era)

        if m["id"] in watchlist:
            score += W_WATCHLIST
            reasons.append("On your watchlist")

        if score >= MIN_SCORE:
            picks.append(
                Pick(m["id"], m.get("title", ""), m.get("year") or 0, score, reasons)
            )

    picks.sort(key=lambda p: (-p.score, -p.year, p.title))
    return picks[:top]


# --- loading and saving (runs as the logged-in user) -------------------------


def load_inputs(pb: PocketBaseClient):
    me = next(pb.list_all("users"))["id"]  # users can only see themselves

    profile = next(pb.list_all("taste_profile"), None) or {}
    taste = Taste(
        languages=set(profile.get("languages") or []),
        genres=set(profile.get("genres") or []),
        eras=set(profile.get("eras") or []),
    )

    favorites = []
    for f in pb.list_all("favorites"):
        person = pb.get("people", f["person"]) or {}
        favorites.append(Favorite(f["person"], f["role"], person.get("name", "?")))

    credits: list[dict] = []
    person_ids = sorted({f.person_id for f in favorites})
    for i in range(0, len(person_ids), 20):  # keep filter strings short
        chunk = person_ids[i : i + 20]
        flt = " || ".join(f'person = "{pid}"' for pid in chunk)
        credits += pb.list_all("credits", filter=flt)

    seen = {w["movie"] for w in pb.list_all("watches")}
    seen |= {r["movie"] for r in pb.list_all("reviews")}
    watchlist = {w["movie"] for w in pb.list_all("watchlist")}
    movies = list(pb.list_all("movies"))
    return me, taste, favorites, credits, seen, watchlist, movies


def save_picks(pb: PocketBaseClient, me: str, picks: list[Pick]) -> None:
    """Replace the user's curated list with these picks."""
    for old in list(pb.list_all("curated_items")):
        pb.delete("curated_items", old["id"])
    for rank, p in enumerate(picks, 1):
        pb.create(
            "curated_items",
            {
                "user": me,
                "movie": p.movie_id,
                "rank": rank,
                "score": p.score,
                "reasons": p.reasons,
            },
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build your curated list.")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP)
    parser.add_argument("--dry-run", action="store_true", help="print, don't save")
    args = parser.parse_args(argv)

    url = os.environ.get("PB_URL")
    if not url:
        sys.exit("PB_URL is not set. Run: set -a; source .env; set +a")
    email = os.environ.get("PB_USER_EMAIL") or input("Your email: ")
    password = getpass.getpass("Your password: ")

    with PocketBaseClient(url) as pb:
        pb.auth_with_password("users", email, password)
        me, taste, favorites, credits, seen, watchlist, movies = load_inputs(pb)
        if not favorites and not taste.languages:
            sys.exit("No taste yet: add a taste_profile and some favorites first.")

        hits = favorite_hits(credits, favorites)
        picks = score_movies(movies, hits, taste, seen, watchlist, args.top)

        for rank, p in enumerate(picks, 1):
            print(f"{rank:>2}. [{p.score:>2}] {p.title} ({p.year})")
            print(f"        {' · '.join(p.reasons)}")
        if not args.dry_run:
            save_picks(pb, me, picks)
            print(f"\nSaved {len(picks)} picks to your curated list.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
