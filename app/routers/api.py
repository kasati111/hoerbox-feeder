"""JSON API for AJAX actions.

All user-facing strings are in everyday German — no technical jargon.
"""
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from .. import config, crud, downloader, feed, library, sd_export, worker
from ..database import get_db
from ..scheduler import refresh_jobs

logger = logging.getLogger("hoerbox.api")

router = APIRouter(prefix="/api")


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


class AddRequest(BaseModel):
    url: str
    channel: int
    confirm_evict: bool = False
    evict_mode: str = "library"  # "library" | "delete"


@router.post("/add")
def add_content(payload: AddRequest, request: Request, db: Session = Depends(get_db)):
    """Add a link to a channel. Series become auto-subscriptions."""
    channel = crud.get_channel(db, payload.channel)
    if channel is None:
        raise HTTPException(status_code=404, detail="Diesen Knopf gibt es nicht.")
    if not channel.active:
        raise HTTPException(status_code=400, detail="Dieser Knopf ist deaktiviert.")

    url = payload.url.strip()
    if not url:
        return {"ok": False, "message": "Bitte zuerst einen Link einfügen.",
                "action": "Link einfügen"}

    # Storage guard.
    if not worker.storage_ok():
        tidy = worker.channel_with_most_items(db)
        tidy_name = crud.get_channel(db, tidy).name
        return {
            "ok": False,
            "message": f"Kein Platz mehr. Räume den Kanal „{tidy_name}“ auf.",
            "action": "Aufräumen",
        }

    try:
        info = downloader.analyze(url)
    except Exception as exc:  # noqa: BLE001
        logger.error("analyze failed url=%s error=%s", url, exc)
        return {
            "ok": False,
            "message": "Der Link ließ sich nicht öffnen.",
            "action": "Nochmal versuchen",
        }

    job_ids = []
    created_items = 0
    total_entries = len(info.entries)

    # Limit initial items for large playlists to prevent request timeouts and wasted downloads.
    # Subscriptions will automatically fetch new entries later.
    limit = min(total_entries, crud.get_settings(db).max_items_per_list)
    entries_to_process = info.entries[:limit]

    # Series -> create an auto-subscription (default on) *before* creating the
    # initial batch of items, and tag each item with its subscription_id.
    # Otherwise the channel page's block-grouping (by subscription_id) would
    # never group a freshly-added playlist's own items — only episodes synced
    # in later would form a block, splitting one show into two groups.
    is_series = info.is_series
    sub_id = None

    # Whole-playlist adds may need to make room under the global "maximale
    # Playlistlänge" setting. Never evict silently here (unlike the automatic
    # background sync in scheduler.py) — ask first, since a live user is
    # present; confirm_evict=True (a resubmission of this same request)
    # means they already said yes.
    if is_series:
        new_count = sum(
            1 for e in entries_to_process
            if crud.item_exists(db, payload.channel, e.url) is None
        )
        if new_count > 0:
            plan = crud.plan_retention_eviction(db, payload.channel, new_count)
            if plan and not payload.confirm_evict:
                titles = []
                for unit in plan:
                    if unit["kind"] == "block":
                        sub = crud.get_subscription(db, unit["subscription_id"])
                        first_item = crud.get_item(db, unit["item_ids"][0])
                        titles.append(sub.title if sub and sub.title else first_item.title)
                    else:
                        titles.append(crud.get_item(db, unit["item_ids"][0]).title)
                names = ", ".join(f"„{t}“" for t in titles)
                return {
                    "ok": True,
                    "needs_confirmation": True,
                    "message": f"Um Platz zu machen, ist kein Platz mehr für: {names}.",
                }
            if plan and payload.confirm_evict:
                base_url = _base_url(request)
                for unit in plan:
                    try:
                        if payload.evict_mode == "delete":
                            if unit["kind"] == "block":
                                _delete_subscription_and_files(db, unit["subscription_id"], base_url)
                            else:
                                _delete_item_and_file(db, unit["item_ids"][0], base_url)
                        elif unit["kind"] == "block":
                            library.park_block(db, unit["subscription_id"], base_url)
                        else:
                            library.park_item(db, unit["item_ids"][0], base_url)
                    except library.LibraryError as exc:
                        logger.warning("eviction action failed: %s", exc)

        sub = crud.create_subscription(db, payload.channel, url, info.kind, title=info.list_title)
        sub_id = sub.id

    for entry in entries_to_process:
        item = crud.create_item(db, payload.channel, entry.url, entry.title, subscription_id=sub_id)
        if item is not None:
            job = crud.create_job(db, item.id)
            job_ids.append(job.id)
            created_items += 1

    if is_series:
        refresh_jobs()

    worker.wake()

    if created_items == 0:
        return {
            "ok": True,
            "duplicate": True,
            "message": "Das ist auf diesem Knopf schon vorhanden.",
            "job_ids": [],
            "is_series": is_series,
        }

    # Build user-friendly message for large playlists.
    # Always say so when a pasted link turned out to be a whole series/
    # playlist, not just when the item-count cap kicks in — a plain video
    # link that happens to carry a YouTube "&list=..." parameter (which
    # copying a link while browsing inside a playlist adds automatically)
    # silently expands into every episode otherwise, with nothing telling
    # the user why a "single link" produced two dozen jobs. Name it
    # explicitly too (not just "a series") — otherwise a stuck/backing-off
    # batch is just an anonymous number with no way to tell what it is
    # without opening the channel page.
    series_title = None
    if is_series:
        # Prefer the playlist's own title; fall back to the first entry that
        # actually has one rather than just entries_to_process[0] — some
        # extractors leave individual entries title-less (they show up later
        # as "Ohne Titel"), and picking blindly at index 0 meant an add whose
        # very first episode happened to lack a title fell through to no
        # title at all, even though later episodes had perfectly good ones.
        series_title = info.list_title or next(
            (e.title for e in entries_to_process if e.title), None
        )

    message = "Wird vorbereitet …"
    if is_series:
        label = f"„{series_title}“ ({channel.name})" if series_title else "Die Liste"
        if total_entries > limit:
            message = (f"{label} hat {total_entries} Folgen – "
                       f"die neuesten {created_items} werden jetzt geladen. "
                       f"Neue Folgen kommen automatisch.")
        else:
            message = (f"{label}: {created_items} Folgen werden jetzt geladen. "
                       f"Neue Folgen kommen automatisch.")

    return {
        "ok": True,
        "message": message,
        "series_title": series_title,
        "job_ids": job_ids,
        "is_series": is_series,
        "count": created_items,
    }


@router.get("/job/{job_id}/status")
def job_status(job_id: int, db: Session = Depends(get_db)):
    job = crud.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Auftrag nicht gefunden.")

    is_backoff = job.status == "queued" and bool(job.error_text)
    if is_backoff:
        # Backing off after a failed attempt (not exhausted yet, see
        # worker.handle_failure) is a fundamentally different situation from
        # "queued, waiting for its turn" — both used to report the same
        # generic "wird geladen" text here, which made a job silently
        # erroring for hours indistinguishable from one healthily in
        # progress, both to a human reading the single-item status line
        # and to pollJobs()'s batch aggregation on the client.
        text = job.error_text
    elif job.status == "queued":
        pos = crud.queue_position(db, job)
        if crud.worker_busy(db) or pos > 1:
            text = f"Wird geladen (aktuell in Warteposition {pos})"
        else:
            text = "Wird vorbereitet …"
    elif job.status == "running":
        pct = job.progress or 0
        if pct >= 90:
            # Download is finished; ffmpeg conversion is running.
            text = "Umwandlung zu Audio …"
        else:
            text = f"Wird geladen … {pct} %"
    elif job.status == "done":
        text = "Ab morgen früh auf dem Hörspieler 🎵"
    elif job.status == "cancelled":
        text = "Wurde abgebrochen"
    else:  # failed
        reason = job.error_text or "Unbekannter Grund"
        text = reason

    item = crud.get_item(db, job.item_id)

    return {
        "status": job.status,
        "progress": job.progress or 0,
        "text": text,
        "action": "Nochmal versuchen" if job.status == "failed" else None,
        "can_cancel": job.status in ("queued", "running"),
        "item_id": job.item_id,
        "is_backoff": is_backoff,
        "error_text": job.error_text,
        # Lets the client backfill a display title for a batch whose
        # seriesTitle wasn't available client-side (e.g. localStorage was
        # cleared, or the status page was opened fresh) — see pollJobs().
        "item_title": item.title if item else None,
    }


@router.delete("/job/{job_id}")
def cancel_job(job_id: int, db: Session = Depends(get_db)):
    """Cancel a queued or running job."""
    job = crud.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Auftrag nicht gefunden.")

    if job.status not in ("queued", "running"):
        return {"ok": False, "message": "Der Auftrag kann nicht mehr abgebrochen werden."}

    crud.update_job(db, job_id, status="cancelled", error_text="Abgebrochen")
    if job.item_id:
        crud.update_item(db, job.item_id, status="cancelled", error_text="Abgebrochen")

    return {"ok": True, "message": "Auftrag wurde abgebrochen."}


@router.post("/item/{item_id}/retry")
def retry_item(item_id: int, db: Session = Depends(get_db)):
    """Retry a failed or backing-off item right now, instead of waiting out
    the exponential backoff (or giving up after MAX_ATTEMPTS).
    """
    item = crud.get_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden.")
    if not item.error_text and item.status != "failed":
        return {"ok": False, "message": "Dieser Eintrag hat gerade kein Problem."}

    job = crud.latest_job_for_item(db, item_id) or crud.create_job(db, item_id)
    crud.update_job(
        db, job.id, status="queued", error_text=None,
        next_attempt_at=None, attempt_count=0, progress=0,
    )
    crud.update_item(db, item_id, status="queued", error_text=None)
    worker.wake()
    return {"ok": True, "message": "Wird erneut versucht.", "job_id": job.id}


@router.post("/item/{item_id}/find-alternative")
def find_alternative(item_id: int, db: Session = Depends(get_db)):
    """Search for a different source of the same title and retry with it.

    Reuses yt-dlp's native ytsearch1: pseudo-URL (the same mechanism already
    used for Spotify-sourced items in downloader._resolve_spotify, including
    its automatic YouTube-Music fallback on a miss) — no new download logic
    needed. Sets Item.alt_source_url rather than overwriting source_url, so
    a subscription-linked item keeps matching correctly on future syncs.
    """
    item = crud.get_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden.")
    if not item.error_text and item.status != "failed":
        return {"ok": False, "message": "Dieser Eintrag hat gerade kein Problem."}
    # Before giving up, try once to recover a real title (a flat playlist
    # listing, e.g. a SoundCloud set, can leave this "Ohne Titel" even
    # though the track has a perfectly good real one) — see
    # worker._ensure_real_title.
    title = worker._ensure_real_title(db, item)
    if downloader.is_placeholder_title(title):
        # No real title to search with — a blind search would just match an
        # arbitrary unrelated video (see search_candidates()'s docstring /
        # the session's "Gugus" bug). Point at the manual picker instead of
        # guessing.
        return {
            "ok": False,
            "message": "Kein Titel bekannt – bitte selbst nach einem Ersatz suchen.",
        }

    query = downloader.default_search_query(title, crud.item_search_context(db, item))
    crud.update_item(
        db, item_id, alt_source_url=f"ytsearch1:{query}",
        status="queued", error_text=None,
    )
    job = crud.latest_job_for_item(db, item_id) or crud.create_job(db, item_id)
    crud.update_job(
        db, job.id, status="queued", error_text=None,
        next_attempt_at=None, attempt_count=0, progress=0,
    )
    worker.wake()
    return {"ok": True, "message": "Suche nach anderer Quelle gestartet …", "job_id": job.id}


class SearchAlternativeRequest(BaseModel):
    query: str


@router.post("/item/{item_id}/search-alternative")
def search_alternative(item_id: int, payload: SearchAlternativeRequest, db: Session = Depends(get_db)):
    """Look up candidates for a user-chosen search term — a pure lookup, no
    DB mutation, no download. The human-verifiable counterpart to the blind
    ytsearch1: guess: shows title/uploader/duration/thumbnail so a parent can
    actually tell the candidates apart before committing to one."""
    if crud.get_item(db, item_id) is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden.")
    query = payload.query.strip()
    if not query:
        return {"ok": False, "message": "Bitte einen Suchbegriff eingeben.", "candidates": []}
    try:
        candidates = downloader.search_candidates(query)
    except Exception as exc:  # noqa: BLE001
        logger.warning("search_candidates failed for %r: %s", query, exc)
        return {"ok": False, "message": "Suche ist fehlgeschlagen.", "candidates": []}
    return {
        "ok": True,
        "candidates": [
            {
                "url": c.url, "title": c.title, "uploader": c.uploader,
                "duration_seconds": c.duration_seconds, "thumbnail_url": c.thumbnail_url,
            }
            for c in candidates
        ],
    }


class PickAlternativeRequest(BaseModel):
    url: str


@router.post("/item/{item_id}/pick-alternative")
def pick_alternative(item_id: int, payload: PickAlternativeRequest, db: Session = Depends(get_db)):
    """Commit a specific candidate the user picked in search-alternative's
    results as the item's alt_source_url. Unlike the blind ytsearch1:
    mechanisms, this stores the concrete resolved video URL (deterministic on
    retry) and marks it reviewed — a human saw the thumbnail/title/uploader
    and chose it, so it shouldn't keep showing the "please check this" hint.
    """
    item = crud.get_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden.")
    url = payload.url.strip()
    if not url:
        return {"ok": False, "message": "Keine Quelle ausgewählt."}

    crud.update_item(
        db, item_id, alt_source_url=url, alt_source_reviewed=1,
        status="queued", error_text=None,
    )
    job = crud.latest_job_for_item(db, item_id) or crud.create_job(db, item_id)
    crud.update_job(
        db, job.id, status="queued", error_text=None,
        next_attempt_at=None, attempt_count=0, progress=0,
    )
    worker.wake()
    return {"ok": True, "message": "Wird mit der ausgewählten Quelle geladen …", "job_id": job.id}


@router.post("/item/{item_id}/confirm-alternative")
def confirm_alternative(item_id: int, db: Session = Depends(get_db)):
    """Dismiss the "please check this" hint without touching the audio —
    for when a parent has listened/looked and the auto-substituted content
    is actually fine as-is."""
    item = crud.get_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden.")
    crud.update_item(db, item_id, alt_source_reviewed=1)
    return {"ok": True, "message": "Bestätigt."}


@router.post("/problems/retry-all")
def retry_all_problems(db: Session = Depends(get_db)):
    """Bulk version of retry_item() for every currently flagged item (see
    crud.list_problem_items) — backs the Start page's single "Alle nochmal
    versuchen" action, which replaces a per-item card list there; individual
    handling still lives in the channel view via retry_item()."""
    items = crud.list_problem_items(db)
    for item in items:
        job = crud.latest_job_for_item(db, item.id) or crud.create_job(db, item.id)
        crud.update_job(
            db, job.id, status="queued", error_text=None,
            next_attempt_at=None, attempt_count=0, progress=0,
        )
        crud.update_item(db, item.id, status="queued", error_text=None)
    if items:
        worker.wake()
    count = len(items)
    return {
        "ok": True, "count": count,
        "message": f"{count} Titel {'wird' if count == 1 else 'werden'} erneut versucht.",
    }


@router.post("/problems/find-alternative-all")
def find_alternative_all_problems(db: Session = Depends(get_db)):
    """Bulk version of find_alternative() for every currently flagged item.
    Items with a placeholder title (no real title to search with) are
    skipped rather than fed a guaranteed-wrong blind search — see
    find_alternative()'s single-item guard for why."""
    items = [i for i in crud.list_problem_items(db) if not downloader.is_placeholder_title(i.title)]
    for item in items:
        query = downloader.default_search_query(item.title, crud.item_search_context(db, item))
        crud.update_item(
            db, item.id, alt_source_url=f"ytsearch1:{query}",
            status="queued", error_text=None,
        )
        job = crud.latest_job_for_item(db, item.id) or crud.create_job(db, item.id)
        crud.update_job(
            db, job.id, status="queued", error_text=None,
            next_attempt_at=None, attempt_count=0, progress=0,
        )
    if items:
        worker.wake()
    count = len(items)
    return {
        "ok": True, "count": count,
        "message": f"Suche nach anderen Quellen für {count} Titel gestartet …",
    }


class ReorderRequest(BaseModel):
    order: list[int]


@router.post("/kanal/{n}/reorder")
def reorder(n: int, payload: ReorderRequest, request: Request,
            db: Session = Depends(get_db)):
    if crud.get_channel(db, n) is None:
        raise HTTPException(status_code=404, detail="Diesen Knopf gibt es nicht.")
    crud.reorder_items(db, n, payload.order)
    try:
        feed.write_feed_file(db, n, _base_url(request))
    except Exception as exc:  # noqa: BLE001
        logger.warning("feed write failed: %s", exc)
    return {"ok": True, "message": "Reihenfolge gespeichert."}


class ReorderBlocksRequest(BaseModel):
    order: list[dict]


@router.post("/kanal/{n}/reorder-blocks")
def reorder_blocks(n: int, payload: ReorderBlocksRequest, request: Request,
                    db: Session = Depends(get_db)):
    """Reorder a channel's top-level list of blocks/singles (separate payload
    shape from /reorder's flat item-id list, so existing callers keep working)."""
    if crud.get_channel(db, n) is None:
        raise HTTPException(status_code=404, detail="Diesen Knopf gibt es nicht.")
    crud.reorder_blocks(db, n, payload.order)
    try:
        feed.write_feed_file(db, n, _base_url(request))
    except Exception as exc:  # noqa: BLE001
        logger.warning("feed write failed: %s", exc)
    return {"ok": True, "message": "Reihenfolge gespeichert."}


class ReorderSubscriptionRequest(BaseModel):
    order: list[int]


@router.post("/subscription/{sub_id}/reorder")
def reorder_subscription(sub_id: int, payload: ReorderSubscriptionRequest, request: Request,
                          db: Session = Depends(get_db)):
    """Reorder the episodes within one playlist block."""
    sub = crud.get_subscription(db, sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Abo nicht gefunden.")
    crud.reorder_subscription_items(db, sub_id, payload.order)
    try:
        feed.write_feed_file(db, sub.channel_id, _base_url(request))
    except Exception as exc:  # noqa: BLE001
        logger.warning("feed write failed: %s", exc)
    return {"ok": True, "message": "Reihenfolge gespeichert."}


def _delete_item_and_file(db: Session, item_id: int, base_url: str) -> bool:
    """Delete one item's DB row, its audio file, and rewrite its channel's
    feed. Shared by the plain delete route and the eviction-delete path."""
    item = crud.get_item(db, item_id)
    if item is None:
        return False
    channel_id = item.channel_id
    filename = item.filename
    crud.delete_item(db, item_id)
    if filename:
        path = config.AUDIO_DIR / str(channel_id) / filename
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
    try:
        feed.write_feed_file(db, channel_id, base_url)
    except Exception:  # noqa: BLE001
        pass
    return True


def _delete_subscription_and_files(db: Session, sub_id: int, base_url: str) -> int:
    """Delete a whole playlist/subscription: every item's DB row + audio
    file, the subscription itself, and rewrite every affected channel's feed."""
    items = crud.list_items_by_subscription(db, sub_id)
    file_refs = [(i.channel_id, i.filename) for i in items if i.filename]
    channels_touched = {i.channel_id for i in items}
    count = crud.delete_subscription(db, sub_id)
    for channel_id, filename in file_refs:
        path = config.AUDIO_DIR / str(channel_id) / filename
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
    for channel_id in channels_touched:
        try:
            feed.write_feed_file(db, channel_id, base_url)
        except Exception:  # noqa: BLE001
            pass
    return count


@router.delete("/item/{item_id}")
def delete_item(item_id: int, request: Request, db: Session = Depends(get_db)):
    if not _delete_item_and_file(db, item_id, _base_url(request)):
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden.")
    return {"ok": True, "message": "Eintrag gelöscht."}


@router.delete("/problems/delete-all")
def delete_all_problems(request: Request, db: Session = Depends(get_db)):
    """Bulk version of delete_item() for every currently flagged item."""
    items = crud.list_problem_items(db)
    base_url = _base_url(request)
    count = 0
    for item in items:
        if _delete_item_and_file(db, item.id, base_url):
            count += 1
    return {"ok": True, "count": count, "message": f"{count} Titel gelöscht."}


@router.delete("/subscription/{sub_id}")
def delete_subscription(sub_id: int, request: Request, db: Session = Depends(get_db)):
    if crud.get_subscription(db, sub_id) is None:
        raise HTTPException(status_code=404, detail="Abo nicht gefunden.")
    count = _delete_subscription_and_files(db, sub_id, _base_url(request))
    return {"ok": True, "message": f"{count} Folgen gelöscht."}


@router.post("/item/{item_id}/park")
def park_item(item_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        library.park_item(db, item_id, _base_url(request))
    except library.LibraryError as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "message": "In die Bibliothek verschoben."}


class AssignRequest(BaseModel):
    channel_id: int


@router.post("/item/{item_id}/assign")
def assign_item(item_id: int, payload: AssignRequest, request: Request,
                 db: Session = Depends(get_db)):
    try:
        library.reassign_item(db, item_id, payload.channel_id, _base_url(request))
    except library.LibraryError as exc:
        return {"ok": False, "message": str(exc)}
    channel = crud.get_channel(db, payload.channel_id)
    return {"ok": True, "message": f"Auf „{channel.name}“ verschoben."}


@router.post("/subscription/{sub_id}/park")
def park_subscription(sub_id: int, request: Request, db: Session = Depends(get_db)):
    if crud.get_subscription(db, sub_id) is None:
        raise HTTPException(status_code=404, detail="Abo nicht gefunden.")
    try:
        count = library.park_block(db, sub_id, _base_url(request))
    except library.LibraryError as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "message": f"{count} Folgen in die Bibliothek verschoben."}


@router.post("/subscription/{sub_id}/assign")
def assign_subscription(sub_id: int, payload: AssignRequest, request: Request,
                         db: Session = Depends(get_db)):
    if crud.get_subscription(db, sub_id) is None:
        raise HTTPException(status_code=404, detail="Abo nicht gefunden.")
    try:
        count = library.reassign_block(db, sub_id, payload.channel_id, _base_url(request))
    except library.LibraryError as exc:
        return {"ok": False, "message": str(exc)}
    channel = crud.get_channel(db, payload.channel_id)
    return {"ok": True, "message": f"{count} Folgen auf „{channel.name}“ verschoben."}


class AboToggleRequest(BaseModel):
    enabled: bool


@router.post("/kanal/{n}/abo-toggle")
def abo_toggle(n: int, payload: AboToggleRequest, db: Session = Depends(get_db)):
    if crud.get_channel(db, n) is None:
        raise HTTPException(status_code=404, detail="Diesen Knopf gibt es nicht.")
    subs = crud.set_subscription_enabled(db, n, payload.enabled)
    refresh_jobs()
    state = "an" if payload.enabled else "aus"
    return {"ok": True, "enabled": payload.enabled,
            "message": f"Automatisches Holen ist jetzt {state}.",
            "count": len(subs)}


@router.post("/kanal/{n}/park")
def park_channel(n: int, request: Request, db: Session = Depends(get_db)):
    """Move every active item of this channel to the Bibliothek at once --
    the whole-channel counterpart to item/{id}/park and subscription/{id}/park,
    already used internally by set_channel_active() when deactivating a
    channel with content, exposed here as its own standalone action.

    Also disables any subscriptions on this channel (same as park_block()
    does for a single playlist) -- otherwise the next Abo-Sync would just
    pull the parked episodes' successors straight back into the now-empty
    channel, undoing the point of "move everything out"."""
    if crud.get_channel(db, n) is None:
        raise HTTPException(status_code=404, detail="Diesen Knopf gibt es nicht.")
    count = library.park_channel(db, n, _base_url(request))
    crud.set_subscription_enabled(db, n, False)
    return {"ok": True, "message": f"{count} Folgen in die Bibliothek verschoben.", "count": count}


class ChannelActiveRequest(BaseModel):
    active: bool
    move_to_library: bool = False


@router.post("/kanal/{n}/set-active")
def set_channel_active(n: int, payload: ChannelActiveRequest, request: Request, db: Session = Depends(get_db)):
    channel = crud.get_channel(db, n)
    if channel is None:
        raise HTTPException(status_code=404, detail="Diesen Knopf gibt es nicht.")

    if payload.active:
        crud.set_channel_active(db, n, True)
        return {"ok": True, "active": True, "message": f"„{channel.name}“ ist wieder aktiv."}

    if crud.channel_has_content(db, n) and not payload.move_to_library:
        return {
            "ok": False,
            "needs_confirmation": True,
            "message": f"„{channel.name}“ hat noch Inhalte. In Bibliothek verschieben oder abbrechen?",
        }

    if payload.move_to_library:
        library.park_channel(db, n, _base_url(request))
    crud.set_subscription_enabled(db, n, False)
    crud.set_channel_active(db, n, False)
    return {"ok": True, "active": False, "message": f"„{channel.name}“ ist jetzt inaktiv."}


class SettingsRequest(BaseModel):
    max_items_per_list: Optional[int] = None
    max_playlist_length: Optional[int] = None
    audio_channels: Optional[int] = None


@router.post("/settings")
def save_settings(payload: SettingsRequest, db: Session = Depends(get_db)):
    """Each field is optional so the Setup page's cards can save
    independently without one field's save resetting the others."""
    fields = {}
    messages = []

    if payload.max_items_per_list is not None:
        if not (1 <= payload.max_items_per_list <= 500):
            return {"ok": False, "message": "Bitte eine Zahl zwischen 1 und 500 eingeben."}
        fields["max_items_per_list"] = payload.max_items_per_list
        messages.append(f"bis zu {payload.max_items_per_list} Folgen pro Liste werden geladen")

    if payload.max_playlist_length is not None:
        if not (1 <= payload.max_playlist_length <= 500):
            return {"ok": False, "message": "Bitte eine Zahl zwischen 1 und 500 eingeben."}
        fields["max_playlist_length"] = payload.max_playlist_length
        messages.append(f"max. {payload.max_playlist_length} Folgen werden je Kanal behalten")

    if payload.audio_channels is not None:
        if payload.audio_channels not in (1, 2):
            return {"ok": False, "message": "Bitte Mono oder Stereo wählen."}
        fields["audio_channels"] = payload.audio_channels
        # Only future downloads/reprocessing pick this up — existing MP3s on
        # disk keep whatever channel count they were originally encoded with.
        label = "Mono" if payload.audio_channels == 1 else "Stereo"
        messages.append(f"neue Downloads werden ab jetzt in {label} umgewandelt")

    if not fields:
        return {"ok": False, "message": "Nichts zu speichern."}

    crud.update_settings(db, **fields)
    return {"ok": True, "message": "Gespeichert – " + ", ".join(messages) + "."}


class SDExportRequest(BaseModel):
    path: str = "/media/sdcard"


@router.post("/sd-export")
def sd_export_endpoint(payload: SDExportRequest, db: Session = Depends(get_db)):
    try:
        result = sd_export.export_to_sd(db, payload.path)
        return result
    except sd_export.SDExportError as exc:
        return {"ok": False, "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.error("sd export failed: %s", exc)
        return {"ok": False,
                "message": "Das Schreiben auf die Karte ging nicht. "
                           "→ Karte neu einstecken und erneut tippen."}


@router.get("/sd-export/zip")
def sd_export_zip(db: Session = Depends(get_db)):
    """Browser-native SD export: download everything as one ZIP, folders 0..8.

    Used from the "Belegung"-Seite instead of the server-path variant above —
    no server-side access to the card needed, works from whatever device the
    browser (and the card reader) is actually on. Written to a real temp file
    rather than held in memory, since the whole library can run into the
    hundreds of MB.
    """
    fd, tmp_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    try:
        sd_export.build_export_zip(db, Path(tmp_path))
    except Exception as exc:  # noqa: BLE001
        os.unlink(tmp_path)
        logger.error("sd export zip failed: %s", exc)
        raise HTTPException(status_code=500, detail="Die ZIP-Datei konnte nicht erstellt werden.") from exc
    return FileResponse(
        tmp_path,
        media_type="application/zip",
        filename="hoerbox-sd-karte.zip",
        background=BackgroundTask(os.unlink, tmp_path),
    )


@router.delete("/audio/{channel_id}/{filename}")
def delete_audio_file(channel_id: int, filename: str, db: Session = Depends(get_db)):
    """Delete a single audio file from a channel."""
    channel = crud.get_channel(db, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Kanal nicht gefunden.")

    # Security: prevent path traversal
    if "/" in filename or ".." in filename or filename.startswith("_"):
        raise HTTPException(status_code=400, detail="Ungültiger Dateiname.")

    file_path = config.AUDIO_DIR / str(channel_id) / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Datei nicht gefunden.")

    try:
        file_path.unlink()
        # Also remove corresponding item from DB if exists
        items = crud.list_items(db, channel_id)
        for item in items:
            if item.filename == filename:
                crud.delete_item(db, item.id)
                break
        return {"ok": True, "message": "Datei gelöscht."}
    except Exception as exc:  # noqa: BLE001
        logger.error("delete file failed: %s", exc)
        raise HTTPException(status_code=500, detail="Löschen fehlgeschlagen.") from exc


@router.post("/cookies-upload")
async def upload_cookies(file: UploadFile = File(...)):
    """Accept a cookies.txt upload and save it to the data directory."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Keine Datei übermittelt.")

    # Basic sanity check: must look like a Netscape cookies file.
    first_bytes = await file.read(64)
    await file.seek(0)
    if b"HTTP" not in first_bytes and b"# Netscape" not in first_bytes and b"# HTTP" not in first_bytes:
        # Be lenient – also accept files that just start with a domain line.
        # Only reject obviously wrong types (e.g. images, ZIPs).
        if first_bytes[:4] in (b"\x89PNG", b"\xff\xd8\xff", b"PK\x03\x04"):
            raise HTTPException(status_code=400,
                                detail="Das ist keine Cookies-Datei.")

    # DB_DIR (/data/db), not DATA_DIR (/data) — see downloader._cookies_path()
    # for why: only DB_DIR is an actual persistent volume mount, so a plain
    # DATA_DIR path would get silently wiped on the next container rebuild.
    dest = config.DB_DIR / "cookies.txt"
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with dest.open("wb") as fh:
            shutil.copyfileobj(file.file, fh)
    except Exception as exc:
        logger.error("cookies upload failed: %s", exc)
        raise HTTPException(status_code=500, detail="Speichern fehlgeschlagen.") from exc

    size = dest.stat().st_size
    logger.info("cookies.txt uploaded, %d bytes", size)
    return {"ok": True, "message": "YouTube-Zugang gespeichert ✓", "bytes": size}


@router.delete("/audio/{channel_id}")
def delete_all_audio_files(channel_id: int, request: Request, db: Session = Depends(get_db)):
    """Delete all audio files from a channel."""
    channel = crud.get_channel(db, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Kanal nicht gefunden.")

    channel_dir = config.AUDIO_DIR / str(channel_id)
    deleted = 0
    active_names = crud.active_filenames(db, channel_id)

    if channel_dir.exists():
        for file in channel_dir.glob("*.mp3"):
            if file.name.startswith("_"):  # skip temp
                continue
            if file.name not in active_names:  # protect parked (Bibliothek) files
                continue
            try:
                file.unlink()
                deleted += 1
            except Exception:  # noqa: BLE001
                pass

    # Remove only active (non-parked) items from DB for this channel
    items = crud.list_active_items(db, channel_id)
    for item in items:
        crud.delete_item(db, item.id)

    # Regenerate empty feed
    try:
        feed.write_feed_file(db, channel_id, str(request.base_url).rstrip("/"))
    except Exception:  # noqa: BLE001
        pass

    return {"ok": True, "message": f"{deleted} Dateien gelöscht.", "count": deleted}
