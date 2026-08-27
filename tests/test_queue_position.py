"""Tests for the queue-position feature (Warteposition)."""
import time

from app import crud


def _make_job(db, channel_id, url):
    item = crud.create_item(db, channel_id=channel_id, source_url=url, title=url)
    return crud.create_job(db, item.id)


def test_queue_position_increments(db):
    j1 = _make_job(db, 0, "http://example.com/a")
    time.sleep(0.01)
    j2 = _make_job(db, 0, "http://example.com/b")
    time.sleep(0.01)
    j3 = _make_job(db, 0, "http://example.com/c")

    assert crud.queue_position(db, j1) == 1
    assert crud.queue_position(db, j2) == 2
    assert crud.queue_position(db, j3) == 3


def test_queue_position_zero_when_not_queued(db):
    j1 = _make_job(db, 0, "http://example.com/a")
    crud.update_job(db, j1.id, status="running")
    db.refresh(j1)
    assert crud.queue_position(db, j1) == 0


def test_worker_busy(db):
    assert crud.worker_busy(db) is False
    j1 = _make_job(db, 0, "http://example.com/a")
    assert crud.worker_busy(db) is False
    crud.update_job(db, j1.id, status="running")
    assert crud.worker_busy(db) is True


def test_position_after_first_completes(db):
    j1 = _make_job(db, 0, "http://example.com/a")
    time.sleep(0.01)
    j2 = _make_job(db, 0, "http://example.com/b")
    # first one finishes -> j2 moves to front
    crud.update_job(db, j1.id, status="done")
    assert crud.queue_position(db, j2) == 1
