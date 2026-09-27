"""Crates: non-destructive groups of buckets, favorites, and Mercury's Misc filing."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from mercury.accounts.models import GmailAccount, User
from mercury.buckets.crates import (
    MISC_MAX_MEMBERS,
    bucket_sizes,
    build_library,
    combine_crates,
    create_crate,
    ensure_misc_crate,
    file_small_buckets,
    place_bucket,
    set_bucket_favorite,
    set_crate_favorite,
)
from mercury.buckets.models import Bucket, BucketAssignment, Crate
from mercury.buckets.service import active_buckets, archive_bucket, create_bucket
from mercury.extensions import db
from mercury.inbox.models import EmailThread
from tests.bucket_vectors import add_thread, assign, make_bucket
from tests.conftest import csrf_token

FIXTURE_SUBJECTS = {
    "Work": "fixture-work-review",
    "Finance": "fixture-bank-html",
    "Purchases": "fixture-shopping",
}


def _bucket(name: str) -> Bucket:
    return db.session.scalar(select(Bucket).where(Bucket.name == name))


def _misc() -> Crate:
    return db.session.scalar(select(Crate).where(Crate.kind == "misc"))


def _subject(name: str) -> bytes:
    thread = db.session.scalar(
        select(EmailThread).where(EmailThread.gmail_thread_id == FIXTURE_SUBJECTS[name])
    )
    return thread.subject.encode()


def _token(client) -> str:
    return csrf_token(client.get("/app/buckets/new"))


def _fill(account: GmailAccount, bucket: Bucket, count: int) -> None:
    for _ in range(count):
        assign(account, add_thread(account, [1.0] + [0.0] * 511), bucket)


def test_connecting_creates_one_misc_crate_holding_the_small_demo_buckets(app, connected):
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        misc = _misc()
        assert misc is not None and misc.name == "Misc"
        assert ensure_misc_crate(account).id == misc.id
        assert db.session.scalar(select(func.count()).select_from(Crate)) == 1
        demo = active_buckets(account.user_id)
        assert demo and all(b.crate_id == misc.id and b.crate_origin == "auto" for b in demo)


def test_crate_view_lists_all_member_conversations_and_can_narrow_to_one(app, client, connected):
    with app.app_context():
        work, finance, purchases = _bucket("Work"), _bucket("Finance"), _bucket("Purchases")
        ids = work.id, finance.id, purchases.id
        subjects = _subject("Work"), _subject("Finance"), _subject("Purchases")
    work_id, finance_id, purchases_id = ids
    created = client.post(
        "/app/crates",
        data={
            "bucket_ids": [str(work_id), str(finance_id)],
            "name": "Desk",
            "csrf_token": _token(client),
        },
    )
    assert created.status_code == 303
    with app.app_context():
        crate = db.session.scalar(select(Crate).where(Crate.name == "Desk"))
        crate_id = crate.id
        assert {b.id for b in active_buckets(crate.user_id) if b.crate_id == crate_id} == {
            work_id,
            finance_id,
        }

    everything = client.get(f"/app/crates/{crate_id}")
    assert everything.status_code == 200
    assert subjects[0] in everything.data and subjects[1] in everything.data
    assert subjects[2] not in everything.data

    narrowed = client.get(f"/app/crates/{crate_id}?bucket={work_id}")
    assert subjects[0] in narrowed.data and subjects[1] not in narrowed.data

    # A bucket outside the crate cannot be used to reach its conversations through the crate.
    outside = client.get(f"/app/crates/{crate_id}?bucket={purchases_id}")
    assert subjects[2] not in outside.data


def test_placing_buckets_moves_them_and_an_emptied_user_crate_disappears(app, client, connected):
    with app.app_context():
        work, finance, misc = _bucket("Work"), _bucket("Finance"), _misc()
        work_id, finance_id, misc_id = work.id, finance.id, misc.id
    token = _token(client)

    paired = client.post(
        f"/app/buckets/{work_id}/crate",
        data={"crate_id": "new", "with_bucket_id": str(finance_id), "csrf_token": token},
    )
    assert paired.status_code == 303
    with app.app_context():
        crate = db.session.get(Crate, db.session.get(Bucket, work_id).crate_id)
        assert crate.kind == "user" and crate.name == "Finance & Work"
        assert db.session.get(Bucket, finance_id).crate_id == crate.id
        assert db.session.get(Bucket, work_id).crate_origin == "user"
        crate_id = crate.id

    taken_out = client.post(
        f"/app/buckets/{work_id}/crate",
        data={"crate_id": "", "csrf_token": token, "next": "/app/organize"},
    )
    assert taken_out.headers["Location"].endswith("/app/organize")
    back_to_misc = client.post(
        f"/app/buckets/{finance_id}/crate", data={"crate_id": str(misc_id), "csrf_token": token}
    )
    assert back_to_misc.status_code == 303
    with app.app_context():
        assert db.session.get(Bucket, work_id).crate_id is None
        assert db.session.get(Bucket, finance_id).crate_id == misc_id
        assert db.session.get(Crate, crate_id) is None
        # Grouping never touched the conversations themselves.
        assert (
            db.session.scalar(
                select(func.count())
                .select_from(BucketAssignment)
                .where(BucketAssignment.bucket_id.in_([work_id, finance_id]))
            )
            == 2
        )


@pytest.mark.parametrize(
    "target", ["https://attacker.invalid/app", "//attacker.invalid/app", "/\\attacker", "/public"]
)
def test_redirect_after_a_crate_change_stays_inside_mercury(app, client, connected, target):
    with app.app_context():
        work_id = _bucket("Work").id
    response = client.post(
        f"/app/buckets/{work_id}/favorite",
        data={"favorite": "1", "csrf_token": _token(client), "next": target},
    )
    assert response.status_code == 303
    assert response.headers["Location"].endswith(f"/app/buckets/{work_id}")


def test_dissolving_and_combining_crates(app, client, connected):
    with app.app_context():
        user_id = db.session.scalar(select(User)).id
        work, finance, purchases, misc = (
            _bucket("Work"),
            _bucket("Finance"),
            _bucket("Purchases"),
            _misc(),
        )
        first = create_crate(user_id, [work.id], "First")
        second = create_crate(user_id, [finance.id], "Second")
        ids = work.id, finance.id, purchases.id, first.id, second.id, misc.id
    work_id, finance_id, purchases_id, first_id, second_id, misc_id = ids
    token = _token(client)

    combined = client.post(
        f"/app/crates/{first_id}/combine", data={"target_id": str(second_id), "csrf_token": token}
    )
    assert combined.status_code == 303
    itself = client.post(
        f"/app/crates/{second_id}/combine", data={"target_id": str(second_id), "csrf_token": token}
    )
    assert itself.status_code == 409
    with app.app_context():
        assert db.session.get(Crate, first_id) is None
        assert db.session.get(Bucket, work_id).crate_id == second_id

    dissolved = client.post(f"/app/crates/{second_id}/dissolve", data={"csrf_token": token})
    assert dissolved.status_code == 303
    emptied = client.post(f"/app/crates/{misc_id}/dissolve", data={"csrf_token": token})
    assert emptied.status_code == 303
    with app.app_context():
        assert db.session.get(Crate, second_id) is None
        assert db.session.get(Crate, misc_id) is not None
        for bucket_id in (work_id, finance_id, purchases_id):
            bucket = db.session.get(Bucket, bucket_id)
            assert bucket.crate_id is None and bucket.crate_origin == "user"


def test_rename_keeps_names_unique_and_archiving_the_last_member_removes_the_crate(
    app, client, connected
):
    with app.app_context():
        user_id = db.session.scalar(select(User)).id
        work = _bucket("Work")
        crate = create_crate(user_id, [work.id], "Solo")
        crate_id, work_id = crate.id, work.id
    token = _token(client)
    renamed = client.post(
        f"/app/crates/{crate_id}/rename", data={"name": "  misc ", "csrf_token": token}
    )
    assert renamed.status_code == 303
    blank = client.post(f"/app/crates/{crate_id}/rename", data={"name": " ", "csrf_token": token})
    assert blank.status_code == 400
    with app.app_context():
        assert db.session.get(Crate, crate_id).name == "misc (2)"
        archive_bucket(user_id, work_id)
        assert db.session.get(Crate, crate_id) is None
        assert db.session.get(Bucket, work_id).crate_id is None


def test_favorites_are_independent_and_pin_each_sidebar_section(app, connected):
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        user_id = account.user_id
        misc = _misc()
        big = create_bucket(user_id, account.id, "Big")
        _fill(account, big, 5)
        mid = create_bucket(user_id, account.id, "Mid")
        _fill(account, mid, 3)
        empty_crate = create_crate(user_id, [mid.id], "Empty soon")
        place_bucket(user_id, mid.id, None)

        library = build_library(user_id, buckets=active_buckets(user_id))
        assert not library.crates_pinned and not library.buckets_pinned
        # Largest three buckets; crates without buckets never fill the unpinned list.
        assert [b.name for b in library.nav_buckets] == ["Big", "Mid", "Finance"]
        assert [c.id for c in library.nav_crates] == [misc.id]
        assert db.session.get(Crate, empty_crate.id) is None

        set_crate_favorite(user_id, misc.id, True)
        library = build_library(user_id, buckets=active_buckets(user_id))
        assert library.crates_pinned and [c.id for c in library.nav_crates] == [misc.id]
        # Favoriting a crate does not favorite, or pin, the buckets inside it.
        assert not any(b.favorite for b in active_buckets(user_id))
        assert not library.buckets_pinned

        finance = _bucket("Finance")
        set_bucket_favorite(user_id, finance.id, True)
        library = build_library(user_id, buckets=active_buckets(user_id))
        assert [b.id for b in library.nav_buckets] == [finance.id]
        assert library.crate_of[finance.id].id == misc.id
        assert db.session.get(Crate, misc.id).favorite is True
        assert library.hidden_count == len(library.buckets) - 1

        # The crate holding the selected bucket is shown expanded even when not pinned.
        set_crate_favorite(user_id, misc.id, False)
        set_bucket_favorite(user_id, finance.id, False)
        other = create_crate(user_id, [big.id], "Other")
        work = _bucket("Work")
        library = build_library(user_id, buckets=active_buckets(user_id), selected_bucket=work)
        assert library.expanded_crate_id == misc.id
        library = build_library(user_id, buckets=active_buckets(user_id), selected_crate=other)
        assert library.expanded_crate_id == other.id
        assert other.id in [c.id for c in library.nav_crates]


def test_mercury_files_small_suggested_buckets_once_and_graduates_grown_ones(app, connected):
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        user_id = account.user_id
        misc = _misc()
        small = make_bucket(account, "Small Topic")
        large = make_bucket(account, "Large Topic")
        _fill(account, small, 3)
        _fill(account, large, MISC_MAX_MEMBERS)
        mine = create_bucket(user_id, account.id, "Mine")

        assert file_small_buckets(account) == 1
        db.session.expire_all()
        assert (small.crate_id, small.crate_origin) == (misc.id, "auto")
        assert (large.crate_id, large.crate_origin) == (None, "auto")
        assert (mine.crate_id, mine.crate_origin) == (None, "user")

        _fill(account, small, MISC_MAX_MEMBERS - 3)
        assert bucket_sizes(user_id)[small.id] == MISC_MAX_MEMBERS
        assert file_small_buckets(account) == 1
        db.session.expire_all()
        assert (small.crate_id, small.crate_origin) == (None, "auto")

        # Once judged, shrinking again never files it back; nothing moves on a repeat pass.
        db.session.execute(
            BucketAssignment.__table__.delete().where(BucketAssignment.bucket_id == small.id)
        )
        db.session.commit()
        assert file_small_buckets(account) == 0
        db.session.expire_all()
        assert small.crate_id is None


def test_a_bucket_the_user_placed_in_misc_is_never_moved_by_mercury(app, connected):
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        misc = _misc()
        grown = make_bucket(account, "Grown Topic")
        place_bucket(account.user_id, grown.id, misc.id)
        _fill(account, grown, MISC_MAX_MEMBERS + 2)
        assert file_small_buckets(account) == 0
        db.session.expire_all()
        assert (grown.crate_id, grown.crate_origin) == (misc.id, "user")


def test_the_old_destructive_merge_is_gone(app, client, connected):
    with app.app_context():
        work_id = _bucket("Work").id
    assert client.get(f"/app/buckets/{work_id}/merge").status_code == 404


def test_crate_changes_require_csrf(app, client, connected):
    with app.app_context():
        work_id, misc_id = _bucket("Work").id, _misc().id
    assert client.post(f"/app/buckets/{work_id}/crate", data={"crate_id": ""}).status_code == 400
    assert client.post(f"/app/buckets/{work_id}/favorite", data={"favorite": "1"}).status_code == (
        400
    )
    assert client.post(f"/app/crates/{misc_id}/dissolve").status_code == 400
    with app.app_context():
        assert db.session.get(Bucket, work_id).crate_id == misc_id
        assert db.session.get(Bucket, work_id).favorite is False


def test_combining_a_crate_with_itself_is_rejected_by_the_service(app, connected):
    with app.app_context():
        misc = _misc()
        with pytest.raises(ValueError):
            combine_crates(misc.user_id, misc.id, misc.id)


def test_quiet_drag_requests_get_no_content_instead_of_a_redirect(app, client, connected):
    with app.app_context():
        work_id = _bucket("Work").id
    token = _token(client)
    quiet = client.post(
        f"/app/buckets/{work_id}/crate",
        data={"crate_id": "", "csrf_token": token},
        headers={"X-Mercury-Quiet": "1"},
    )
    assert quiet.status_code == 204 and not quiet.data
    assert b"left its crate" not in client.get("/app").data


def test_choosing_the_current_crate_keeps_mercurys_automatic_filing(app, client, connected):
    with app.app_context():
        work, misc = _bucket("Work"), _misc()
        work_id, misc_id = work.id, misc.id
        assert work.crate_origin == "auto"
    token = _token(client)
    same = client.post(
        f"/app/buckets/{work_id}/crate", data={"crate_id": str(misc_id), "csrf_token": token}
    )
    assert same.status_code == 303
    with app.app_context():
        assert db.session.get(Bucket, work_id).crate_origin == "auto"


def test_undo_hands_a_filed_bucket_back_to_automatic_filing_only(app, client, connected):
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        work_id, misc_id = _bucket("Work").id, _misc().id
        mine = create_bucket(account.user_id, account.id, "Mine")
        other = create_crate(account.user_id, [mine.id], "Other")
        mine_id, other_id = mine.id, other.id
    token = _token(client)
    client.post(f"/app/buckets/{work_id}/crate", data={"crate_id": "", "csrf_token": token})
    undo = client.post(
        f"/app/buckets/{work_id}/crate",
        data={"crate_id": str(misc_id), "restore": "auto", "csrf_token": token},
    )
    assert undo.status_code == 303
    # Restoring is refused for a user-made bucket, or for a crate other than Misc.
    for bucket_id, crate_id in ((mine_id, misc_id), (work_id, other_id)):
        refused = client.post(
            f"/app/buckets/{bucket_id}/crate",
            data={"crate_id": str(crate_id), "restore": "auto", "csrf_token": token},
        )
        assert refused.status_code == 409
    bogus = client.post(
        f"/app/buckets/{work_id}/crate",
        data={"crate_id": "", "restore": "user", "csrf_token": token},
    )
    assert bogus.status_code == 400
    with app.app_context():
        work = db.session.get(Bucket, work_id)
        assert (work.crate_id, work.crate_origin) == (misc_id, "auto")
        assert db.session.get(Bucket, mine_id).crate_id == other_id
