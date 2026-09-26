from mercury.inbox.reader import build_thread_view
from mercury.integrations.fake_gmail import FIXTURE_THREADS


def test_html_reader_outputs_text_without_active_remote_content():
    fixture = next(item for item in FIXTURE_THREADS if item.id == "fixture-bank-html")
    view = build_thread_view(fixture, max_bytes=100_000, max_messages=20)
    text = view.messages[0].text
    assert "Statement ready" in text
    assert "<script" not in text
    assert "https://tracker.invalid" not in text
    assert "hx-get" not in text
    assert "PERSISTENCE_SENTINEL_BODY_ONLY" not in text


def test_reader_is_bounded_and_skips_drafts():
    fixture = FIXTURE_THREADS[0]
    view = build_thread_view(fixture, max_bytes=12, max_messages=1)
    assert len(view.messages) == 1
    assert len(view.messages[0].text.encode()) <= 12
    assert view.messages[0].truncated is True


def test_malformed_large_fixture_is_bounded():
    fixture = next(item for item in FIXTURE_THREADS if item.id == "fixture-malformed-large")
    view = build_thread_view(fixture, max_bytes=128, max_messages=20)
    assert len(view.messages[0].text.encode()) <= 128
    assert view.messages[0].truncated is True
