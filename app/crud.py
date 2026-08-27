"""Database operations. Idempotency checks live here."""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import config
from .models import Channel, Item, Job, Settings, Subscription


# --- Channels ---------------------------------------------------------------
def seed_channels(db: Session) -> None:
    """Create the nine fixed channels, and keep name/colour in sync with config.

    Runs on every startup: new channels are created, and existing channels get
    their name/colour/hex refreshed from ``config.CHANNELS`` so that changes to
    the colour definitions take effect automatically after an update — no manual
    database migration required. The user-configurable ``retention`` value is
    preserved.
    """
    for ch in config.CHANNELS:
        existing = db.get(Channel, ch["id"])
        if existing is None:
            db.add(
                Channel(
                    id=ch["id"],
                    name=ch["name"],
                    color=ch["color"],
                    color_hex=ch["color_hex"],
                    retention=config.DEFAULT_RETENTION,
                    active=1,
                )
            )
        else:
            # Refresh display attributes from config (idempotent).
            existing.name = ch["name"]
            existing.color = ch["color"]
            existing.color_hex = ch["color_hex"]
    db.commit()


def get_channel(db: Session, channel_id: int) -> Optional[Channel]:
    return db.get(Channel, channel_id)


def list_channels(db: Session) -> List[Channel]:
    return db.query(Channel).order_by(Channel.id).all()


def channel_has_content(db: Session, channel_id: int) -> bool:
    """True, wenn der Kanal aktive Titel oder ein laufendes Abo hat —
    Grundlage für die Rückfrage beim Deaktivieren."""
    if list_active_items(db, channel_id):
        return True
    return any(s.enabled for s in list_subscriptions(db, channel_id))


def set_channel_active(db: Session, channel_id: int, active: bool) -> None:
    channel = get_channel(db, channel_id)
    if channel is not None:
        channel.active = 1 if active else 0
        db.commit()


# --- Settings -----------------------------------------------------------------
def get_settings(db: Session) -> Settings:
    """Fetch the singleton Settings row, creating it (seeded from the env-var
    default) on first use. Keeps a pre-existing env override alive after
    upgrading, instead of silently resetting to the hardcoded default.
    """
    settings = db.get(Settings, 1)
    if settings is None:
        settings = Settings(
            id=1,
            max_items_per_list=config.MAX_INITIAL_PLAYLIST_ITEMS,
            max_playlist_length=config.DEFAULT_RETENTION,
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def update_settings(db: Session, **fields) -> Settings:
    settings = get_settings(db)
    for key, value in fields.items():
        setattr(settings, key, value)
    db.commit()
    db.refresh(settings)
    return settings


# --- Items ------------------------------------------------------------------
def item_exists(db: Session, channel_id: int, source_url: str) -> Optional[Item]:
    """Idempotency: same source_url in same channel is never loaded twice."""
    return (
        db.query(Item)
        .filter(Item.channel_id == channel_id, Item.source_url == source_url)
        .first()
    )


def next_sort_index(db: Session, channel_id: int) -> int:
    max_idx = (
        db.query(func.max(Item.sort_index))
        .filter(Item.channel_id == channel_id)
        .scalar()
    )
    return (max_idx or 0) + 1


def create_item(
    db: Session,
    channel_id: int,
    source_url: str,
    title: str,
    subscription_id: Optional[int] = None,
) -> Optional[Item]:
    """Create an item unless it already exists (idempotent). Returns None if dup."""
    if item_exists(db, channel_id, source_url):
        return None
    item = Item(
        channel_id=channel_id,
        source_url=source_url,
        title=title,
        sort_index=next_sort_index(db, channel_id),
        status="queued",
        subscription_id=subscription_id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def get_item(db: Session, item_id: int) -> Optional[Item]:
    return db.get(Item, item_id)


def list_items(db: Session, channel_id: int) -> List[Item]:
    return (
        db.query(Item)
        .filter(Item.channel_id == channel_id)
        .order_by(Item.sort_index)
        .all()
    )


def list_active_items(db: Session, channel_id: int) -> List[Item]:
    """Like list_items, but excludes items parked in the Bibliothek."""
    return (
        db.query(Item)
        .filter(Item.channel_id == channel_id, Item.in_library == 0)
        .order_by(Item.sort_index)
        .all()
    )


def list_library_items(db: Session, channel_id: int = None) -> List[Item]:
    """Items currently parked in the Bibliothek, newest-parked first."""
    q = db.query(Item).filter(Item.in_library == 1)
    if channel_id is not None:
        q = q.filter(Item.channel_id == channel_id)
    return q.order_by(Item.library_added_at.desc()).all()


def list_items_by_subscription(
    db: Session, subscription_id: int, channel_id: int = None
) -> List[Item]:
    q = db.query(Item).filter(Item.subscription_id == subscription_id)
    if channel_id is not None:
        q = q.filter(Item.channel_id == channel_id)
    return q.order_by(Item.sort_index).all()


def active_filenames(db: Session, channel_id: int) -> set:
    """Filenames of every active (non-parked) item in a channel."""
    items = list_active_items(db, channel_id)
    return {i.filename for i in items if i.filename}


def short_hint(text: Optional[str], max_len: int = 70) -> str:
    """Trim a stored error_text down to something that fits next to a badge:
    drop the "Ging nicht: " prefix (redundant once shown as a hint) and cap
    long yt-dlp error dumps at max_len."""
    if not text:
        return ""
    if text.startswith("Ging nicht: "):
        text = text[len("Ging nicht: "):]
    if len(text) > max_len:
        text = text[:max_len].rstrip() + "…"
    return text


def channels_with_problems(db: Session) -> dict:
    """channel_id -> {"count": N, "hint": <most common reason, short>}.

    The bare count used to be shown with no explanation at all — a user
    had no way to tell "a few YouTube links died" from "something is
    structurally broken" without clicking into every flagged channel.
    "hint" surfaces the most frequent error_text among that channel's
    problem items (typically the same message repeated, e.g. "Der Inhalt
    ist nicht verfügbar."), so the badge itself carries a reason.

    "cancelled" is deliberately excluded: it's a resolved user action (they
    chose to cancel), not an outstanding problem — counting it produced a
    misleading warning badge for channels with nothing actually wrong.
    """
    rows = (
        db.query(Item.channel_id, Item.error_text, func.count(Item.id))
        .filter(
            Item.error_text.isnot(None),
            Item.in_library == 0,
            Item.status.in_(["failed", "queued"]),
        )
        .group_by(Item.channel_id, Item.error_text)
        .all()
    )
    result: dict = {}
    for channel_id, error_text, count in rows:
        entry = result.setdefault(channel_id, {"count": 0, "hint": "", "_hint_count": 0})
        entry["count"] += count
        if count > entry["_hint_count"]:
            entry["_hint_count"] = count
            entry["hint"] = short_hint(error_text)
    for entry in result.values():
        del entry["_hint_count"]
    return result


def list_problem_items(db: Session) -> List[Item]:
    """Every active item that currently needs the user's attention — both
    permanently failed (attempts exhausted) and still-backing-off items with
    an error, across every channel — for the actionable Start-page notice.

    Used to be 'failed' only, on the theory that a backing-off item would
    sort itself out within a couple of hours. In practice that just meant a
    channel with dozens of items silently retrying every 2h for most of a
    day was only visible as a bare count on /bearbeiten — invisible on the
    page the user actually looks at. Same filter as channels_with_problems()
    for consistency between the two views."""
    return (
        db.query(Item)
        .filter(
            Item.error_text.isnot(None),
            Item.in_library == 0,
            Item.status.in_(["failed", "queued"]),
        )
        .order_by(Item.updated_at.desc())
        .all()
    )


def list_unreviewed_alt_items(db: Session) -> List[Item]:
    """Active items whose audio came from alt_source_url (a substitute
    source) that a human hasn't reviewed/confirmed yet — regardless of
    status. Deliberately not restricted to status in ("failed", "queued")
    like list_problem_items(): a blind substitute can be sitting there
    marked 'done', playable, and simply wrong (the "Gugus" bug this session
    fixed by hand) — this is precisely the case invisible everywhere else."""
    return (
        db.query(Item)
        .filter(
            Item.alt_source_url.isnot(None),
            Item.alt_source_reviewed == 0,
            Item.in_library == 0,
        )
        .order_by(Item.updated_at.desc())
        .all()
    )


def channels_with_unreviewed_alts(db: Session) -> dict:
    """channel_id -> count of list_unreviewed_alt_items(), for a per-channel
    badge on /bearbeiten distinct from channels_with_problems()'s red one."""
    rows = (
        db.query(Item.channel_id, func.count(Item.id))
        .filter(
            Item.alt_source_url.isnot(None),
            Item.alt_source_reviewed == 0,
            Item.in_library == 0,
        )
        .group_by(Item.channel_id)
        .all()
    )
    return {channel_id: count for channel_id, count in rows}


def items_per_channel(db: Session) -> dict:
    """channel_id -> Anzahl aktiver (nicht in der Bibliothek geparkter)
    Titel, für die kleine Belegungszahl unter jedem Kanal-Knopf auf der
    Start-Seite."""
    rows = (
        db.query(Item.channel_id, func.count(Item.id))
        .filter(Item.in_library == 0)
        .group_by(Item.channel_id)
        .all()
    )
    return {channel_id: count for channel_id, count in rows}


def list_done_items(db: Session, channel_id: int) -> List[Item]:
    return (
        db.query(Item)
        .filter(Item.channel_id == channel_id, Item.status == "done", Item.in_library == 0)
        .order_by(Item.sort_index)
        .all()
    )


def update_item(db: Session, item_id: int, **fields) -> Optional[Item]:
    item = db.get(Item, item_id)
    if item is None:
        return None
    for key, value in fields.items():
        setattr(item, key, value)
    item.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return item


def delete_item(db: Session, item_id: int) -> Optional[Item]:
    item = db.get(Item, item_id)
    if item is None:
        return None
    # remove any jobs tied to the item
    db.query(Job).filter(Job.item_id == item_id).delete()
    db.delete(item)
    db.commit()
    return item


def delete_subscription(db: Session, sub_id: int) -> int:
    """Delete a subscription and all its items/jobs (DB rows only — the
    caller is responsible for removing the underlying audio files first,
    since it needs each item's channel_id/filename before they're gone).

    Returns the number of items deleted.
    """
    item_ids = [
        i.id for i in db.query(Item.id).filter(Item.subscription_id == sub_id).all()
    ]
    if item_ids:
        db.query(Job).filter(Job.item_id.in_(item_ids)).delete(synchronize_session=False)
        db.query(Item).filter(Item.id.in_(item_ids)).delete(synchronize_session=False)
    sub = db.get(Subscription, sub_id)
    if sub is not None:
        db.delete(sub)
    db.commit()
    return len(item_ids)


def reorder_items(db: Session, channel_id: int, ordered_ids: List[int]) -> None:
    """Rewrite sort_index according to the given order of item ids."""
    for new_index, item_id in enumerate(ordered_ids, start=1):
        item = db.get(Item, item_id)
        if item is not None and item.channel_id == channel_id:
            item.sort_index = new_index
            item.updated_at = datetime.utcnow()
    db.commit()


def insert_into_block(
    db: Session, channel_id: int, subscription_id: int, source_url: str, title: str
) -> Optional[Item]:
    """Create an item belonging to a subscription, keeping the block contiguous.

    Unlike create_item (which always appends at the very end of the channel),
    this inserts the new item directly after the subscription's existing
    items in this channel — otherwise a new episode synced into a block that
    currently sits in the middle of the list would land after every other
    block, splitting the show into two visually separate groups.
    """
    if item_exists(db, channel_id, source_url):
        return None
    existing = (
        db.query(Item)
        .filter(
            Item.channel_id == channel_id,
            Item.subscription_id == subscription_id,
            Item.in_library == 0,
        )
        .all()
    )
    if existing:
        max_idx = max(i.sort_index for i in existing)
        (
            db.query(Item)
            .filter(Item.channel_id == channel_id, Item.sort_index > max_idx)
            .update({Item.sort_index: Item.sort_index + 1}, synchronize_session=False)
        )
        new_index = max_idx + 1
    else:
        new_index = next_sort_index(db, channel_id)
    item = Item(
        channel_id=channel_id,
        source_url=source_url,
        title=title,
        sort_index=new_index,
        status="queued",
        subscription_id=subscription_id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def reorder_blocks(db: Session, channel_id: int, order: List[dict]) -> None:
    """Rewrite sort_index for a channel's top-level list of blocks/singles.

    order: [{"type": "single", "item_id": int} | {"type": "block", "subscription_id": int}, ...]
    """
    next_index = 1
    for entry in order:
        if entry.get("type") == "single":
            item = db.get(Item, entry.get("item_id"))
            if item is not None and item.channel_id == channel_id and item.subscription_id is None:
                item.sort_index = next_index
                item.updated_at = datetime.utcnow()
                next_index += 1
        elif entry.get("type") == "block":
            members = list_items_by_subscription(db, entry.get("subscription_id"), channel_id)
            for item in members:
                item.sort_index = next_index
                item.updated_at = datetime.utcnow()
                next_index += 1
    db.commit()


def reorder_subscription_items(db: Session, subscription_id: int, ordered_ids: List[int]) -> None:
    """Rewrite sort_index within one block, anchored at its current position
    so the block's place among other blocks/singles in the channel doesn't move.
    """
    items = (
        db.query(Item)
        .filter(Item.subscription_id == subscription_id)
        .order_by(Item.sort_index)
        .all()
    )
    if not items:
        return
    base = items[0].sort_index
    valid_ids = {i.id for i in items}
    for offset, item_id in enumerate(ordered_ids):
        if item_id in valid_ids:
            item = db.get(Item, item_id)
            item.sort_index = base + offset
            item.updated_at = datetime.utcnow()
    db.commit()


def latest_job_for_item(db: Session, item_id: int) -> Optional[Job]:
    return (
        db.query(Job)
        .filter(Job.item_id == item_id)
        .order_by(Job.id.desc())
        .first()
    )


def latest_jobs_for_items(db: Session, item_ids: List[int]) -> dict:
    """Map item_id -> its most recent Job, in one query."""
    if not item_ids:
        return {}
    jobs = (
        db.query(Job)
        .filter(Job.item_id.in_(item_ids))
        .order_by(Job.item_id, Job.id.desc())
        .all()
    )
    latest = {}
    for job in jobs:
        if job.item_id not in latest:
            latest[job.item_id] = job
    return latest


# --- Jobs -------------------------------------------------------------------
def create_job(db: Session, item_id: int) -> Job:
    job = Job(item_id=item_id, status="queued", progress=0, attempt_count=0)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, job_id: int) -> Optional[Job]:
    return db.get(Job, job_id)


def update_job(db: Session, job_id: int, **fields) -> Optional[Job]:
    job = db.get(Job, job_id)
    if job is None:
        return None
    for key, value in fields.items():
        setattr(job, key, value)
    job.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(job)
    return job


def queue_position(db: Session, job: Job) -> int:
    """1-based position of a queued job in the waiting line (1 = next up)."""
    if job.status != "queued":
        return 0
    ahead = (
        db.query(Job)
        .filter(Job.status == "queued")
        .filter(Job.created_at < job.created_at)
        .count()
    )
    return ahead + 1


def worker_busy(db: Session) -> bool:
    """True if a job is currently being processed."""
    return db.query(Job).filter(Job.status == "running").count() > 0


def reset_running_jobs(db: Session) -> int:
    """On startup: put running jobs back to queued so they are retried."""
    jobs = db.query(Job).filter(Job.status == "running").all()
    count = 0
    for job in jobs:
        job.status = "queued"
        job.progress = 0
        job.updated_at = datetime.utcnow()
        if job.item_id:
            item = db.get(Item, job.item_id)
            if item and item.status == "downloading":
                item.status = "queued"
        count += 1
    db.commit()
    return count


def claim_next_job(db: Session) -> Optional[Job]:
    """Pick the next queued job whose next_attempt_at is due; mark it running.
    
    Skips jobs with cancelled items.
    """
    now = datetime.utcnow()
    while True:
        job = (
            db.query(Job)
            .filter(Job.status == "queued")
            .filter((Job.next_attempt_at == None) | (Job.next_attempt_at <= now))  # noqa: E711
            .order_by(Job.created_at)
            .first()
        )
        if job is None:
            return None
        
        # Skip jobs whose item was cancelled
        if job.item_id:
            item = db.get(Item, job.item_id)
            if item and item.status == "cancelled":
                job.status = "cancelled"
                job.updated_at = now
                db.commit()
                continue  # try next job
        
        job.status = "running"
        job.attempt_count = (job.attempt_count or 0) + 1
        job.updated_at = now
        db.commit()
        db.refresh(job)
        return job


# --- Subscriptions ----------------------------------------------------------
def get_subscription(db: Session, sub_id: int) -> Optional[Subscription]:
    return db.get(Subscription, sub_id)


def item_search_context(db: Session, item: Item) -> Optional[str]:
    """The show/album title to combine with an item's own title when
    searching for a replacement source (see downloader.default_search_query)
    — the subscription's title if the item belongs to one, else None for a
    standalone item with no such context."""
    if not item.subscription_id:
        return None
    sub = get_subscription(db, item.subscription_id)
    return sub.title if sub else None


def subscription_exists(
    db: Session, channel_id: int, source_url: str
) -> Optional[Subscription]:
    return (
        db.query(Subscription)
        .filter(
            Subscription.channel_id == channel_id,
            Subscription.source_url == source_url,
        )
        .first()
    )


def create_subscription(
    db: Session, channel_id: int, source_url: str, sub_type: str,
    interval_hours: int = None, title: Optional[str] = None,
) -> Subscription:
    existing = subscription_exists(db, channel_id, source_url)
    if existing:
        return existing
    sub = Subscription(
        channel_id=channel_id,
        source_url=source_url,
        type=sub_type,
        interval_hours=interval_hours or config.DEFAULT_INTERVAL_HOURS,
        enabled=1,
        title=title,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def subscription_item_exists(db: Session, subscription_id: int, source_url: str) -> Optional[Item]:
    """Idempotency scoped to the subscription, not the channel — stays correct
    even after an episode has been reassigned to a different channel or
    parked in the Bibliothek (item_exists() would miss it in both cases and
    let the next sync re-create a duplicate).
    """
    return (
        db.query(Item)
        .filter(Item.subscription_id == subscription_id, Item.source_url == source_url)
        .first()
    )


def list_subscriptions(db: Session, channel_id: int = None) -> List[Subscription]:
    q = db.query(Subscription)
    if channel_id is not None:
        q = q.filter(Subscription.channel_id == channel_id)
    return q.order_by(Subscription.id).all()


def list_enabled_subscriptions(db: Session) -> List[Subscription]:
    return (
        db.query(Subscription)
        .filter(Subscription.enabled == 1)
        .order_by(Subscription.id)
        .all()
    )


def set_subscription_enabled(
    db: Session, channel_id: int, enabled: bool
) -> List[Subscription]:
    subs = list_subscriptions(db, channel_id)
    for sub in subs:
        sub.enabled = 1 if enabled else 0
    db.commit()
    return subs


def set_subscription_enabled_by_id(db: Session, sub_id: int, enabled: bool) -> Optional[Subscription]:
    """Like set_subscription_enabled, but for exactly one subscription — needed
    for parking/reassigning a single block, since the channel-wide abo switch
    would otherwise affect every subscription in that channel.
    """
    sub = db.get(Subscription, sub_id)
    if sub is None:
        return None
    sub.enabled = 1 if enabled else 0
    db.commit()
    db.refresh(sub)
    return sub


def update_subscription(db: Session, sub_id: int, **fields) -> Optional[Subscription]:
    sub = db.get(Subscription, sub_id)
    if sub is None:
        return None
    for key, value in fields.items():
        setattr(sub, key, value)
    db.commit()
    db.refresh(sub)
    return sub


def _oldest_first_eviction_units(items: List[Item]) -> List[dict]:
    """Group items into oldest-first 'eviction units' for retention: a lone
    standalone item is its own unit, but an item belonging to a subscription
    pulls its *entire* block (every member of that subscription in `items`)
    into one unit — so retention always keeps or moves a whole playlist,
    never splits it.

    Each unit: {"kind": "single"|"block", "subscription_id": int|None, "item_ids": [...]}.
    """
    sorted_items = sorted(items, key=lambda i: i.created_at)
    units: List[dict] = []
    seen_subs = set()
    for item in sorted_items:
        if item.subscription_id:
            if item.subscription_id in seen_subs:
                continue
            seen_subs.add(item.subscription_id)
            members = [i for i in items if i.subscription_id == item.subscription_id]
            units.append({
                "kind": "block",
                "subscription_id": item.subscription_id,
                "item_ids": [m.id for m in members],
            })
        else:
            units.append({"kind": "single", "subscription_id": None, "item_ids": [item.id]})
    return units


def plan_retention_eviction(db: Session, channel_id: int, incoming_count: int) -> List[dict]:
    """Oldest-first whole-playlist/standalone units that would need to move
    to the Bibliothek to fit `incoming_count` more items within the global
    max_playlist_length setting. Empty list = no eviction needed.

    Used to ask for confirmation before an interactive add would otherwise
    silently make room; see also apply_retention(), which does the same
    kind of eviction automatically for background subscription syncs.
    """
    limit = get_settings(db).max_playlist_length
    done_items = list_done_items(db, channel_id)
    overflow = (len(done_items) + incoming_count) - limit
    if overflow <= 0:
        return []
    plan = []
    freed = 0
    for unit in _oldest_first_eviction_units(done_items):
        if freed >= overflow:
            break
        plan.append(unit)
        freed += len(unit["item_ids"])
    return plan


def apply_retention(db: Session, channel_id: int) -> List[Item]:
    """Keep only the newest max_playlist_length done items in a channel;
    move (never delete) the rest to the Bibliothek, as whole playlists —
    used by the automatic background subscription sync, where no user is
    present to confirm (see plan_retention_eviction() for the interactive,
    confirm-before-acting counterpart used when adding content by hand).

    Returns the list of items that were parked.
    """
    channel = db.get(Channel, channel_id)
    if channel is None:
        return []
    limit = get_settings(db).max_playlist_length
    done_items = list_done_items(db, channel_id)
    overflow = len(done_items) - limit
    if overflow <= 0:
        return []
    parked: List[Item] = []
    freed = 0
    for unit in _oldest_first_eviction_units(done_items):
        if freed >= overflow:
            break
        for item_id in unit["item_ids"]:
            item = db.get(Item, item_id)
            if item is not None:
                item.in_library = 1
                item.library_added_at = datetime.utcnow()
                parked.append(item)
        freed += len(unit["item_ids"])
    db.commit()
    return parked
