"""End-to-end browser flow against a running synthetic Mercury server.

Skipped unless MERCURY_BROWSER_BASE_URL points at a loopback server started with the synthetic
profile (AUTH_MODE=dev, MAIL_MODE=fake, AI_PROVIDER=fake). The flow resets the demo user's
mailbox by disconnecting it first, so never point it at a server holding data you want to keep.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import pytest

BASE_URL = os.environ.get("MERCURY_BROWSER_BASE_URL", "").rstrip("/")

pytestmark = [
    pytest.mark.skipif(not BASE_URL, reason="set MERCURY_BROWSER_BASE_URL to run browser flows"),
    # Playwright's sync API uses a local socketpair for its event loop; Chromium itself only
    # talks to the loopback server below.
    pytest.mark.enable_socket,
]

if BASE_URL and urlparse(BASE_URL).hostname not in {"localhost", "127.0.0.1", "::1"}:
    raise RuntimeError("Browser flows only run against a loopback Mercury server")

playwright_api = pytest.importorskip("playwright.sync_api")
expect = playwright_api.expect


@pytest.fixture
def watched_page():
    with playwright_api.sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        problems: list[str] = []

        def on_console(message):
            text = message.text
            if message.type == "error" or "Content Security Policy" in text or "Refused to" in text:
                problems.append(f"{message.type}: {text}")

        page.on("console", on_console)
        page.on("pageerror", lambda error: problems.append(f"pageerror: {error}"))
        page.on(
            "request",
            lambda request: problems.append(f"external request: {request.url}")
            if not request.url.startswith((BASE_URL, "data:", "about:"))
            else None,
        )
        yield page, problems
        context.close()
        browser.close()


def _login(page):
    page.goto(f"{BASE_URL}/")
    expect(page.get_by_role("heading", level=1)).to_contain_text("calm, organized")
    page.goto(f"{BASE_URL}/auth/dev")
    page.get_by_role("button", name=re.compile("synthetic workspace", re.I)).click()
    page.wait_for_url(re.compile(r"/app"))


def test_synthetic_demo_flow(watched_page):
    page, problems = watched_page
    _login(page)

    # Start from a clean mailbox: disconnect through the confirmation dialog if connected.
    page.goto(f"{BASE_URL}/settings")
    disconnect = page.get_by_role("button", name="Disconnect and remove mailbox data")
    if disconnect.count():
        disconnect.click()
        dialog = page.locator("#confirm-dialog")
        expect(dialog).to_be_visible()
        expect(dialog).to_contain_text("Gmail messages are not changed")
        dialog.get_by_role("button", name="Disconnect and remove data").click()
        page.wait_for_url(f"{BASE_URL}/")
        expect(page.locator("#toast-stack")).to_contain_text("Gmail was disconnected")
        _login(page)

    # Connect with the explicit disclosure; the required box is enforced server-side.
    page.get_by_role("link", name="Connect Gmail").click()
    expect(page.get_by_role("heading", level=1)).to_contain_text("exactly what Mercury does")
    expect(page.locator("body")).to_contain_text("What Mercury never does")
    page.get_by_label(re.compile("I understand how Mercury processes")).check()
    page.get_by_label(re.compile("Allow selected message text")).check()
    page.get_by_role("button", name=re.compile("Connect synthetic mailbox")).click()
    page.wait_for_url(re.compile(r"/app$"))
    expect(page.locator("#toast-stack")).to_contain_text("Synthetic mailbox connected")

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
