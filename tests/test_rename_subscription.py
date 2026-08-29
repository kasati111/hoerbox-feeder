"""POST /api/subscription/{id}/rename -- rename a playlist/subscription."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import crud
from app.database import get_db
from app.routers import api


def _client(db):
    test_app = FastAPI()
    test_app.include_router(api.router)
    test_app.dependency_overrides[get_db] = lambda: db
    return TestClient(test_app)


def test_rename_updates_title(db):
    sub = crud.create_subscription(db, 0, "https://feed/x", "podcast", title="Alt")

    with _client(db) as client:
        resp = client.post(f"/api/subscription/{sub.id}/rename", json={"title": "Neu"})

    body = resp.json()
    assert resp.status_code == 200
    assert body["ok"] is True
    assert body["title"] == "Neu"
    assert crud.get_subscription(db, sub.id).title == "Neu"


def test_rename_strips_whitespace(db):
    sub = crud.create_subscription(db, 0, "https://feed/x", "podcast", title="Alt")

    with _client(db) as client:
        resp = client.post(f"/api/subscription/{sub.id}/rename", json={"title": "  Neu  "})

    assert resp.json()["title"] == "Neu"
    assert crud.get_subscription(db, sub.id).title == "Neu"


def test_rename_rejects_empty_title(db):
    sub = crud.create_subscription(db, 0, "https://feed/x", "podcast", title="Alt")

    with _client(db) as client:
        resp = client.post(f"/api/subscription/{sub.id}/rename", json={"title": "   "})

    assert resp.json()["ok"] is False
    # Unchanged -- a rejected rename must not clobber the existing title.
    assert crud.get_subscription(db, sub.id).title == "Alt"


def test_rename_unknown_subscription_is_404(db):
    with _client(db) as client:
        resp = client.post("/api/subscription/999/rename", json={"title": "Neu"})

    assert resp.status_code == 404
