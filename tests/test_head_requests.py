"""HEAD /feed/{n}.xml and HEAD /audio/{kanal}/{filename} must succeed.

Regression test for a bug where a device/podcast client HEAD-probing a new
episode's feed entry or enclosure before GET-ing it got a plain 405 -- these
routes only declared GET, and (unlike older starlette) starlette 1.x does not
auto-add HEAD support for a GET-only route (see DEVELOPER.md §5.1/§5.8). That
made a newly-synced item silently fail to reach the device while everything
already downloaded earlier kept working, since only new episodes get probed.
"""
from app import config
from app.database import get_db
from app.routers import feed_routes, media
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client(db, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUDIO_DIR", tmp_path)
    channel_dir = tmp_path / "4"
    channel_dir.mkdir()
    (channel_dir / "episode.mp3").write_bytes(b"fake-mp3-bytes-for-testing")

    test_app = FastAPI()
    test_app.include_router(feed_routes.router)
    test_app.include_router(media.router)
    test_app.dependency_overrides[get_db] = lambda: db
    return TestClient(test_app)


def test_feed_head_has_no_body_but_matches_get_headers(db, tmp_path, monkeypatch):
    with _client(db, tmp_path, monkeypatch) as client:
        get_resp = client.get("/feed/4.xml")
        head_resp = client.head("/feed/4.xml")

    assert get_resp.status_code == 200
    assert head_resp.status_code == 200
    assert head_resp.content == b""
    assert head_resp.headers["content-length"] == get_resp.headers["content-length"]


def test_audio_head_has_no_body_but_matches_get_headers(db, tmp_path, monkeypatch):
    with _client(db, tmp_path, monkeypatch) as client:
        get_resp = client.get("/audio/4/episode.mp3")
        head_resp = client.head("/audio/4/episode.mp3")

    assert get_resp.status_code == 200
    assert head_resp.status_code == 200
    assert head_resp.content == b""
    assert head_resp.headers["content-length"] == get_resp.headers["content-length"]
    assert head_resp.headers["accept-ranges"] == "bytes"


def test_audio_head_for_missing_file_is_404_not_405(db, tmp_path, monkeypatch):
    with _client(db, tmp_path, monkeypatch) as client:
        resp = client.head("/audio/4/does-not-exist.mp3")

    assert resp.status_code == 404
