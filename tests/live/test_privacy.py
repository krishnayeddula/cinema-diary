"""Live privacy tests: run against a real PocketBase with `make test-live`.

Needs two ordinary user accounts, alice and bob, created by a superuser in
the admin UI, and these env vars (in .env):
    PB_URL, PB_SA_EMAIL, PB_SA_PASSWORD
    PB_TEST_ALICE_EMAIL, PB_TEST_BOB_EMAIL, PB_TEST_PASSWORD

Each test creates its own rows as alice and deletes them afterwards.
Skipped automatically when the env vars are missing (e.g. in CI).
"""

import os

import pytest

from cinema_diary.pb_client import PocketBaseClient, PocketBaseError

REQUIRED = [
    "PB_URL",
    "PB_SA_EMAIL",
    "PB_SA_PASSWORD",
    "PB_TEST_ALICE_EMAIL",
    "PB_TEST_BOB_EMAIL",
    "PB_TEST_PASSWORD",
]
pytestmark = pytest.mark.skipif(
    any(not os.environ.get(v) for v in REQUIRED),
    reason="live PocketBase env vars not set",
)

DIARY = ["taste_profile", "favorites", "watches", "reviews", "watchlist"]


def login(collection, email_var, password_var):
    pb = PocketBaseClient(os.environ["PB_URL"], max_retries=1)
    pb.auth_with_password(collection, os.environ[email_var], os.environ[password_var])
    return pb


@pytest.fixture(scope="module")
def alice():
    return login("users", "PB_TEST_ALICE_EMAIL", "PB_TEST_PASSWORD")


@pytest.fixture(scope="module")
def bob():
    return login("users", "PB_TEST_BOB_EMAIL", "PB_TEST_PASSWORD")


@pytest.fixture(scope="module")
def importer():
    return login("service_accounts", "PB_SA_EMAIL", "PB_SA_PASSWORD")


@pytest.fixture(scope="module")
def ids(alice, bob):
    """Record ids we need: both users and two catalog movies."""
    alice_id = next(alice.list_all("users"))["id"]  # users only see themselves
    bob_id = next(bob.list_all("users"))["id"]
    movies = alice.list_page("movies", per_page=2)["items"]
    people = alice.list_page("people", per_page=1)["items"]
    assert len(movies) == 2 and people, "import some movies first (P1 importer)"
    return {
        "alice": alice_id,
        "bob": bob_id,
        "movie": movies[0]["id"],
        "movie2": movies[1]["id"],
        "person": people[0]["id"],
    }


@pytest.fixture
def alice_rows(alice, ids):
    """One real row of alice's in every diary collection."""
    me = ids["alice"]
    rows = {
        "taste_profile": {"user": me, "languages": ["te", "bn"]},
        "favorites": {"user": me, "person": ids["person"], "role": "director"},
        "watches": {
            "user": me,
            "movie": ids["movie"],
            "watched_on": "2026-11-11 00:00:00.000Z",
        },
        "reviews": {"user": me, "movie": ids["movie2"], "stars": 4},
        "watchlist": {"user": me, "movie": ids["movie"]},
    }
    created = {c: alice.create(c, data) for c, data in rows.items()}
    yield created
    for c, rec in created.items():
        alice.delete(c, rec["id"])


@pytest.fixture
def alice_review(alice, ids):
    rec = alice.create(
        "reviews",
        {"user": ids["alice"], "movie": ids["movie"], "stars": 5, "music": 5},
    )
    yield rec
    alice.delete("reviews", rec["id"])


# --- the owner can use their own diary ------------------------------------


def test_owner_sees_own_review(alice, alice_review):
    got = alice.get("reviews", alice_review["id"])
    assert got is not None and got["stars"] == 5


def test_owner_can_update_own_review(alice, alice_review):
    updated = alice.update("reviews", alice_review["id"], {"stars": 4})
    assert updated["stars"] == 4


# --- other users see nothing ----------------------------------------------


@pytest.mark.parametrize("collection", DIARY)
def test_other_user_sees_none_of_owners_rows(alice, bob, alice_rows, collection):
    assert alice.list_page(collection)["totalItems"] >= 1  # the row exists...
    assert bob.list_page(collection)["totalItems"] == 0  # ...but bob sees nothing


def test_other_user_cannot_view_by_id(bob, alice_review):
    assert bob.get("reviews", alice_review["id"]) is None  # 404, not 403


def test_other_user_cannot_update(bob, alice_review):
    with pytest.raises(PocketBaseError) as err:
        bob.update("reviews", alice_review["id"], {"stars": 1})
    assert err.value.status == 404


def test_other_user_cannot_delete(bob, alice_review):
    with pytest.raises(PocketBaseError) as err:
        bob.delete("reviews", alice_review["id"])
    assert err.value.status == 404


# --- nobody can write as someone else --------------------------------------


def test_cannot_create_row_for_another_user(bob, ids):
    with pytest.raises(PocketBaseError) as err:
        bob.create(
            "reviews", {"user": ids["alice"], "movie": ids["movie2"], "stars": 1}
        )
    assert err.value.status in (400, 403)


def test_cannot_hand_row_to_another_user(alice, ids, alice_review):
    with pytest.raises(PocketBaseError):
        alice.update("reviews", alice_review["id"], {"user": ids["bob"]})


# --- the import service account cannot read diaries ------------------------


@pytest.mark.parametrize("collection", DIARY)
def test_service_account_sees_no_diary_rows(importer, alice_rows, collection):
    assert importer.list_page(collection)["totalItems"] == 0


def test_service_account_cannot_write_diary(importer, ids):
    with pytest.raises(PocketBaseError):
        importer.create(
            "reviews", {"user": ids["alice"], "movie": ids["movie2"], "stars": 1}
        )


# --- data rules -------------------------------------------------------------


def test_one_review_per_user_per_movie(alice, ids, alice_review):
    with pytest.raises(PocketBaseError) as err:
        alice.create(
            "reviews", {"user": ids["alice"], "movie": ids["movie"], "stars": 3}
        )
    assert err.value.status == 400


def test_stars_must_be_1_to_5(alice, ids):
    with pytest.raises(PocketBaseError) as err:
        alice.create(
            "reviews", {"user": ids["alice"], "movie": ids["movie2"], "stars": 9}
        )
    assert err.value.status == 400
