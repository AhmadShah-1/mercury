"""End-to-end browser flow against a running synthetic Mercury server.

Skipped unless MERCURY_BROWSER_BASE_URL points at a loopback server started with the synthetic
profile (AUTH_MODE=dev, MAIL_MODE=fake, AI_PROVIDER=fake). The flow resets the demo user's
mailbox by disconnecting it first, so never point it at a server holding data you want to keep.
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
    # Playwright's sync API uses a local socketpair for its event loop; Chromium itself only
    # talks to the loopback server below.
    pytest.mark.enable_socket,
]

playwright_api = pytest.importorskip("playwright.sync_api")
expect = playwright_api.expect


def test_synthetic_demo_flow(watched_page):
    page, problems = watched_page
    login(page, expect)
    disconnect_if_connected(page, expect)

    # Connect with the explicit disclosure; the required box is enforced server-side.
    connect_synthetic_mailbox(page, expect)

    # Workspace: three regions, original subjects, honest badges.
    row = page.locator("[data-thread-row]", has_text="Revised launch forecast")
    expect(row).to_contain_text("Unread in Gmail")
    expect(row).to_contain_text("New in Mercury")

    # Reader loads into the panel via HTMX; body arrives separately.
    row.locator("[data-reader-link]").click()
    reader = page.locator("#reader-panel")
    expect(reader.locator("#reader-subject")).to_have_text("Revised launch forecast")
    expect(reader).to_contain_text("AI summary")
    expect(reader.locator("#message-body")).to_contain_text("forecast", timeout=10_000)
    gmail = reader.get_by_role("link", name=re.compile("Open in Gmail"))
    expect(gmail).to_have_attribute("rel", "noopener noreferrer")
    expect(gmail).to_have_attribute("target", "_blank")
    expect(row).not_to_contain_text("New in Mercury")

    # Move to a bucket in place.
    reader.locator("select[name=bucket_id]").select_option(label="Finance")
    reader.get_by_role("button", name="Move", exact=True).click()
    expect(page.locator("#toast-stack")).to_contain_text("Conversation moved")
    expect(page.locator("[data-thread-row]", has_text="Revised launch forecast")).to_contain_text(
        "Finance"
    )

    # Mark the possible action handled (Mercury-only), then see the reopen control.
    page.get_by_role("button", name="Mark handled in Mercury").click()
    expect(page.locator("#toast-stack")).to_contain_text("Marked handled in Mercury")
    expect(page.locator("#reader-panel")).to_contain_text("Reopen")

    # Keyboard navigation moves focus through rows; ? opens shortcut help.
    page.locator("#list-title").click()
    links = page.locator("[data-thread-row] [data-reader-link]")
    page.keyboard.press("j")  # next after the conversation open in the reader
    expect(links.nth(1)).to_be_focused()
    page.keyboard.press("k")
    expect(links.nth(0)).to_be_focused()
    page.keyboard.press("?")
    expect(page.locator("#shortcuts-dialog")).to_be_visible()
    page.keyboard.press("Escape")

    # Bulk move two conversations with a confirmation showing the count.
    boxes = page.locator("[data-row-select]")
    boxes.nth(1).check()
    boxes.nth(2).check()
    expect(page.locator("[data-bulk-count]")).to_have_text("2 selected")
    page.get_by_role("button", name=re.compile("Move to")).click()
    dialog = page.locator("#bulk-move-dialog")
    expect(dialog).to_contain_text("2 conversations")
    expect(dialog).to_contain_text("Gmail messages are not moved, archived, or deleted")
    dialog.locator("[data-bulk-destination]").select_option(label="Work")
    dialog.locator("[data-bulk-confirm]").click()
    expect(page.locator("#toast-stack")).to_contain_text("Moved 2 conversations")

    # Settings explains disconnect/delete consequences.
    page.goto(f"{BASE_URL}/settings")
    expect(page.get_by_role("heading", name="Disconnect Gmail")).to_be_visible()
    expect(page.locator("body")).to_contain_text("Gmail messages stay untouched")

    # Small screens use a separate reader view with a Back control.
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{BASE_URL}/app")
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    page.locator("[data-thread-row] [data-reader-link]").first.click()
    page.wait_for_url(re.compile(r"/app/threads/"))
    expect(page.get_by_role("link", name=re.compile("^Back"))).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth") <= 390

    assert not problems, problems
