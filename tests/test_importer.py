"""Importer tests with a fake TMDB and an in-memory PocketBase.
The key test: running the import twice leaves the same rows."""

import pytest

from cinema_diary.importer import (
    MAX_CAST,
    Importer,
    movie_record,
    pick_filmography,
    select_credits,
)
from cinema_diary.pb_client import derived_id


class FakeTMDB:
    def search_person(self, name):
        return [{"id": 12160, "name": name, "known_for_department": "Directing"}]

    def person_movie_credits(self, person_id):
        return {
            "crew": [
                {"id": 896, "job": "Director"},
                {"id": 897, "job": "Director"},
                {"id": 896, "job": "Screenplay"},  # same film, other job
                {"id": 999, "job": "Producer"},  # not directed: skipped
            ]
        }

    def movie(self, movie_id):
        return {
            "id": movie_id,
            "title": f"Film {movie_id}",
            "original_title": f"Film {movie_id}",
            "original_language": "bn",
            "release_date": "1964-04-17",
            "runtime": 117,
            "genres": [{"id": 18, "name": "Drama"}],
            "credits": {
                "cast": [
                    {
                        "id": 1,
                        "name": "Actor A",
                        "credit_id": f"c{movie_id}a",
                        "order": 0,
                    },
                ],
                "crew": [
                    {
                        "id": 12160,
                        "name": "Satyajit Ray",
                        "credit_id": f"c{movie_id}d",
                        "job": "Director",
                        "department": "Directing",
                    },
                    {
                        "id": 12160,
                        "name": "Satyajit Ray",
                        "credit_id": f"c{movie_id}m",
                        "job": "Original Music Composer",
                        "department": "Sound",
                    },
                    {
                        "id": 2,
                        "name": "Grip B",
                        "credit_id": f"c{movie_id}g",
                        "job": "Grip",
                        "department": "Crew",
                    },
                ],
            },
        }


class FakePB:
    def __init__(self):
        self.tables = {"movies": {}, "people": {}, "credits": {}}

    def upsert(self, collection, record_id, data):
        self.tables[collection][record_id] = {**data, "id": record_id}
        return self.tables[collection][record_id]

    def counts(self):
        return {name: len(rows) for name, rows in self.tables.items()}


def run_import(pb):
    importer = Importer(FakeTMDB(), pb)
    importer.import_person(importer.resolve_person("Satyajit Ray")["id"], "director")
    return importer


def test_imports_directed_movies_with_key_credits():
    pb = FakePB()
    run_import(pb)
    # 2 directed films; per film: actor + director + composer (grip skipped)
    assert pb.counts() == {"movies": 2, "people": 2, "credits": 6}


def test_rerun_is_idempotent():
    pb = FakePB()
    run_import(pb)
    first = pb.counts()
    run_import(pb)
    assert pb.counts() == first


def test_record_ids_are_derived_from_tmdb_ids():
    pb = FakePB()
    run_import(pb)
    assert derived_id("movie", 896) in pb.tables["movies"]
    assert derived_id("person", 12160) in pb.tables["people"]
    credit = pb.tables["credits"][derived_id("credit", "c896d")]
    assert credit["movie"] == derived_id("movie", 896)
    assert credit["person"] == derived_id("person", 12160)
    assert credit["kind"] == "crew"


def test_movie_record_mapping():
    rec = movie_record(
        {
            "id": 5,
            "title": "Charulata",
            "original_title": "চারুলতা",
            "original_language": "bn",
            "release_date": "1964-04-17",
            "runtime": None,
            "genres": [{"name": "Drama"}, {"name": "Romance"}],
        },
        "2026-11-11 00:00:00.000Z",
    )
    assert rec["year"] == 1964
    assert rec["runtime"] == 0
    assert rec["genres"] == ["Drama", "Romance"]
    assert rec["poster_path"] == ""


def test_movie_record_handles_missing_release_date():
    rec = movie_record({"id": 6, "title": "Upcoming", "release_date": ""}, "x")
    assert rec["year"] == 0


def test_select_credits_caps_cast_and_filters_crew():
    credits = {
        "cast": [{"id": i, "order": i, "credit_id": f"c{i}"} for i in range(50)],
        "crew": [
            {"id": 100, "job": "Lyricist", "credit_id": "l"},
            {"id": 101, "job": "Catering", "credit_id": "x"},
        ],
    }
    chosen = select_credits(credits)
    cast = [c for kind, c in chosen if kind == "cast"]
    crew = [c for kind, c in chosen if kind == "crew"]
    assert len(cast) == MAX_CAST
    assert cast[0]["order"] == 0
    assert [c["job"] for c in crew] == ["Lyricist"]


# --- role-based seeds --------------------------------------------------------

FILMOGRAPHY = {
    "cast": [
        {"id": 10, "popularity": 5.0, "original_language": "te"},
        {"id": 11, "popularity": 9.0, "original_language": "ta"},
    ],
    "crew": [
        {"id": 20, "job": "Director", "popularity": 1.0, "original_language": "te"},
        {
            "id": 21,
            "job": "Original Music Composer",
            "popularity": 3.0,
            "original_language": "ta",
        },
        {"id": 22, "job": "Music", "popularity": 7.0, "original_language": "te"},
        {"id": 22, "job": "Songs", "popularity": 7.0, "original_language": "te"},
        {"id": 23, "job": "Lyricist", "popularity": 2.0, "original_language": "te"},
    ],
}


def test_actor_role_uses_cast_most_popular_first():
    assert pick_filmography(FILMOGRAPHY, "actor") == [11, 10]


def test_composer_role_uses_music_jobs():
    assert pick_filmography(FILMOGRAPHY, "composer") == [22, 21]


def test_lyricist_role_includes_songs_and_dedupes():
    assert pick_filmography(FILMOGRAPHY, "lyricist") == [22, 23]


def test_director_role_only_directing_credits():
    assert pick_filmography(FILMOGRAPHY, "director") == [20]


def test_limit_caps_big_filmographies():
    big = {"cast": [{"id": i, "popularity": float(i)} for i in range(500)]}
    picked = pick_filmography(big, "actor", limit=40)
    assert len(picked) == 40
    assert picked[0] == 499  # most popular first


def test_language_filter():
    langs = frozenset({"te"})
    assert pick_filmography(FILMOGRAPHY, "composer", languages=langs) == [22]


def test_unknown_role_rejected():
    with pytest.raises(ValueError):
        pick_filmography(FILMOGRAPHY, "caterer")
