"""Serial worker thread.

Pulls queued jobs one at a time, downloads + processes audio, applies backoff
on failure, and enforces the storage guard.
"""
import logging
import shutil
import threading
from datetime import datetime, timedelta
from pathlib import Path

from . import audio, config, crud, downloader, i18n
from .database import session_scope
from .models import Job

logger = logging.getLogger("hoerbox.worker")

_worker_thread = None
_stop_event = threading.Event()
_wake_event = threading.Event()


# --- Storage guard ----------------------------------------------------------
def free_space_mb(path: Path = None) -> int:
    path = path or config.AUDIO_DIR
    try:
        usage = shutil.disk_usage(str(path))
        return usage.free // (1024 * 1024)
    except FileNotFoundError:
        config.ensure_dirs()
        usage = shutil.disk_usage(str(config.AUDIO_DIR))
        return usage.free // (1024 * 1024)


def storage_ok() -> bool:
    return free_space_mb() >= config.STORAGE_WARN_MB


def disk_usage_summary(path: Path = None) -> dict:
    """Used/total/free/percent for the Belegung page's storage bar."""
    path = path or config.AUDIO_DIR
    usage = shutil.disk_usage(str(path))
    used_mb = (usage.total - usage.free) // (1024 * 1024)
    total_mb = usage.total // (1024 * 1024)
    percent = round((usage.total - usage.free) / usage.total * 100, 1)
    return {
        "used_mb": used_mb,
        "total_mb": total_mb,
        "free_mb": usage.free // (1024 * 1024),
        "percent": percent,
    }


def _lang_skin(db) -> tuple:
    settings = crud.get_settings(db)
    return settings.language, settings.skin


def channel_with_most_items(db) -> int:
    """Suggest which channel could be tidied up (has the most items)."""
    best_id, best_count = 0, -1
    for ch in crud.list_channels(db):
        if not ch.active:
            continue
        count = len(crud.list_items(db, ch.id))
        if count > best_count:
            best_id, best_count = ch.id, count
    return best_id


# --- Backoff ----------------------------------------------------------------
# Fixed 2h wait between each of MAX_ATTEMPTS (3) tries — was exponential
# (2**attempt, up to 16h+ for the last of 5 attempts, ~31h total), which
# meant a genuinely broken item sat around for the better part of a day
# before the user found out. 3 tries x 2h = failing loudly within ~4h.
_BACKOFF_HOURS = 2


def _backoff_delay_hours(attempt_count: int) -> int:
    return _BACKOFF_HOURS


def wake() -> None:
    """Signal the worker that new work is available."""
    _wake_event.set()


# --- Job processing ---------------------------------------------------------
def _progress_hook_factory(job_id: int):
    last = {"pct": 0}

    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            if total:
                pct = int(done * 90 / total)  # reserve last 10% for processing
                if pct != last["pct"]:
                    last["pct"] = pct
                    with session_scope() as db:
                        crud.update_job(db, job_id, progress=pct)

    return hook


def _touch_job(job_id: int) -> None:
    """Bump Job.updated_at with no other change — a heartbeat so a long,
    healthy ffmpeg run (see audio.py's _run heartbeat param) doesn't go
    unnoticed by the stuck-job watchdog, which keys off that timestamp."""
    with session_scope() as db:
        crud.update_job(db, job_id)


def process_job(job_id: int) -> None:
    """Process a single job end to end."""
    with session_scope() as db:
        settings = crud.get_settings(db)
        lang, skin = settings.language, settings.skin
        job = crud.get_job(db, job_id)
        if job is None or job.item_id is None:
            return
        item = crud.get_item(db, job.item_id)
        if item is None:
            crud.update_job(db, job_id, status="failed", error_text=i18n.t("worker.entry_missing", lang))
            return
        item_id = item.id
        channel_id = item.channel_id
        # alt_source_url (set by "Andere Quelle suchen") takes priority for
        # the actual download; source_url itself stays untouched so future
        # subscription syncs keep recognizing this item correctly.
        source_url = item.alt_source_url or item.source_url
        sort_index = item.sort_index
        attempt_count = job.attempt_count or 1
        channel = crud.get_channel(db, channel_id)
        channel_name = i18n.channel_label(channel, lang, skin) if channel else str(channel_id)
        audio_channels = settings.audio_channels

    # Storage guard before doing heavy work.
    if not storage_ok():
        with session_scope() as db:
            lang, skin = _lang_skin(db)
            tidy = channel_with_most_items(db)
            tidy_channel = crud.get_channel(db, tidy)
            tidy_name = i18n.channel_label(tidy_channel, lang, skin) if tidy_channel else str(tidy)
            msg = i18n.t("worker.no_space", lang, name=tidy_name)
            crud.update_job(db, job_id, status="failed", error_text=msg, progress=0)
            crud.update_item(db, item_id, status="failed", error_text=msg)
        return

    with session_scope() as db:
        crud.update_item(db, item_id, status="downloading")
        crud.update_job(db, job_id, progress=5)

    tmp_dir = config.AUDIO_DIR / str(channel_id) / "_tmp"
    try:
        result = downloader.download_audio(
            source_url, tmp_dir, progress_hook=_progress_hook_factory(job_id), lang=lang
        )

        # Download done – ffmpeg conversion starts now.
        # progress >= 90 is used by the status endpoint to show the
        # "Umwandlung zu Audio …" message instead of "Wird geladen".
        with session_scope() as db:
            crud.update_job(db, job_id, progress=90)

        # Final output filename.
        slug = downloader.sanitize_filename(result.title)
        final_name = f"{sort_index:02d}_{slug}.mp3"
        final_path = config.AUDIO_DIR / str(channel_id) / final_name

        # Some generic direct-download sources (e.g. Vorleser.net's single-file
        # audiobook downloads) give yt-dlp no duration metadata at all. Probe
        # the actual downloaded file so _ffmpeg_timeout() scales to the real
        # length instead of silently falling back to a flat 1h — too tight for
        # a multi-hour audiobook on slow hardware.
        duration_seconds = result.duration_seconds or audio.get_duration_seconds(result.audio_path)

        audio.process_audio(
            input_path=result.audio_path,
            output_path=final_path,
            title=result.title,
            album=channel_name,
            track=sort_index,
            cover_path=result.thumbnail_path,
            duration_seconds=duration_seconds,
            heartbeat=lambda: _touch_job(job_id),
            channels=audio_channels,
        )

        duration = duration_seconds or audio.get_duration_seconds(final_path)
        size = final_path.stat().st_size

        with session_scope() as db:
            crud.update_item(
                db, item_id,
                title=result.title,
                filename=final_name,
                duration_seconds=duration,
                file_size_bytes=size,
                status="done",
                error_text=None,
            )
            crud.update_job(db, job_id, status="done", progress=100, error_text=None)

        logger.info(
            "job_done", extra={"job_id": job_id, "item_id": item_id,
                                "channel": channel_id, "file": final_name}
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "job_failed job_id=%s item_id=%s error=%s",
            job_id, item_id, exc,
        )
        handle_failure(job_id, item_id, attempt_count, str(exc))
    finally:
        # Clean up temp files.
        try:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def _ensure_real_title(db, item) -> str:
    """If item.title is just a placeholder, try one non-flat metadata lookup
    of the URL that was just attempted before accepting that as final —
    a flat playlist listing (e.g. a SoundCloud set) can leave a track
    titleless even though it has a perfectly good real one. Persists the
    real title if found, so it also fixes the UI, not just this decision."""
    if not downloader.is_placeholder_title(item.title):
        return item.title
    # Same source precedence run_job() uses for the actual download attempt
    # (alt_source_url wins once set) — resolve against whatever just failed.
    resolved = downloader.resolve_real_title(item.alt_source_url or item.source_url)
    if resolved:
        crud.update_item(db, item.id, title=resolved)
        return resolved
    return item.title


def handle_failure(job_id: int, item_id: int, attempt_count: int, error: str) -> None:
    with session_scope() as db:
        lang, _skin = _lang_skin(db)
        user_msg = i18n.t("worker.failed_prefix", lang, error=error)
        item = crud.get_item(db, item_id)
        title = _ensure_real_title(db, item) if item is not None else None
        if attempt_count >= config.MAX_ATTEMPTS:
            if item is not None and downloader.is_placeholder_title(title) and not item.alt_source_url:
                # Never got an escalation attempt below (no real title to
                # search with) — say so explicitly instead of leaving the
                # user staring at a generic failure with no path forward.
                user_msg += i18n.t("worker.no_title_use_search", lang)
            # next_attempt_at must be cleared here, not just left stale from
            # the last backoff round — is_backoff (ui.py._item_view) keys off
            # "next_attempt_at is still in the future", not job.status, so a
            # leftover future timestamp made a terminally-failed item still
            # report itself as backing off (still showing "Andere Quelle
            # suchen" and a bogus "nächster Versuch automatisch um ..." even
            # though nothing will happen at that time anymore).
            crud.update_job(
                db, job_id, status="failed", error_text=user_msg, next_attempt_at=None
            )
            crud.update_item(db, item_id, status="failed", error_text=user_msg)
        else:
            # One retry with the same source, then automatically switch to a
            # different one for the final attempt instead of hammering the
            # same broken URL a second time — reuses the exact ytsearch1:
            # mechanism the user-triggered "Andere Quelle suchen" uses (see
            # api.find_alternative). Only the item's own next (last) attempt
            # gets escalated, not every retry, and not if the item already
            # has an alt_source_url (e.g. a manual "Andere Quelle suchen"
            # click already set one — don't stomp that with a fresh, likely
            # identical ytsearch1 query for the same title). Also skipped
            # entirely when the title is itself just a placeholder ("Ohne
            # Titel" etc, set when the original had no real title at all) —
            # searching YouTube for a literal placeholder string is
            # guaranteed to match an unrelated video that happens to share
            # it, exactly the bug this session found and fixed by hand.
            if (
                attempt_count == config.MAX_ATTEMPTS - 1
                and item is not None
                and not item.alt_source_url
                and not downloader.is_placeholder_title(title)
            ):
                # Include the show/album context (subscription title) in the
                # search, not just the bare episode title — see
                # downloader.default_search_query() for why.
                context_title = crud.item_search_context(db, item)
                query = downloader.default_search_query(title, context_title)
                crud.update_item(
                    db, item_id, alt_source_url=f"ytsearch1:{query}"
                )
            delay = _backoff_delay_hours(attempt_count)
            next_at = datetime.utcnow() + timedelta(hours=delay)
            crud.update_job(
                db, job_id, status="queued", error_text=user_msg,
                next_attempt_at=next_at, progress=0,
            )
            crud.update_item(db, item_id, status="queued", error_text=user_msg)


# --- Stuck-job watchdog ------------------------------------------------------
STUCK_JOB_TIMEOUT_MINUTES = 30


def check_stuck_jobs() -> int:
    """Find 'running' jobs that haven't been touched in over
    STUCK_JOB_TIMEOUT_MINUTES and route them through the normal failure/backoff
    path — same bounded retries and eventual visible "failed" state as any
    other error, instead of resetting silently forever.

    Caveat this can't fix: the worker loop is a single dedicated thread that
    processes one job at a time via a *blocking* call. If that call is
    genuinely wedged forever (e.g. a network read with no timeout at all),
    this only corrects the job's database bookkeeping — the thread itself
    stays blocked and no other job can run until it eventually returns (or
    the process restarts). This catches the case that actually triggered
    building it: a job whose progress silently stopped without ever
    producing an error, left invisible with no error text and no retry
    time shown anywhere in the UI.
    """
    cutoff = datetime.utcnow() - timedelta(minutes=STUCK_JOB_TIMEOUT_MINUTES)
    with session_scope() as db:
        lang, _skin = _lang_skin(db)
        stuck = (
            db.query(Job)
            .filter(Job.status == "running", Job.updated_at < cutoff)
            .all()
        )
        stuck_info = [(j.id, j.item_id, j.attempt_count or 1) for j in stuck]

    for job_id, item_id, attempt_count in stuck_info:
        logger.warning("stuck job detected job_id=%s item_id=%s, resetting", job_id, item_id)
        handle_failure(job_id, item_id, attempt_count, i18n.t("worker.did_not_respond", lang))

    return len(stuck_info)


# --- Worker loop ------------------------------------------------------------
def _loop() -> None:
    logger.info("worker started")
    while not _stop_event.is_set():
        job_id = None
        with session_scope() as db:
            job = crud.claim_next_job(db)
            if job is not None:
                job_id = job.id
        if job_id is not None:
            process_job(job_id)
        else:
            # No work: wait until woken or a short timeout (for backoff retries).
            _wake_event.wait(timeout=30)
            _wake_event.clear()
    logger.info("worker stopped")


def start_worker() -> None:
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return
    _stop_event.clear()
    _worker_thread = threading.Thread(target=_loop, name="hoerbox-worker", daemon=True)
    _worker_thread.start()


def stop_worker() -> None:
    _stop_event.set()
    _wake_event.set()
