"""POST /api/add -- overflow beyond max_playlist_length moves to the
Bibliothek (never deletes), for single-item adds as well as whole
playlists, and always as a whole subscription block, never split."""
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import crud
from app.database import get_db
from app.downloader import SourceEntry, SourceInfo
from app.routers import api


def _client(db, monkeypatch, info):
    monkeypatch.setattr(api.downloader, "analyze", lambda url, lang="de": info)
    monkeypatch.setattr(api.worker, "storage_ok", lambda: True)
    monkeypatch.setattr(api.worker, "wake", lambda: None)
    test_app = FastAPI()
    test_app.include_router(api.router)
    test_app.dependency_overrides[get_db] = lambda: db
    return TestClient(test_app)


def _add_done(db, channel_id, url, title, subscription_id=None):
    item = crud.create_item(db, channel_id, url, title, subscription_id=subscription_id)
    crud.update_item(db, item.id, status="done", filename=f"{item.sort_index}.mp3",
                      duration_seconds=60, file_size_bytes=1000)
    time.sleep(0.001)  # distinct created_at ordering, oldest-first eviction
    return item


def test_single_item_add_needs_confirmation_when_over_limit(db, monkeypatch):
    crud.update_settings(db, max_playlist_length=1)
    _add_done(db, 0, "https://x/old", "Alt")

    info = SourceInfo(kind="single", is_series=False,
                       entries=[SourceEntry("https://x/new", "Neu")])
    client = _client(db, monkeypatch, info)

    resp = client.post("/api/add", json={"url": "https://x/new", "channel": 0})
    body = resp.json()

    assert body["needs_confirmation"] is True
    # nothing added or moved yet -- just asked
    assert crud.item_exists(db, 0, "https://x/new") is None


def test_confirmed_single_item_add_moves_oldest_to_library(db, monkeypatch):
    crud.update_settings(db, max_playlist_length=1)
    old = _add_done(db, 0, "https://x/old", "Alt")

    info = SourceInfo(kind="single", is_series=False,
                       entries=[SourceEntry("https://x/new", "Neu")])
    client = _client(db, monkeypatch, info)

    resp = client.post("/api/add", json={
        "url": "https://x/new", "channel": 0, "confirm_evict": True,
    })
    assert resp.json()["ok"] is True

    # the new item was created ...
    assert crud.item_exists(db, 0, "https://x/new") is not None
    # ... the old one moved to the Bibliothek, not deleted
    moved = crud.get_item(db, old.id)
    assert moved is not None
    assert moved.in_library == 1


def test_playlist_add_moves_whole_block_not_split(db, monkeypatch):
    crud.update_settings(db, max_playlist_length=2)
    sub = crud.create_subscription(db, 0, "https://old-show/feed", "podcast", title="Alte Serie")
    old_a = _add_done(db, 0, "https://old-show/1", "Alte Serie Folge 1", subscription_id=sub.id)
    old_b = _add_done(db, 0, "https://old-show/2", "Alte Serie Folge 2", subscription_id=sub.id)

    info = SourceInfo(kind="podcast", is_series=True, list_title="Neue Serie",
                       entries=[SourceEntry("https://new-show/1", "Neue Serie Folge 1")])
    client = _client(db, monkeypatch, info)

    resp = client.post("/api/add", json={"url": "https://new-show/feed", "channel": 0})
    assert resp.json()["needs_confirmation"] is True

    resp = client.post("/api/add", json={
        "url": "https://new-show/feed", "channel": 0, "confirm_evict": True,
    })
    assert resp.json()["ok"] is True

    # the whole old block moved together, not just one of its two episodes
    for old_item in (old_a, old_b):
        moved = crud.get_item(db, old_item.id)
        assert moved.in_library == 1


def test_no_confirmation_needed_when_under_limit(db, monkeypatch):
    crud.update_settings(db, max_playlist_length=10)

    info = SourceInfo(kind="single", is_series=False,
                       entries=[SourceEntry("https://x/new", "Neu")])
    client = _client(db, monkeypatch, info)

    resp = client.post("/api/add", json={"url": "https://x/new", "channel": 0})
    body = resp.json()

    assert "needs_confirmation" not in body or not body["needs_confirmation"]
    assert crud.item_exists(db, 0, "https://x/new") is not None
