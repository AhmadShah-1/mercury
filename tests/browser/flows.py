"""Shared steps for browser flows against a running synthetic Mercury server."""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

BASE_URL = os.environ.get("MERCURY_BROWSER_BASE_URL", "").rstrip("/")

if BASE_URL and urlparse(BASE_URL).hostname not in {"localhost", "127.0.0.1", "::1"}:
    raise RuntimeError("Browser flows only run against a loopback Mercury server")


def login(page, expect):
    page.goto(f"{BASE_URL}/")
    expect(page.get_by_role("heading", level=1)).to_contain_text("calm, organized")
    page.goto(f"{BASE_URL}/auth/dev")
    page.get_by_role("button", name=re.compile("synthetic workspace", re.I)).click()
    page.wait_for_url(re.compile(r"/app"))


def disconnect_if_connected(page, expect):
    """Start from a clean mailbox: disconnect through the confirmation dialog if connected."""
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
        login(page, expect)


def connect_synthetic_mailbox(page, expect):
    page.get_by_role("link", name="Connect Gmail").click()
    expect(page.get_by_role("heading", level=1)).to_contain_text("exactly what Mercury does")
    expect(page.locator("body")).to_contain_text("What Mercury never does")
    page.get_by_label(re.compile("I understand how Mercury processes")).check()
    page.get_by_label(re.compile("Allow selected message text")).check()
    page.get_by_role("button", name=re.compile("Connect synthetic mailbox")).click()
    page.wait_for_url(re.compile(r"/app$"))
    expect(page.locator("#toast-stack")).to_contain_text("Synthetic mailbox connected")
