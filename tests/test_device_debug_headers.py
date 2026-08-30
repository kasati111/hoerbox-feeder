"""Reverse-engineering aids added to feed/audio logging: conditional-GET
headers on feed polls, and the retry-gap tracker on repeated 404s."""
from datetime import datetime, timedelta

from app.routers import feed_routes, media


class _FakeRequest:
    def __init__(self, headers):
        self.headers = headers


def test_conditional_headers_present():
    req = _FakeRequest({"if-modified-since": "Sun, 30 Aug 2026 09:00:00 GMT",
                         "if-none-match": '"abc123"'})
    result = feed_routes._conditional_headers(req)
    assert result == 'if_modified_since=Sun, 30 Aug 2026 09:00:00 GMT if_none_match="abc123"'


def test_conditional_headers_absent():
    req = _FakeRequest({})
    assert feed_routes._conditional_headers(req) == "if_modified_since=- if_none_match=-"


def test_retry_gap_first_seen():
    media._last_not_found_at.clear()
    assert media._retry_gap(9, "never-seen.mp3") == "since_last=first"


def test_retry_gap_seconds():
    media._last_not_found_at.clear()
    media._last_not_found_at[(1, "x.mp3")] = datetime.utcnow() - timedelta(seconds=42)
    assert media._retry_gap(1, "x.mp3") == "since_last=42s"


def test_retry_gap_minutes():
    media._last_not_found_at.clear()
    media._last_not_found_at[(1, "x.mp3")] = datetime.utcnow() - timedelta(minutes=3, seconds=5)
    assert media._retry_gap(1, "x.mp3") == "since_last=3m5s"


def test_retry_gap_hours():
    media._last_not_found_at.clear()
    media._last_not_found_at[(1, "x.mp3")] = datetime.utcnow() - timedelta(hours=2, minutes=10)
    assert media._retry_gap(1, "x.mp3") == "since_last=2h10m"


def test_retry_gap_updates_last_seen():
    media._last_not_found_at.clear()
    media._retry_gap(1, "x.mp3")
    assert (1, "x.mp3") in media._last_not_found_at
