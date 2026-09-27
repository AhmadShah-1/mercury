"""Drag-and-drop crate flow against a running synthetic Mercury server.

Skipped unless MERCURY_BROWSER_BASE_URL points at a loopback synthetic server (see
test_demo_flow.py). Like that flow, it disconnects the demo mailbox first.
"""

from __future__ import annotations

import re

import pytest

from tests.browser.flows import (
    BASE_URL,
    connect_synthetic_mailbox,
    disconnect_if_connected,
    login,
)

pytestmark = [
    pytest.mark.skipif(not BASE_URL, reason="set MERCURY_BROWSER_BASE_URL to run browser flows"),
    pytest.mark.enable_socket,
]

playwright_api = pytest.importorskip("playwright.sync_api")
expect = playwright_api.expect


def _drag(page, source, target):
    """A real pointer drag, which Chromium turns into native HTML drag-and-drop events."""
    start, end = source.bounding_box(), target.bounding_box()
    x, y = start["x"] + start["width"] / 2, start["y"] + start["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 8, y + 8, steps=3)
    page.mouse.move(end["x"] + end["width"] / 2, end["y"] + end["height"] / 2, steps=12)
    page.mouse.up()


def test_crates_are_made_and_used_by_dragging(watched_page):
    page, problems = watched_page
    login(page, expect)
    disconnect_if_connected(page, expect)
    connect_synthetic_mailbox(page, expect)

    # The small demo buckets start in Misc, and the Crates section sits above Buckets.
    nav = page.locator("[data-ws-nav]")
    expect(nav.locator("#crates-heading")).to_be_visible()
    expect(nav.locator('[data-drop="crate"]', has_text="Misc")).to_be_visible()
    headings = nav.locator(".nav-heading-text").all_inner_texts()
    assert [text.casefold() for text in headings[:2]] == ["crates", "buckets"]

    # Edit view: take Work out of Misc, then drop Finance onto it to make a crate of both.
    nav.get_by_role("link", name="Edit crates and buckets").click()
    page.wait_for_url(re.compile(r"/app/organize$"))

    def tile(name):
        return page.locator(".tile", has=page.locator(".tile-name", has_text=name))

    tray = page.locator('[data-drop="loose"]')
    _drag(page, tile("Work"), tray)
    expect(tray.locator(".tile-name", has_text="Work")).to_be_visible()
    _drag(page, tile("Finance"), tray.locator(".tile", has_text="Work"))
    crate = page.locator(
        ".crate-card[data-crate-id]",
        has=page.locator(".crate-card-name", has_text="Work & Finance"),
    )
    expect(crate.locator(".tile-name")).to_have_text(["Finance", "Work"])
    expect(page.locator("#toast-stack")).to_be_visible()

    # Star it: the Crates section now pins only favorites.
    crate.locator(".crate-card-head .star-btn").click()
    expect(crate.locator(".crate-card-head .star-btn")).to_have_attribute("aria-pressed", "true")
    crate.locator(".crate-card-name a").click()
    page.wait_for_url(re.compile(r"/app/crates/"))
    crates_nav = page.locator("[data-ws-nav] .nav-group-crates")
    expect(crates_nav.locator('[data-drop="crate"]')).to_have_count(1)

    # The crate view lists both buckets' conversations as one list, with each bucket visible.
    rows = page.locator("[data-thread-list] [data-thread-row]")
    expect(rows).to_have_count(2)
    expect(page.locator("[data-thread-list]")).to_contain_text("Revised launch forecast")
    expect(page.locator("[data-thread-list]")).to_contain_text("Monthly statement notice")

    # Drag one conversation onto a sidebar bucket outside the crate: it leaves this list.
    row = rows.filter(has_text="Revised launch forecast")
    target = page.locator('[data-ws-nav] .nav-group-buckets [data-drop="bucket"]').filter(
        has_text="Purchases"
    )
    _drag(page, row, target)
    expect(page.locator("#toast-stack")).to_contain_text("Moved")
    expect(rows).to_have_count(1)

    assert page.evaluate("document.documentElement.scrollWidth") <= 1440
    assert not problems, problems
