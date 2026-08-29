"""APScheduler-based periodic updater.

Default interval 6h per subscription, preferred nightly window, start offset
between subscriptions. Each run: list source -> compare with DB -> queue new ->
apply retention -> rewrite output.
"""
import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from . import config, crud, downloader, feed, worker
from .database import session_scope

logger = logging.getLogger("hoerbox.scheduler")

_scheduler = None


def sync_subscription(sub_id: int) -> None:
    """Run one subscription: fetch source, queue new items, apply retention."""
    if not worker.storage_ok():
        logger.warning("storage low, skipping subscription %s", sub_id)
        return

    with session_scope() as db:
        sub = crud.get_subscription(db, sub_id)
        if sub is None or not sub.enabled:
            return
        channel_id = sub.channel_id
        source_url = sub.source_url
        lang = crud.get_settings(db).language
        crud.update_subscription(db, sub_id, last_run_at=datetime.utcnow())

    try:
        info = downloader.analyze(source_url, lang)
    except Exception as exc:  # noqa: BLE001
        logger.error("subscription %s analyze failed: %s", sub_id, exc)
        return

    new_count = 0
    with session_scope() as db:
        limit = crud.get_settings(db).max_items_per_list
        entries = info.entries[:limit]
        for entry in entries:
            # Idempotency scoped to the subscription (not the channel) — stays
            # correct even if an episode was individually reassigned to a
            # different channel or parked in the Bibliothek.
            if crud.subscription_item_exists(db, sub_id, entry.url):
                continue
            if crud.is_subscription_url_excluded(db, sub_id, entry.url):
                continue
            item = crud.insert_into_block(
                db, channel_id, sub_id, entry.url, entry.title
            )
            if item is not None:
                crud.create_job(db, item.id)
                new_count += 1

    if new_count:
        worker.wake()

    # Retention: park (never delete) oldest playlists/items beyond the limit.
    with session_scope() as db:
        crud.apply_retention(db, channel_id)

    with session_scope() as db:
        crud.update_subscription(db, sub_id, last_success_at=datetime.utcnow())
        try:
            feed.write_feed_file(db, channel_id, config.FEED_BASE_URL)
        except Exception as exc:  # noqa: BLE001
            logger.warning("feed write failed for channel %s: %s", channel_id, exc)

    logger.info("subscription_synced sub_id=%s new=%s", sub_id, new_count)


def _schedule_all_subscriptions() -> None:
    """(Re)register jobs for every enabled subscription with a start offset."""
    with session_scope() as db:
        subs = crud.list_enabled_subscriptions(db)
        sub_specs = [(s.id, s.interval_hours or config.DEFAULT_INTERVAL_HOURS)
                     for s in subs]

    for sub_id, interval in sub_specs:
        job_id = f"sub_{sub_id}"
        offset_minutes = sub_id * config.SUBSCRIPTION_STAGGER_MINUTES
        _scheduler.add_job(
            sync_subscription,
            trigger=IntervalTrigger(hours=interval, timezone=config.TZ),
            args=[sub_id],
            id=job_id,
            replace_existing=True,
            next_run_time=_first_run_time(offset_minutes),
            misfire_grace_time=3600,
        )


def _first_run_time(offset_minutes: int) -> datetime:
    from datetime import timedelta
    return datetime.now(config.TZ) + timedelta(minutes=offset_minutes)


def refresh_jobs() -> None:
    """Re-read subscriptions and update scheduled jobs (call after changes)."""
    if _scheduler is None:
        return
    _schedule_all_subscriptions()


def update_ytdlp() -> None:
    """Auto-update yt-dlp daily to prevent breakage from upstream changes."""
    import subprocess
    logger.info("ytdlp_update_start")
    try:
        subprocess.check_call(
            ["pip", "install", "--upgrade", "--no-cache-dir", "yt-dlp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        new_version = downloader.get_yt_dlp_version()
        logger.info("ytdlp_update_ok version=%s", new_version)
    except subprocess.CalledProcessError as exc:
        logger.error("ytdlp_update_failed error=%s", exc.stderr.decode())
    except Exception as exc:  # noqa: BLE001
        logger.error("ytdlp_update_failed error=%s", exc)


def weekly_selftest() -> None:
    """Download a known public-domain file to verify the toolchain works."""
    import tempfile
    from pathlib import Path

    logger.info("selftest_start url=%s", config.SELFTEST_URL)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            downloader.download_audio(config.SELFTEST_URL, Path(tmp))
        logger.info("selftest_ok")
    except Exception as exc:  # noqa: BLE001
        logger.error("selftest_failed error=%s", exc)


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone=config.TZ)
    _schedule_all_subscriptions()
    # Daily yt-dlp update, every day 02:00 Europe/Berlin.
    from apscheduler.triggers.cron import CronTrigger
    _scheduler.add_job(
        update_ytdlp,
        trigger=CronTrigger(hour=2, minute=0, timezone=config.TZ),
        id="daily_ytdlp_update",
        replace_existing=True,
    )
    # Weekly self-test, Monday 03:00 Europe/Berlin.
    _scheduler.add_job(
        weekly_selftest,
        trigger=CronTrigger(day_of_week="mon", hour=3, minute=0, timezone=config.TZ),
        id="weekly_selftest",
        replace_existing=True,
    )
    # Stuck-job watchdog: check every 10 min for 'running' jobs that haven't
    # made progress in STUCK_JOB_TIMEOUT_MINUTES (30) and route them through
    # the normal failure/backoff path instead of leaving them silently stuck.
    _scheduler.add_job(
        worker.check_stuck_jobs,
        trigger=IntervalTrigger(minutes=10, timezone=config.TZ),
        id="stuck_job_watchdog",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("scheduler started")
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
