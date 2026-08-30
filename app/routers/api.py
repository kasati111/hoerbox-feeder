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

from .. import config, crud, downloader, feed, i18n, library, sd_export, worker
from ..database import get_db
from ..scheduler import refresh_jobs

logger = logging.getLogger("hoerbox.api")

router = APIRouter(prefix="/api")


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


class AddRequest(BaseModel):
    url: str
    channel: int
    # A resubmission after needs_confirmation=True -- overflow from adding
    # always moves to the Bibliothek (never deletes, see the eviction block
    # below), so there is no accompanying "mode" to choose.
    confirm_evict: bool = False


@router.post("/add")
def add_content(payload: AddRequest, request: Request, db: Session = Depends(get_db)):
    """Add a link to a channel. Series become auto-subscriptions."""
    settings = crud.get_settings(db)
    lang, skin = settings.language, settings.skin
    channel = crud.get_channel(db, payload.channel)
    if channel is None:
        raise HTTPException(status_code=404, detail=i18n.t("api.channel_not_found", lang))
    if not channel.active:
        raise HTTPException(status_code=400, detail=i18n.t("api.channel_inactive", lang))

    url = payload.url.strip()
    if not url:
        return {"ok": False, "message": i18n.t("api.paste_link_first", lang),
                "action": i18n.t("api.paste_link_action", lang)}

    # Storage guard.
    if not worker.storage_ok():
        tidy = worker.channel_with_most_items(db)
        tidy_channel = crud.get_channel(db, tidy)
        tidy_name = i18n.channel_label(tidy_channel, lang, skin)
        return {
            "ok": False,
            "message": i18n.t("api.no_space", lang, name=tidy_name),
            "action": i18n.t("api.tidy_up_action", lang),
        }

    try:
        info = downloader.analyze(url, lang)
    except Exception as exc:  # noqa: BLE001
        logger.error("analyze failed url=%s error=%s", url, exc)
        return {
            "ok": False,
            "message": i18n.t("api.link_failed", lang),
            "action": i18n.t("api.try_again_action", lang),
        }

    job_ids = []
    created_items = 0
    total_entries = len(info.entries)

    # Limit initial items for large playlists to prevent request timeouts and wasted downloads.
    # Subscriptions will automatically fetch new entries later.
    limit = min(total_entries, settings.max_items_per_list)
    entries_to_process = info.entries[:limit]

    # Series -> create an auto-subscription (default on) *before* creating the
    # initial batch of items, and tag each item with its subscription_id.
    # Otherwise the channel page's block-grouping (by subscription_id) would
    # never group a freshly-added playlist's own items — only episodes synced
    # in later would form a block, splitting one show into two groups.
    is_series = info.is_series
    sub_id = None

    # Any add (single item or whole playlist) may need to make room under
    # the global "maximale Playlistlänge" setting -- this is also the
    # device's own per-button track limit, so overflow always moves to the
    # Bibliothek, never deletes (a device sync must never be the reason
    # something gets permanently lost). Never evict silently here (unlike
    # the automatic background sync in scheduler.py) -- ask first, since a
    # live user is present; confirm_evict=True (a resubmission of this same
    # request) means they already said yes. Whole playlists/subscriptions
    # are always moved as one unit, never split (see
    # _oldest_first_eviction_units()).
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
            names = ", ".join(i18n.quote(title, lang) for title in titles)
            return {
                "ok": True,
                "needs_confirmation": True,
                "message": i18n.t("api.eviction_needed", lang, names=names),
            }
        if plan and payload.confirm_evict:
            base_url = _base_url(request)
            for unit in plan:
                try:
                    if unit["kind"] == "block":
                        library.park_block(db, unit["subscription_id"], base_url)
                    else:
                        library.park_item(db, unit["item_ids"][0], base_url)
                except library.LibraryError as exc:
                    logger.warning("eviction action failed: %s", exc)

    if is_series:
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
            "message": i18n.t("api.already_exists", lang),
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

    message = i18n.t("api.preparing", lang)
    if is_series:
        channel_name = i18n.channel_label(channel, lang, skin)
        label = f"{i18n.quote(series_title, lang)} ({channel_name})" if series_title else i18n.t("api.the_list", lang)
        if total_entries > limit:
            message = i18n.t(
                "api.series_over_limit", lang,
                label=label, total=total_entries, created=created_items,
            )
        else:
            message = i18n.t(
                "api.series_all_loading", lang,
                label=label, created=created_items,
            )

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
    lang, _skin = crud.lang_skin(db)
    job = crud.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=i18n.t("api.job_not_found", lang))

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
            text = i18n.t("api.queue_position", lang, pos=pos)
        else:
            text = i18n.t("api.preparing", lang)
    elif job.status == "running":
        pct = job.progress or 0
        if pct >= 90:
            # Download is finished; ffmpeg conversion is running.
            text = i18n.t("api.converting", lang)
        else:
            text = i18n.t("api.loading_percent", lang, pct=pct)
    elif job.status == "done":
        text = i18n.t("api.on_player_tomorrow", lang)
    elif job.status == "cancelled":
        text = i18n.t("api.cancelled", lang)
    else:  # failed
        reason = job.error_text or i18n.t("api.unknown_reason", lang)
        text = reason

    item = crud.get_item(db, job.item_id)

    return {
        "status": job.status,
        "progress": job.progress or 0,
        "text": text,
        "action": i18n.t("api.try_again_action", lang) if job.status == "failed" else None,
        "can_cancel": job.status in ("queued", "running"),
        "item_id": job.item_id,
        "is_backoff": is_backoff,
        "error_text": job.error_text,
        # Lets the client backfill a display title for a batch whose
        # seriesTitle wasn't available client-side (e.g. localStorage was
        # cleared, or the status page was opened fresh) — see pollJobs().
        "item_title": item.title if item else None,
    }


@router.get("/logs")
def logs_content(lines: int = 300):
    """Polled by the /logs page to auto-refresh without a full reload.

    Mirrors app.routers.ui.logs_page()'s line-reading (same file, same
    newest-first order, same cap) but returns just the text -- kept
    duplicated rather than shared since it's a handful of lines and the
    two live in genuinely different route modules (HTML page vs. JSON API).
    """
    from ..main import LOG_PATH  # local import: main imports this router, avoid a cycle

    lines = max(10, min(lines, 2000))
    content = ""
    if LOG_PATH.exists():
        all_lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
        content = "\n".join(reversed(all_lines[-lines:]))
    return {"content": content}


@router.delete("/job/{job_id}")
def cancel_job(job_id: int, db: Session = Depends(get_db)):
    """Cancel a queued or running job."""
    lang, _skin = crud.lang_skin(db)
    job = crud.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=i18n.t("api.job_not_found", lang))

    if job.status not in ("queued", "running"):
        return {"ok": False, "message": i18n.t("api.job_cannot_cancel", lang)}

    crud.update_job(db, job_id, status="cancelled", error_text=i18n.t("api.cancelled_short", lang))
    if job.item_id:
        crud.update_item(db, job.item_id, status="cancelled", error_text=i18n.t("api.cancelled_short", lang))

    return {"ok": True, "message": i18n.t("api.job_was_cancelled", lang)}


@router.post("/item/{item_id}/retry")
def retry_item(item_id: int, db: Session = Depends(get_db)):
    """Retry a failed or backing-off item right now, instead of waiting out
    the exponential backoff (or giving up after MAX_ATTEMPTS).
    """
    lang, _skin = crud.lang_skin(db)
    item = crud.get_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=i18n.t("api.item_not_found", lang))
    if not item.error_text and item.status != "failed":
        return {"ok": False, "message": i18n.t("api.no_current_problem", lang)}

    job = crud.latest_job_for_item(db, item_id) or crud.create_job(db, item_id)
    crud.update_job(
        db, job.id, status="queued", error_text=None,
        next_attempt_at=None, attempt_count=0, progress=0,
    )
    crud.update_item(db, item_id, status="queued", error_text=None)
    worker.wake()
    return {"ok": True, "message": i18n.t("api.will_retry", lang), "job_id": job.id}


@router.post("/item/{item_id}/find-alternative")
def find_alternative(item_id: int, db: Session = Depends(get_db)):
    """Search for a different source of the same title and retry with it.

    Reuses yt-dlp's native ytsearch1: pseudo-URL (the same mechanism already
    used for Spotify-sourced items in downloader._resolve_spotify, including
    its automatic YouTube-Music fallback on a miss) — no new download logic
    needed. Sets Item.alt_source_url rather than overwriting source_url, so
    a subscription-linked item keeps matching correctly on future syncs.
    """
    lang, _skin = crud.lang_skin(db)
    item = crud.get_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=i18n.t("api.item_not_found", lang))
    if not item.error_text and item.status != "failed":
        return {"ok": False, "message": i18n.t("api.no_current_problem", lang)}
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
            "message": i18n.t("api.no_title_search_self", lang),
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
    return {"ok": True, "message": i18n.t("api.searching_alt_source", lang), "job_id": job.id}


class SearchAlternativeRequest(BaseModel):
    query: str


@router.post("/item/{item_id}/search-alternative")
def search_alternative(item_id: int, payload: SearchAlternativeRequest, db: Session = Depends(get_db)):
    """Look up candidates for a user-chosen search term — a pure lookup, no
    DB mutation, no download. The human-verifiable counterpart to the blind
    ytsearch1: guess: shows title/uploader/duration/thumbnail so a parent can
    actually tell the candidates apart before committing to one."""
    lang, _skin = crud.lang_skin(db)
    if crud.get_item(db, item_id) is None:
        raise HTTPException(status_code=404, detail=i18n.t("api.item_not_found", lang))
    query = payload.query.strip()
    if not query:
        return {"ok": False, "message": i18n.t("api.enter_search_term", lang), "candidates": []}
    try:
        candidates = downloader.search_candidates(query, lang=lang)
    except Exception as exc:  # noqa: BLE001
        logger.warning("search_candidates failed for %r: %s", query, exc)
        return {"ok": False, "message": i18n.t("api.search_failed", lang), "candidates": []}
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
    lang, _skin = crud.lang_skin(db)
    item = crud.get_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=i18n.t("api.item_not_found", lang))
    url = payload.url.strip()
    if not url:
        return {"ok": False, "message": i18n.t("api.no_source_selected", lang)}

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
    return {"ok": True, "message": i18n.t("api.loading_with_picked_source", lang), "job_id": job.id}


@router.post("/item/{item_id}/confirm-alternative")
def confirm_alternative(item_id: int, db: Session = Depends(get_db)):
    """Dismiss the "please check this" hint without touching the audio —
    for when a parent has listened/looked and the auto-substituted content
    is actually fine as-is."""
    lang, _skin = crud.lang_skin(db)
    item = crud.get_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=i18n.t("api.item_not_found", lang))
    crud.update_item(db, item_id, alt_source_reviewed=1)
    return {"ok": True, "message": i18n.t("api.confirmed", lang)}


@router.post("/problems/retry-all")
def retry_all_problems(db: Session = Depends(get_db)):
    """Bulk version of retry_item() for every currently flagged item (see
    crud.list_problem_items) — backs the Start page's single "Alle nochmal
    versuchen" action, which replaces a per-item card list there; individual
    handling still lives in the channel view via retry_item()."""
    lang, _skin = crud.lang_skin(db)
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
        "message": i18n.t(
            "api.retry_count", lang, count=count,
            verb="wird" if count == 1 else "werden",
            s="" if count == 1 else "s",
        ),
    }


@router.post("/problems/find-alternative-all")
def find_alternative_all_problems(db: Session = Depends(get_db)):
    """Bulk version of find_alternative() for every currently flagged item.
    Items with a placeholder title (no real title to search with) are
    skipped rather than fed a guaranteed-wrong blind search — see
    find_alternative()'s single-item guard for why."""
    lang, _skin = crud.lang_skin(db)
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
        "message": i18n.t("api.find_alt_count", lang, count=count, s="" if count == 1 else "s"),
    }


class ReorderRequest(BaseModel):
    order: list[int]


@router.post("/kanal/{n}/reorder")
def reorder(n: int, payload: ReorderRequest, request: Request,
            db: Session = Depends(get_db)):
    lang, _skin = crud.lang_skin(db)
    if crud.get_channel(db, n) is None:
        raise HTTPException(status_code=404, detail=i18n.t("api.channel_not_found", lang))
    crud.reorder_items(db, n, payload.order)
    try:
        feed.write_feed_file(db, n, _base_url(request))
    except Exception as exc:  # noqa: BLE001
        logger.warning("feed write failed: %s", exc)
    return {"ok": True, "message": i18n.t("api.order_saved", lang)}


class ReorderBlocksRequest(BaseModel):
    order: list[dict]


@router.post("/kanal/{n}/reorder-blocks")
def reorder_blocks(n: int, payload: ReorderBlocksRequest, request: Request,
                    db: Session = Depends(get_db)):
    """Reorder a channel's top-level list of blocks/singles (separate payload
    shape from /reorder's flat item-id list, so existing callers keep working)."""
    lang, _skin = crud.lang_skin(db)
    if crud.get_channel(db, n) is None:
        raise HTTPException(status_code=404, detail=i18n.t("api.channel_not_found", lang))
    crud.reorder_blocks(db, n, payload.order)
    try:
        feed.write_feed_file(db, n, _base_url(request))
    except Exception as exc:  # noqa: BLE001
        logger.warning("feed write failed: %s", exc)
    return {"ok": True, "message": i18n.t("api.order_saved", lang)}


class ReorderSubscriptionRequest(BaseModel):
    order: list[int]


@router.post("/subscription/{sub_id}/reorder")
def reorder_subscription(sub_id: int, payload: ReorderSubscriptionRequest, request: Request,
                          db: Session = Depends(get_db)):
    """Reorder the episodes within one playlist block."""
    lang, _skin = crud.lang_skin(db)
    sub = crud.get_subscription(db, sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail=i18n.t("api.subscription_not_found", lang))
    crud.reorder_subscription_items(db, sub_id, payload.order)
    try:
        feed.write_feed_file(db, sub.channel_id, _base_url(request))
    except Exception as exc:  # noqa: BLE001
        logger.warning("feed write failed: %s", exc)
    return {"ok": True, "message": i18n.t("api.order_saved", lang)}


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
    lang, _skin = crud.lang_skin(db)
    if not _delete_item_and_file(db, item_id, _base_url(request)):
        raise HTTPException(status_code=404, detail=i18n.t("api.item_not_found", lang))
    return {"ok": True, "message": i18n.t("api.entry_deleted", lang)}


@router.delete("/problems/delete-all")
def delete_all_problems(request: Request, db: Session = Depends(get_db)):
    """Bulk version of delete_item() for every currently flagged item."""
    lang, _skin = crud.lang_skin(db)
    items = crud.list_problem_items(db)
    base_url = _base_url(request)
    count = 0
    for item in items:
        if _delete_item_and_file(db, item.id, base_url):
            count += 1
    return {"ok": True, "count": count,
            "message": i18n.t("api.count_deleted", lang, count=count, s="" if count == 1 else "s")}


@router.delete("/subscription/{sub_id}")
def delete_subscription(sub_id: int, request: Request, db: Session = Depends(get_db)):
    lang, _skin = crud.lang_skin(db)
    if crud.get_subscription(db, sub_id) is None:
        raise HTTPException(status_code=404, detail=i18n.t("api.subscription_not_found", lang))
    count = _delete_subscription_and_files(db, sub_id, _base_url(request))
    return {"ok": True, "message": i18n.t("api.episodes_deleted", lang, count=count, s="" if count == 1 else "s")}


@router.post("/item/{item_id}/park")
def park_item(item_id: int, request: Request, db: Session = Depends(get_db)):
    lang, _skin = crud.lang_skin(db)
    try:
        library.park_item(db, item_id, _base_url(request))
    except library.LibraryError as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "message": i18n.t("api.moved_to_library", lang)}


class AssignRequest(BaseModel):
    channel_id: int


@router.post("/item/{item_id}/assign")
def assign_item(item_id: int, payload: AssignRequest, request: Request,
                 db: Session = Depends(get_db)):
    lang, skin = crud.lang_skin(db)
    try:
        library.reassign_item(db, item_id, payload.channel_id, _base_url(request))
    except library.LibraryError as exc:
        return {"ok": False, "message": str(exc)}
    channel = crud.get_channel(db, payload.channel_id)
    return {"ok": True, "message": i18n.t("api.moved_to_channel", lang, name=i18n.channel_label(channel, lang, skin))}


@router.post("/subscription/{sub_id}/park")
def park_subscription(sub_id: int, request: Request, db: Session = Depends(get_db)):
    lang, _skin = crud.lang_skin(db)
    if crud.get_subscription(db, sub_id) is None:
        raise HTTPException(status_code=404, detail=i18n.t("api.subscription_not_found", lang))
    try:
        count = library.park_block(db, sub_id, _base_url(request))
    except library.LibraryError as exc:
        return {"ok": False, "message": str(exc)}
    message = i18n.t("api.episodes_moved_to_library", lang, count=count, s="" if count == 1 else "s")
    return {"ok": True, "message": message}


@router.post("/subscription/{sub_id}/assign")
def assign_subscription(sub_id: int, payload: AssignRequest, request: Request,
                         db: Session = Depends(get_db)):
    lang, skin = crud.lang_skin(db)
    if crud.get_subscription(db, sub_id) is None:
        raise HTTPException(status_code=404, detail=i18n.t("api.subscription_not_found", lang))
    try:
        count = library.reassign_block(db, sub_id, payload.channel_id, _base_url(request))
    except library.LibraryError as exc:
        return {"ok": False, "message": str(exc)}
    channel = crud.get_channel(db, payload.channel_id)
    return {"ok": True, "message": i18n.t(
        "api.episodes_moved_to_channel", lang, count=count,
        s="" if count == 1 else "s", name=i18n.channel_label(channel, lang, skin),
    )}


class RenameSubscriptionRequest(BaseModel):
    title: str


@router.post("/subscription/{sub_id}/rename")
def rename_subscription(sub_id: int, payload: RenameSubscriptionRequest, db: Session = Depends(get_db)):
    lang, _skin = crud.lang_skin(db)
    if crud.get_subscription(db, sub_id) is None:
        raise HTTPException(status_code=404, detail=i18n.t("api.subscription_not_found", lang))
    title = payload.title.strip()
    if not title:
        return {"ok": False, "message": i18n.t("api.title_required", lang)}
    crud.update_subscription(db, sub_id, title=title)
    return {"ok": True, "message": i18n.t("api.subscription_renamed", lang), "title": title}


class AboToggleRequest(BaseModel):
    enabled: bool


@router.post("/kanal/{n}/abo-toggle")
def abo_toggle(n: int, payload: AboToggleRequest, db: Session = Depends(get_db)):
    lang, _skin = crud.lang_skin(db)
    if crud.get_channel(db, n) is None:
        raise HTTPException(status_code=404, detail=i18n.t("api.channel_not_found", lang))
    subs = crud.set_subscription_enabled(db, n, payload.enabled)
    refresh_jobs()
    state = i18n.t("api.abo_on", lang) if payload.enabled else i18n.t("api.abo_off", lang)
    return {"ok": True, "enabled": payload.enabled,
            "message": i18n.t("api.abo_state", lang, state=state),
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
    lang, _skin = crud.lang_skin(db)
    if crud.get_channel(db, n) is None:
        raise HTTPException(status_code=404, detail=i18n.t("api.channel_not_found", lang))
    count = library.park_channel(db, n, _base_url(request))
    crud.set_subscription_enabled(db, n, False)
    message = i18n.t("api.episodes_moved_to_library", lang, count=count, s="" if count == 1 else "s")
    return {"ok": True, "message": message, "count": count}


class ChannelActiveRequest(BaseModel):
    active: bool
    move_to_library: bool = False


@router.post("/kanal/{n}/set-active")
def set_channel_active(n: int, payload: ChannelActiveRequest, request: Request, db: Session = Depends(get_db)):
    lang, skin = crud.lang_skin(db)
    channel = crud.get_channel(db, n)
    if channel is None:
        raise HTTPException(status_code=404, detail=i18n.t("api.channel_not_found", lang))
    name = i18n.channel_label(channel, lang, skin)

    if payload.active:
        crud.set_channel_active(db, n, True)
        return {"ok": True, "active": True, "message": i18n.t("api.channel_active_again", lang, name=name)}

    if crud.channel_has_content(db, n) and not payload.move_to_library:
        return {
            "ok": False,
            "needs_confirmation": True,
            "message": i18n.t("api.channel_has_content", lang, name=name),
        }

    if payload.move_to_library:
        library.park_channel(db, n, _base_url(request))
    crud.set_subscription_enabled(db, n, False)
    crud.set_channel_active(db, n, False)
    return {"ok": True, "active": False, "message": i18n.t("api.channel_now_inactive", lang, name=name)}


class SettingsRequest(BaseModel):
    max_items_per_list: Optional[int] = None
    max_playlist_length: Optional[int] = None
    audio_channels: Optional[int] = None
    language: Optional[str] = None
    skin: Optional[str] = None


@router.post("/settings")
def save_settings(payload: SettingsRequest, db: Session = Depends(get_db)):
    """Each field is optional so the Setup page's cards can save
    independently without one field's save resetting the others."""
    lang, _skin = crud.lang_skin(db)  # current language, used for validation messages
    # If this request also changes the language itself, every message below
    # (not just the language one) should read in the newly-selected language
    # — otherwise saving language+skin together produces a bilingual summary
    # line. Resolved up front so all per-field messages agree.
    summary_lang = payload.language if payload.language is not None else lang
    fields = {}
    messages = []

    if payload.max_items_per_list is not None:
        if not (1 <= payload.max_items_per_list <= 500):
            return {"ok": False, "message": i18n.t("api.number_range_error", lang)}
        fields["max_items_per_list"] = payload.max_items_per_list
        messages.append(i18n.t("api.max_items_saved", summary_lang, n=payload.max_items_per_list))

    if payload.max_playlist_length is not None:
        if not (1 <= payload.max_playlist_length <= 500):
            return {"ok": False, "message": i18n.t("api.number_range_error", lang)}
        fields["max_playlist_length"] = payload.max_playlist_length
        messages.append(i18n.t("api.max_length_saved", summary_lang, n=payload.max_playlist_length))

    if payload.audio_channels is not None:
        if payload.audio_channels not in (1, 2):
            return {"ok": False, "message": i18n.t("api.choose_mono_stereo", lang)}
        fields["audio_channels"] = payload.audio_channels
        # Only future downloads/reprocessing pick this up — existing MP3s on
        # disk keep whatever channel count they were originally encoded with.
        label = (
            i18n.t("setup.audio_mono", summary_lang) if payload.audio_channels == 1
            else i18n.t("setup.audio_stereo", summary_lang)
        )
        messages.append(i18n.t("api.audio_channels_saved", summary_lang, label=label))

    if payload.language is not None:
        if payload.language not in i18n.LANGS:
            return {"ok": False, "message": i18n.t("api.choose_language", lang)}
        fields["language"] = payload.language
        # Confirmation shown in the newly-selected language, not the old one
        # — immediate proof the switch worked, right before the page reloads.
        new_lang = payload.language
        label = i18n.t("setup.language_de", new_lang) if new_lang == "de" else i18n.t("setup.language_en", new_lang)
        messages.append(i18n.t("api.language_saved", new_lang, label=label))

    if payload.skin is not None:
        if payload.skin not in i18n.SKINS:
            return {"ok": False, "message": i18n.t("api.choose_skin", lang)}
        fields["skin"] = payload.skin
        messages.append(
            i18n.t("api.skin_saved_colors", summary_lang) if payload.skin == "colors"
            else i18n.t("api.skin_saved_numbers", summary_lang)
        )

    if not fields:
        return {"ok": False, "message": i18n.t("api.nothing_to_save", lang)}

    crud.update_settings(db, **fields)
    return {"ok": True, "message": i18n.t("api.saved_prefix", summary_lang, details=", ".join(messages))}


class SDExportRequest(BaseModel):
    path: str = "/media/sdcard"


@router.post("/sd-export")
def sd_export_endpoint(payload: SDExportRequest, db: Session = Depends(get_db)):
    lang, _skin = crud.lang_skin(db)
    try:
        result = sd_export.export_to_sd(db, payload.path)
        return result
    except sd_export.SDExportError as exc:
        return {"ok": False, "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.error("sd export failed: %s", exc)
        return {"ok": False, "message": i18n.t("api.sd_write_failed", lang)}


@router.get("/sd-export/zip")
def sd_export_zip(db: Session = Depends(get_db)):
    """Browser-native SD export: download everything as one ZIP, folders 0..8.

    Used from the "Belegung"-Seite instead of the server-path variant above —
    no server-side access to the card needed, works from whatever device the
    browser (and the card reader) is actually on. Written to a real temp file
    rather than held in memory, since the whole library can run into the
    hundreds of MB.
    """
    lang, _skin = crud.lang_skin(db)
    fd, tmp_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    try:
        sd_export.build_export_zip(db, Path(tmp_path))
    except Exception as exc:  # noqa: BLE001
        os.unlink(tmp_path)
        logger.error("sd export zip failed: %s", exc)
        raise HTTPException(status_code=500, detail=i18n.t("api.zip_failed", lang)) from exc
    return FileResponse(
        tmp_path,
        media_type="application/zip",
        filename="hoerbox-sd-karte.zip",
        background=BackgroundTask(os.unlink, tmp_path),
    )


@router.delete("/audio/{channel_id}/{filename}")
def delete_audio_file(channel_id: int, filename: str, db: Session = Depends(get_db)):
    """Delete a single audio file from a channel."""
    lang, _skin = crud.lang_skin(db)
    channel = crud.get_channel(db, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail=i18n.t("api.channel_not_found_short", lang))

    # Security: prevent path traversal
    if "/" in filename or ".." in filename or filename.startswith("_"):
        raise HTTPException(status_code=400, detail=i18n.t("api.invalid_filename", lang))

    file_path = config.AUDIO_DIR / str(channel_id) / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=i18n.t("api.file_not_found", lang))

    try:
        file_path.unlink()
        # Also remove corresponding item from DB if exists
        items = crud.list_items(db, channel_id)
        for item in items:
            if item.filename == filename:
                crud.delete_item(db, item.id)
                break
        return {"ok": True, "message": i18n.t("api.file_deleted", lang)}
    except Exception as exc:  # noqa: BLE001
        logger.error("delete file failed: %s", exc)
        raise HTTPException(status_code=500, detail=i18n.t("api.delete_failed", lang)) from exc


@router.post("/cookies-upload")
async def upload_cookies(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Accept a cookies.txt upload and save it to the data directory."""
    lang, _skin = crud.lang_skin(db)
    if not file.filename:
        raise HTTPException(status_code=400, detail=i18n.t("api.no_file_uploaded", lang))

    # Basic sanity check: must look like a Netscape cookies file.
    first_bytes = await file.read(64)
    await file.seek(0)
    if b"HTTP" not in first_bytes and b"# Netscape" not in first_bytes and b"# HTTP" not in first_bytes:
        # Be lenient – also accept files that just start with a domain line.
        # Only reject obviously wrong types (e.g. images, ZIPs).
        if first_bytes[:4] in (b"\x89PNG", b"\xff\xd8\xff", b"PK\x03\x04"):
            raise HTTPException(status_code=400,
                                detail=i18n.t("api.not_a_cookies_file", lang))

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
        raise HTTPException(status_code=500, detail=i18n.t("api.save_failed", lang)) from exc

    size = dest.stat().st_size
    logger.info("cookies.txt uploaded, %d bytes", size)
    return {"ok": True, "message": i18n.t("api.youtube_access_saved", lang), "bytes": size}


@router.delete("/audio/{channel_id}")
def delete_all_audio_files(channel_id: int, request: Request, db: Session = Depends(get_db)):
    """Delete all audio files from a channel."""
    lang, _skin = crud.lang_skin(db)
    channel = crud.get_channel(db, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail=i18n.t("api.channel_not_found_short", lang))

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

    message = i18n.t("api.files_deleted", lang, count=deleted, s="" if deleted == 1 else "s")
    return {"ok": True, "message": message, "count": deleted}
