from __future__ import annotations

from urllib.parse import quote, urlencode

GMAIL_ORIGIN = "https://mail.google.com"


def gmail_thread_url(mailbox: str, thread_id: str) -> str:
    return f"{GMAIL_ORIGIN}/mail/u/{quote(mailbox, safe='')}#all/{quote(thread_id, safe='')}"


def gmail_message_search_url(mailbox: str, internet_message_id: str) -> str:
    query = urlencode({"authuser": mailbox})
    search = quote(f"rfc822msgid:{internet_message_id}", safe="")
    return f"{GMAIL_ORIGIN}/mail/u/?{query}#search/{search}"
