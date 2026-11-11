"""Tests for the rule-based curated list: pure functions, no server."""

from cinema_diary.curate import (
    MIN_SCORE,
    Favorite,
    Pick,
    Taste,
    diversify,
    era_of,
    favorite_hits,
    is_released,
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
        "release_date": "1964-04-17",
        "year": 1964,
        "original_language": "bn",
        "genres": ["Drama", "Romance"],
    },
    {
        "id": "m_sagara",
        "title": "Sagara Sangamam",
        "release_date": "1983-06-03",
        "year": 1983,
        "original_language": "te",
        "genres": ["Drama", "Music"],
    },
    {
        "id": "m_cameo",
        "title": "Cameo Film",
        "release_date": "2001-01-01",
        "year": 2001,
        "original_language": "en",
        "genres": ["Comedy"],
    },
    {
        "id": "m_te_new",
        "title": "New Telugu Film",
        "release_date": "2022-01-14",
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
        "release_date": "1990-01-01",
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


# --- release filter and diversity --------------------------------------------


def test_is_released():
    assert is_released({"release_date": "2026-11-01"}, "2026-11-11")
    assert is_released({"release_date": "2026-11-11"}, "2026-11-11")  # today counts
    assert not is_released({"release_date": "2027-03-01"}, "2026-11-11")
    assert not is_released({"release_date": ""}, "2026-11-11")  # unknown date


def test_unreleased_films_are_skipped():
    upcoming = {
        "id": "m_soon",
        "title": "Upcoming",
        "year": 2027,
        "release_date": "2027-03-01",
        "original_language": "te",
    }
    picks = score_movies(
        [upcoming], {}, Taste(languages={"te"}), set(), set(), today="2026-11-11"
    )
    assert picks == []


def make_pick(mid, score, favs):
    return Pick(mid, mid, 2000, score, list(favs), list(favs))


def test_diversify_caps_each_favorite():
    mani = ["Directed by Mani Ratnam", "Music by A.R. Rahman"]
    picks = [make_pick(f"mani{i}", 10, mani) for i in range(6)]
    picks += [make_pick("fincher1", 7, ["Directed by David Fincher"])]
    picks += [make_pick("ray1", 7, ["Directed by Satyajit Ray"])]

    top = diversify(picks, top=5, cap=3)
    ids = [p.movie_id for p in top]
    assert ids == ["mani0", "mani1", "mani2", "fincher1", "ray1"]


def test_diversify_fills_leftover_slots_with_held_back_films():
    mani = ["Directed by Mani Ratnam"]
    picks = [make_pick(f"mani{i}", 10, mani) for i in range(5)]
    top = diversify(picks, top=5, cap=3)
    assert len(top) == 5  # nothing else to show, so held-back films come back


def test_diversify_ignores_films_without_favorites():
    picks = [make_pick(f"lang{i}", 2, []) for i in range(10)]
    assert len(diversify(picks, top=10, cap=3)) == 10
