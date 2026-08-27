"""Variant B: get the whole library onto an SD card as folders 0..8.

Files are named "01 Titel.mp3" etc. Two ways in:
- export_to_sd(): copy directly to a card mounted on the server's filesystem
  (e.g. a reader plugged into the machine running Docker), then sync + eject hint.
- build_export_zip(): stream a ZIP with the same folder/file layout, for the
  browser-native path where the SD card is in the reader of whatever device
  the browser runs on (no server-side filesystem access to the card needed).
"""
import logging
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Iterator, NamedTuple

from sqlalchemy.orm import Session

from . import config, crud, downloader, i18n

logger = logging.getLogger("hoerbox.sd_export")


class SDExportError(Exception):
    """Raised with a user-friendly, single-action message."""


class ExportFile(NamedTuple):
    channel_id: int
    dest_name: str  # e.g. "01 Titel.mp3"
    src_path: Path


def _iter_export_files(db: Session) -> Iterator[ExportFile]:
    """Yield every done item as (channel_id, dest_name, src_path), in the
    same "NN Titel.mp3" naming used on the card, across all 9 channels.
    """
    for channel in crud.list_channels(db):
        if not channel.active:
            # Deaktivierte Knöpfe sollen auf der Karte leer bleiben -- die
            # zugehörigen Ordner werden trotzdem angelegt/geleert (siehe
            # export_to_sd()), nur eben nie neu befüllt.
            continue
        items = crud.list_done_items(db, channel.id)
        for pos, item in enumerate(items, start=1):
            if not item.filename:
                continue
            src = config.AUDIO_DIR / str(channel.id) / item.filename
            if not src.exists():
                continue
            slug = downloader.sanitize_filename(item.title).replace("_", " ")
            dest_name = f"{pos:02d} {slug}.mp3"
            yield ExportFile(channel.id, dest_name, src)


def _check_target(target: Path, lang: str) -> None:
    if not target.exists():
        raise SDExportError(i18n.t("sdexport.no_card", lang))
    if not target.is_dir():
        raise SDExportError(i18n.t("sdexport.bad_path", lang))
    if not os.access(str(target), os.W_OK):
        raise SDExportError(i18n.t("sdexport.not_writable", lang))


def export_to_sd(db: Session, target_path: str) -> dict:
    """Copy all done items into folders 0..8 on the target card.

    Returns a summary dict. Raises SDExportError with a single action on failure.
    """
    lang = crud.get_settings(db).language
    target = Path(target_path)
    _check_target(target, lang)

    for channel in crud.list_channels(db):
        folder = target / str(channel.id)
        folder.mkdir(parents=True, exist_ok=True)
        # clear existing mp3s so removed items disappear from the card
        for old in folder.glob("*.mp3"):
            try:
                old.unlink()
            except OSError:
                pass

    total_files = 0
    for entry in _iter_export_files(db):
        folder = target / str(entry.channel_id)
        shutil.copy2(entry.src_path, folder / entry.dest_name)
        total_files += 1

    _sync()

    return {
        "ok": True,
        "files": total_files,
        "message": i18n.t("sdexport.done", lang, count=total_files),
    }


def build_export_zip(db: Session, dest_zip_path: Path) -> int:
    """Write a ZIP with the same folders/filenames as export_to_sd() to
    *dest_zip_path* (a real file on disk, not in memory — the library can
    run into the hundreds of MB, more than sensible to hold in RAM on a
    Raspberry Pi). MP3s are already compressed, so entries are stored
    uncompressed (ZIP_STORED) to skip pointless CPU work.

    Returns the number of files written.
    """
    total_files = 0
    with zipfile.ZipFile(dest_zip_path, "w", zipfile.ZIP_STORED) as zf:
        for entry in _iter_export_files(db):
            zf.write(entry.src_path, arcname=f"{entry.channel_id}/{entry.dest_name}")
            total_files += 1
    return total_files


def _sync() -> None:
    try:
        subprocess.run(["sync"], check=False, timeout=60)
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        logger.warning("sync failed: %s", exc)
