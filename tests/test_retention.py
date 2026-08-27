"""Retention keeps exactly N episodes; oldest are removed."""
import time

from app import crud


def _add_done(db, channel_id, url, title):
    item = crud.create_item(db, channel_id, url, title)
    crud.update_item(db, item.id, status="done",
                     filename=f"{item.sort_index}.mp3",
                     duration_seconds=60, file_size_bytes=1000)
    return item


def test_retention_keeps_n_newest(db):
    crud.update_settings(db, max_playlist_length=3)

    items = []
    for i in range(1, 7):
        items.append(_add_done(db, 0, f"https://x/{i}", f"Folge {i}"))
        time.sleep(0.01)  # ensure distinct created_at ordering

    removed = crud.apply_retention(db, 0)

    remaining = crud.list_done_items(db, 0)
    assert len(remaining) == 3
    assert len(removed) == 3
    # newest three (4,5,6) should remain
    remaining_titles = {i.title for i in remaining}
    assert remaining_titles == {"Folge 4", "Folge 5", "Folge 6"}


def test_retention_noop_when_under_limit(db):
    crud.update_settings(db, max_playlist_length=20)

    for i in range(1, 4):
        _add_done(db, 0, f"https://x/{i}", f"Folge {i}")

    removed = crud.apply_retention(db, 0)
    assert removed == []
    assert len(crud.list_done_items(db, 0)) == 3


def test_retention_only_counts_done(db):
    crud.update_settings(db, max_playlist_length=2)

    _add_done(db, 0, "https://x/1", "Fertig 1")
    _add_done(db, 0, "https://x/2", "Fertig 2")
    _add_done(db, 0, "https://x/3", "Fertig 3")
    # queued items should not be deleted by retention
    crud.create_item(db, 0, "https://x/q", "Wartet")

    crud.apply_retention(db, 0)
    assert len(crud.list_done_items(db, 0)) == 2
    # the queued item is still present
    all_items = crud.list_items(db, 0)
    assert any(i.status == "queued" for i in all_items)
