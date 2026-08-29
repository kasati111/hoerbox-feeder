"""Tests for large playlist limiting functionality."""
from unittest.mock import MagicMock

from app import config, crud, downloader
from app.routers.api import AddRequest, add_content


def test_large_playlist_limited(db, monkeypatch):
    """Large playlists should be limited to MAX_INITIAL_PLAYLIST_ITEMS."""
    # Create 100 fake entries (simulating a large YouTube playlist).
    fake_entries = [
        downloader.SourceEntry(url=f"https://example.com/video{i}", title=f"Video {i}")
        for i in range(100)
    ]

    fake_info = downloader.SourceInfo(
        kind="youtube_playlist",
        is_series=True,
        entries=fake_entries
    )

    # Mock downloader.analyze to return our fake large playlist.
    monkeypatch.setattr("app.routers.api.downloader.analyze", lambda url, lang="de": fake_info)

    # Mock worker and scheduler to avoid side effects.
    monkeypatch.setattr("app.routers.api.worker.storage_ok", lambda: True)
    monkeypatch.setattr("app.routers.api.worker.wake", lambda: None)
    monkeypatch.setattr("app.routers.api.refresh_jobs", lambda: None)

    # Mock get_db to return our test db.
    def override_get_db():
        yield db

    # Create a mock request with base_url.
    mock_request = MagicMock()
    mock_request.base_url = "http://localhost:8080/"

    # Call add_content with a fake URL and channel 0.
    payload = AddRequest(url="https://example.com/playlist", channel=0)
    result = add_content(payload, mock_request, db)

    # Assertions:
    # 1. Only MAX_INITIAL_PLAYLIST_ITEMS items should be created.
    items = crud.list_items(db, 0)
    assert len(items) == config.MAX_INITIAL_PLAYLIST_ITEMS

    # 2. A subscription should be created (it's a series).
    subs = crud.list_subscriptions(db, 0)
    assert len(subs) == 1

    # 3. The response should contain a helpful message.
    assert result["ok"] is True
    assert result["is_series"] is True
    assert result["count"] == config.MAX_INITIAL_PLAYLIST_ITEMS
    assert "100 Folgen" in result["message"]
    assert f"{config.MAX_INITIAL_PLAYLIST_ITEMS} werden jetzt geladen" in result["message"]


def test_small_playlist_not_limited(db, monkeypatch):
    """Small playlists should not be limited."""
    # Create 20 fake entries (small playlist).
    fake_entries = [
        downloader.SourceEntry(url=f"https://example.com/video{i}", title=f"Video {i}")
        for i in range(20)
    ]

    fake_info = downloader.SourceInfo(
        kind="youtube_playlist",
        is_series=True,
        entries=fake_entries
    )

    monkeypatch.setattr("app.routers.api.downloader.analyze", lambda url, lang="de": fake_info)
    monkeypatch.setattr("app.routers.api.worker.storage_ok", lambda: True)
    monkeypatch.setattr("app.routers.api.worker.wake", lambda: None)
    monkeypatch.setattr("app.routers.api.refresh_jobs", lambda: None)

    mock_request = MagicMock()
    mock_request.base_url = "http://localhost:8080/"

    payload = AddRequest(url="https://example.com/playlist", channel=0)
    result = add_content(payload, mock_request, db)

    # All 20 items should be created (no truncation).
    items = crud.list_items(db, 0)
    assert len(items) == 20

    # Series adds always name the count (see api.add_content's comment on
    # why: "Neue Folgen kommen automatisch" is shown for any series, not
    # just when the item-count cap actually kicks in) -- only the
    # truncation-specific wording ("hat X Folgen – die neuesten Y werden
    # geladen") is exclusive to the over-the-limit case, which this isn't.
    assert "20 Folgen werden jetzt geladen" in result["message"]
    assert "die neuesten" not in result["message"]  # no truncation warning


def test_single_video_not_limited(db, monkeypatch):
    """Single videos should work as before."""
    fake_info = downloader.SourceInfo(
        kind="single",
        is_series=False,
        entries=[downloader.SourceEntry(url="https://example.com/video", title="Single Video")]
    )

    monkeypatch.setattr("app.routers.api.downloader.analyze", lambda url, lang="de": fake_info)
    monkeypatch.setattr("app.routers.api.worker.storage_ok", lambda: True)
    monkeypatch.setattr("app.routers.api.worker.wake", lambda: None)

    mock_request = MagicMock()
    mock_request.base_url = "http://localhost:8080/"

    payload = AddRequest(url="https://example.com/video", channel=0)
    result = add_content(payload, mock_request, db)

    # 1 item created.
    items = crud.list_items(db, 0)
    assert len(items) == 1

    # No subscription (not a series).
    subs = crud.list_subscriptions(db, 0)
    assert len(subs) == 0

    # Standard message.
    assert result["is_series"] is False
