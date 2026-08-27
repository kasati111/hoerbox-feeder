"""Bibliothek (library) business logic: parking items/blocks off the active
channels and reassigning them to a (possibly different) channel later,
including moving the underlying audio file between channel folders.

Kept separate from crud.py (pure DB ops) and worker.py (the download loop).
"""
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from . import config, crud, feed

logger = logging.getLogger("hoerbox.library")

_IN_FLIGHT_STATUSES = ("queued", "downloading")


class LibraryError(Exception):
    """Raised with a user-friendly, single-action message."""


def _guard_in_flight(item) -> None:
    if item.status in _IN_FLIGHT_STATUSES:
        raise LibraryError("Dieser Titel wird gerade geladen – bitte kurz warten.")


def _channel_dir(channel_id: int) -> Path:
    return config.AUDIO_DIR / str(channel_id)


def _unique_filename(dest_dir: Path, filename: str) -> str:
    candidate = dest_dir / filename
    if not candidate.exists():
        return filename
    stem, suffix = Path(filename).stem, Path(filename).suffix
    n = 2
    while (dest_dir / f"{stem}_{n}{suffix}").exists():
        n += 1
    return f"{stem}_{n}{suffix}"


def _move_file(item, target_channel_id: int) -> Optional[str]:
    """Move item's audio file into the target channel's folder.

    Returns the (possibly renamed, for collision-avoidance) new filename, or
    None if there was no file to move (item never finished downloading, or
    the file was already removed out-of-band e.g. via Belegung).
    """
    if not item.filename:
        return None
    src = _channel_dir(item.channel_id) / item.filename
    if not src.exists():
        logger.warning("library: source file missing, skipping move: %s", src)
        return None
    dest_dir = _channel_dir(target_channel_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    new_filename = _unique_filename(dest_dir, item.filename)
    shutil.move(str(src), str(dest_dir / new_filename))
    return new_filename


def park_item(db: Session, item_id: int, base_url: str):
    item = crud.get_item(db, item_id)
    if item is None:
        raise LibraryError("Eintrag nicht gefunden.")
    _guard_in_flight(item)
    crud.update_item(db, item_id, in_library=1, library_added_at=datetime.utcnow())
    try:
        feed.write_feed_file(db, item.channel_id, base_url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("feed write failed: %s", exc)
    return crud.get_item(db, item_id)


def _guard_channel_active(target_channel_id: int, channel) -> None:
    if channel is None:
        raise LibraryError("Diesen Knopf gibt es nicht.")
    if not channel.active:
        raise LibraryError("Dieser Knopf ist deaktiviert.")


def reassign_item(db: Session, item_id: int, target_channel_id: int, base_url: str):
    item = crud.get_item(db, item_id)
    if item is None:
        raise LibraryError("Eintrag nicht gefunden.")
    _guard_channel_active(target_channel_id, crud.get_channel(db, target_channel_id))
    _guard_in_flight(item)

    old_channel_id = item.channel_id
    new_filename = item.filename
    if target_channel_id != old_channel_id:
        moved = _move_file(item, target_channel_id)
        if moved is not None:
            new_filename = moved

    crud.update_item(
        db, item_id,
        channel_id=target_channel_id,
        filename=new_filename,
        sort_index=crud.next_sort_index(db, target_channel_id),
        in_library=0,
    )

    for ch_id in {old_channel_id, target_channel_id}:
        try:
            feed.write_feed_file(db, ch_id, base_url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("feed write failed for channel %s: %s", ch_id, exc)

    return crud.get_item(db, item_id)


def park_block(db: Session, subscription_id: int, base_url: str) -> int:
    items = crud.list_items_by_subscription(db, subscription_id)
    count = 0
    for item in items:
        if item.status in _IN_FLIGHT_STATUSES:
            continue
        park_item(db, item.id, base_url)
        count += 1
    crud.set_subscription_enabled_by_id(db, subscription_id, False)
    return count


def park_channel(db: Session, channel_id: int, base_url: str) -> int:
    items = crud.list_active_items(db, channel_id)
    count = 0
    for item in items:
        if item.status in _IN_FLIGHT_STATUSES:
            continue
        park_item(db, item.id, base_url)
        count += 1
    return count


def reassign_block(db: Session, subscription_id: int, target_channel_id: int, base_url: str) -> int:
    _guard_channel_active(target_channel_id, crud.get_channel(db, target_channel_id))
    items = crud.list_items_by_subscription(db, subscription_id)
    count = 0
    for item in items:
        if item.status in _IN_FLIGHT_STATUSES:
            continue
        reassign_item(db, item.id, target_channel_id, base_url)
        count += 1
    crud.update_subscription(db, subscription_id, channel_id=target_channel_id, enabled=1)
    return count
