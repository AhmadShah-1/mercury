"""Browser flows drive an external loopback server and never touch the pytest database."""

from __future__ import annotations

import pytest

from tests.browser.flows import BASE_URL


@pytest.fixture(autouse=True)
def clean_database():
    """Override the suite-wide truncation fixture: these tests don't use the test database."""
    yield


@pytest.fixture
def watched_page():
    """A desktop page that records console errors, CSP violations, and non-local requests."""
    playwright_api = pytest.importorskip("playwright.sync_api")
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
