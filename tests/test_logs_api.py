"""GET /api/logs -- polled by the /logs page to auto-refresh; newest line
first, capped to the requested tail."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config
from app.routers import api


def _client():
    test_app = FastAPI()
    test_app.include_router(api.router)
    return TestClient(test_app)


def test_returns_newest_line_first(tmp_path, monkeypatch):
    log_file = tmp_path / "app.log"
    log_file.write_text("line1\nline2\nline3\n", encoding="utf-8")
    monkeypatch.setattr(config, "LOG_PATH", log_file)

    resp = _client().get("/api/logs")

    assert resp.json()["content"] == "line3\nline2\nline1"


def test_caps_to_requested_tail(tmp_path, monkeypatch):
    # lines is clamped to a floor of 10 (see logs_content()), so use more
    # than that to actually exercise the cap rather than the floor.
    log_file = tmp_path / "app.log"
    log_file.write_text("\n".join(f"line{i}" for i in range(1, 16)), encoding="utf-8")
    monkeypatch.setattr(config, "LOG_PATH", log_file)

    resp = _client().get("/api/logs?lines=10")

    assert resp.json()["content"] == "\n".join(f"line{i}" for i in range(15, 5, -1))


def test_missing_log_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_PATH", tmp_path / "does-not-exist.log")

    resp = _client().get("/api/logs")

    assert resp.json()["content"] == ""
