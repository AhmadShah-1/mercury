"""Rendered crate UI: sidebar sections, favorites pinning, the Organize view, and escaping."""

from __future__ import annotations

import re

from sqlalchemy import select

from mercury.accounts.models import User
from mercury.buckets.crates import create_crate
from mercury.buckets.models import Bucket, Crate
from mercury.extensions import db
from tests.conftest import csrf_token


def _section(html: str, heading_id: str) -> str:
    """The sidebar group that starts at the given heading, up to the next group."""
    start = html.index(f'id="{heading_id}"')
    ends = [html.find(marker, start) for marker in ('class="nav-group', "nav-list-secondary")]
    return html[start : min(end for end in ends if end != -1)]


def _ids(app, *names):
    with app.app_context():
        return [db.session.scalar(select(Bucket).where(Bucket.name == name)).id for name in names]


def test_sidebar_puts_crates_above_buckets_with_one_edit_view(app, client, connected):
    html = client.get("/app").data.decode()
    assert html.index('id="crates-heading"') < html.index('id="buckets-heading"')
    crates = _section(html, "crates-heading")
    assert "Misc" in crates and 'href="/app/organize"' in crates
    assert "buckets.merge" not in html and "/merge" not in html
    with app.app_context():
        assert len(db.session.scalars(select(Bucket)).all()) == 4
    # Four equal-sized buckets: the largest three are shown, and the rest are one click away.
    buckets = _section(html, "buckets-heading")
    assert len(re.findall(r'data-drag="bucket"', buckets)) == 3
    assert "star to pin" in buckets


def test_starring_pins_items_per_section_without_starring_crate_members(app, client, connected):
    work_id, finance_id = _ids(app, "Work", "Finance")
    with app.app_context():
        user_id = db.session.scalar(select(User)).id
        desk = create_crate(user_id, [work_id], "Desk")
        desk_id = desk.id
    token = csrf_token(client.get("/app"))
    assert (
        client.post(
            f"/app/crates/{desk_id}/favorite", data={"favorite": "1", "csrf_token": token}
        ).status_code
        == 303
    )
    html = client.get("/app").data.decode()
    crates = _section(html, "crates-heading")
    assert "Desk" in crates and "Misc" not in crates
    # Buckets are still unpinned: starring Desk did not star Work.
    assert "star to pin" in _section(html, "buckets-heading")

    client.post(f"/app/buckets/{finance_id}/favorite", data={"favorite": "1", "csrf_token": token})
    buckets = _section(client.get("/app").data.decode(), "buckets-heading")
    assert re.findall(r'data-bucket-id="([^"]+)"', buckets) == [str(finance_id)]
    with app.app_context():
        assert db.session.get(Bucket, work_id).favorite is False
        assert db.session.get(Crate, desk_id).favorite is True


def test_organize_view_shows_every_crate_and_bucket_with_plain_form_fallbacks(
    app, client, connected
):
    response = client.get("/app/organize")
    assert response.status_code == 200
    html = response.data.decode()
    for name in ("Work", "Finance", "Purchases", "Newsletters", "Misc", "Automatic"):
        assert name in html
    forms = re.findall(r"<form\b[^>]*method=\"post\"[^>]*>.*?</form>", html, re.S)
    assert forms and all('name="csrf_token"' in form for form in forms)
    assert 'data-drop="new-crate"' in html and 'data-drop="loose"' in html


def test_bucket_and_crate_pages_offer_crate_controls_instead_of_merge(app, client, connected):
    (work_id,) = _ids(app, "Work")
    for url in (f"/app/buckets/{work_id}", f"/app/buckets/{work_id}/edit"):
        html = client.get(url).data.decode()
        assert f"/app/buckets/{work_id}/crate" in html
        assert "/merge" not in html


def test_crate_and_bucket_names_are_escaped_everywhere(app, client, connected):
    (work_id,) = _ids(app, "Work")
    hostile = '<img src="https://attacker.invalid/x">'
    token = csrf_token(client.get("/app"))
    client.post(
        "/app/crates", data={"bucket_ids": [str(work_id)], "name": hostile, "csrf_token": token}
    )
    with app.app_context():
        crate_id = db.session.scalar(select(Crate).where(Crate.kind == "user")).id
    for url in ("/app", f"/app/crates/{crate_id}", "/app/organize", f"/app/buckets/{work_id}"):
        page = client.get(url).data
        assert b"<img src=" not in page, url
        assert b"&lt;img" in page, url


def test_organize_needs_a_connected_mailbox(client, login):
    login()
    response = client.get("/app/organize")
    assert response.status_code == 302 and "/auth/gmail/connect" in response.headers["Location"]
    assert client.get("/app").status_code == 200
