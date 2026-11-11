"""Tests for the rule-based curated list: pure functions, no server."""

from cinema_diary.curate import (
    MIN_SCORE,
    Favorite,
    Taste,
    era_of,
    favorite_hits,
    score_movies,
)

RAY = Favorite("p_ray", "director", "Satyajit Ray")
RAJA = Favorite("p_raja", "composer", "Ilaiyaraaja")

CREDITS = [
    {"movie": "m_charu", "person": "p_ray", "kind": "crew", "job": "Director"},
    {"movie": "m_charu", "person": "p_ray", "kind": "crew", "job": "Screenplay"},
    {"movie": "m_sagara", "person": "p_raja", "kind": "crew", "job": "Music"},
    # Ilaiyaraaja acting in a film is not a "composer" hit
    {"movie": "m_cameo", "person": "p_raja", "kind": "cast", "job": ""},
]

MOVIES = [
    {
        "id": "m_charu",
        "title": "Charulata",
        "year": 1964,
        "original_language": "bn",
        "genres": ["Drama", "Romance"],
    },
    {
        "id": "m_sagara",
        "title": "Sagara Sangamam",
        "year": 1983,
        "original_language": "te",
        "genres": ["Drama", "Music"],
    },
    {
        "id": "m_cameo",
        "title": "Cameo Film",
        "year": 2001,
        "original_language": "en",
        "genres": ["Comedy"],
    },
    {
        "id": "m_te_new",
        "title": "New Telugu Film",
        "year": 2022,
        "original_language": "te",
        "genres": ["Action"],
    },
]

TASTE = Taste(languages={"te", "bn"}, genres={"Drama"}, eras={"1980s"})


def test_era_of():
    assert era_of(1964) == "1960s"
    assert era_of(0) == ""


def test_favorite_hits_respect_role():
    hits = favorite_hits(CREDITS, [RAY, RAJA])
    assert hits["m_charu"] == ["Directed by Satyajit Ray"]  # one reason, not two
    assert hits["m_sagara"] == ["Music by Ilaiyaraaja"]
    assert "m_cameo" not in hits  # acting credit != composer favorite


def test_scores_and_reasons():
    hits = favorite_hits(CREDITS, [RAY, RAJA])
    picks = score_movies(MOVIES, hits, TASTE, seen=set(), watchlist=set())
    by_id = {p.movie_id: p for p in picks}

    # 3 favorite + 2 Telugu + 1 Drama + 1 1980s
    assert by_id["m_sagara"].score == 7
    assert by_id["m_sagara"].reasons == [
        "Music by Ilaiyaraaja",
        "Telugu",
        "Drama",
        "1980s",
    ]
    # 3 favorite + 2 Bengali + 1 Drama
    assert by_id["m_charu"].score == 6
    # Telugu only: 2 points, just enough
    assert by_id["m_te_new"].score == MIN_SCORE
    # nothing matches: not listed
    assert "m_cameo" not in by_id
    assert [p.movie_id for p in picks] == ["m_sagara", "m_charu", "m_te_new"]


def test_seen_films_are_skipped():
    hits = favorite_hits(CREDITS, [RAY, RAJA])
    picks = score_movies(MOVIES, hits, TASTE, seen={"m_sagara"}, watchlist=set())
    assert "m_sagara" not in [p.movie_id for p in picks]


def test_watchlist_adds_a_point():
    picks = score_movies(
        MOVIES, {}, Taste(languages={"te"}), seen=set(), watchlist={"m_te_new"}
    )
    top = picks[0]
    assert top.movie_id == "m_te_new"
    assert top.score == 3
    assert "On your watchlist" in top.reasons


def test_genre_points_are_capped():
    movie = {
        "id": "m",
        "title": "x",
        "year": 1990,
        "original_language": "xx",
        "genres": ["A", "B", "C", "D"],
    }
    picks = score_movies([movie], {}, Taste(genres={"A", "B", "C", "D"}), set(), set())
    assert picks[0].score == 2


def test_top_limits_the_list():
    picks = score_movies(MOVIES, {}, Taste(languages={"te", "bn"}), set(), set(), top=1)
    assert len(picks) == 1


def test_same_input_same_output():
    hits = favorite_hits(CREDITS, [RAY, RAJA])
    a = score_movies(MOVIES, hits, TASTE, set(), set())
    b = score_movies(MOVIES, hits, TASTE, set(), set())
    assert a == b
