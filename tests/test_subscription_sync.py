"""Subscription sync: new -> queued, known -> skipped, retention applied."""
from contextlib import contextmanager

import pytest

from app import crud, scheduler
from app.downloader import SourceEntry, SourceInfo


@pytest.fixture()
def patched(db, monkeypatch):
    """Wire scheduler internals to the in-memory db and stub side effects."""

    @contextmanager
    def fake_scope():
        yield db  # do not close/commit-teardown the shared test session

    monkeypatch.setattr(scheduler, "session_scope", fake_scope)
    monkeypatch.setattr(scheduler.worker, "storage_ok", lambda: True)
    monkeypatch.setattr(scheduler.worker, "wake", lambda: None)
    monkeypatch.setattr(scheduler.feed, "write_feed_file", lambda *a, **k: None)
    return monkeypatch


def _set_source(monkeypatch, entries):
    info = SourceInfo(kind="podcast", is_series=True, entries=entries)
    monkeypatch.setattr(scheduler.downloader, "analyze", lambda url, lang="de": info)


def test_new_entries_are_queued(db, patched):
    sub = crud.create_subscription(db, 0, "https://feed/x", "podcast")
    _set_source(patched, [
        SourceEntry("https://feed/x/1", "Folge 1"),
        SourceEntry("https://feed/x/2", "Folge 2"),
    ])

    scheduler.sync_subscription(sub.id)

    items = crud.list_items(db, 0)
    assert len(items) == 2
    assert all(i.status == "queued" for i in items)
    # each item got a job
    for item in items:
        assert len(item.jobs) == 1


def test_known_entries_are_skipped(db, patched):
    sub = crud.create_subscription(db, 0, "https://feed/x", "podcast")
    # pre-existing item
    crud.create_item(db, 0, "https://feed/x/1", "Folge 1", subscription_id=sub.id)

    _set_source(patched, [
        SourceEntry("https://feed/x/1", "Folge 1"),   # known
        SourceEntry("https://feed/x/2", "Folge 2"),   # new
    ])

    scheduler.sync_subscription(sub.id)

    items = crud.list_items(db, 0)
    assert len(items) == 2  # only one new added


def test_retention_applied_on_sync(db, patched):
    crud.update_settings(db, max_playlist_length=2)

    sub = crud.create_subscription(db, 0, "https://feed/x", "podcast")
    _set_source(patched, [
        SourceEntry(f"https://feed/x/{i}", f"Folge {i}") for i in range(1, 6)
    ])
    scheduler.sync_subscription(sub.id)

    # Mark all as done so retention counts them.
    for item in crud.list_items(db, 0):
        crud.update_item(db, item.id, status="done", filename=f"{item.sort_index}.mp3")

    # All 5 episodes belong to the same subscription, i.e. one single
    # "block" eviction unit (see crud._oldest_first_eviction_units --
    # retention always keeps or moves a whole playlist, never splits it).
    # With a limit of 2, the entire block is evicted rather than trimmed
    # down to 2 episodes; partial per-item retention for standalone items
    # is covered separately in test_retention.py.
    removed = crud.apply_retention(db, 0)
    assert len(removed) == 5
    assert len(crud.list_done_items(db, 0)) == 0
