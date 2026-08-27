"""HTML routes: GET /, GET /kanal/{n}, GET /einrichtung."""
import base64
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import qrcode
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .. import config, crud, downloader, worker
from ..database import get_db
from ..downloader import _cookies_path
from ..models import Subscription

router = APIRouter()

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _footer_context():
    return {
        "legal_notice": config.LEGAL_NOTICE,
    }


def _fmt_playtime(seconds: int) -> str:
    seconds = seconds or 0
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h:
        return f"{h} Std. {m} Min."
    return f"{m} Min."


@router.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    channels = crud.list_channels(db)
    problem_items = crud.list_problem_items(db)
    unreviewed_items = crud.list_unreviewed_alt_items(db)
    item_counts = crud.items_per_channel(db)
    ctx = {
        "request": request,
        "channels": channels,
        "item_counts": item_counts,
        "problem_count": len(problem_items),
        # Only used when problem_count == 1: naming the actual title/reason
        # beats a bare "1 Titel braucht Aufmerksamkeit." that forces a click
        # through to /bearbeiten just to find out what's wrong.
        "problem_item": (
            {
                "title": problem_items[0].title,
                "hint": crud.short_hint(problem_items[0].error_text),
                "channel_id": problem_items[0].channel_id,
                "id": problem_items[0].id,
            }
            if len(problem_items) == 1
            else None
        ),
        "unreviewed_count": len(unreviewed_items),
        "unreviewed_item": (
            {
                "title": unreviewed_items[0].title,
                "channel_id": unreviewed_items[0].channel_id,
                "id": unreviewed_items[0].id,
            }
            if len(unreviewed_items) == 1
            else None
        ),
        **_footer_context(),
    }
    return templates.TemplateResponse(request, "index.html", ctx)


def _item_view(item, jobs_by_item, is_sub: bool, channel_id: int = None, context_title: str = None) -> dict:
    job = jobs_by_item.get(item.id)
    next_attempt_str = None
    if job and job.next_attempt_at and job.next_attempt_at > datetime.utcnow():
        # next_attempt_at is stored naive-UTC; convert to the configured local TZ.
        local = job.next_attempt_at.replace(tzinfo=UTC).astimezone(config.TZ)
        next_attempt_str = local.strftime("%H:%M")
    return {
        "id": item.id,
        "title": item.title,
        "filename": item.filename,
        "channel_id": channel_id if channel_id is not None else item.channel_id,
        "playtime": _fmt_playtime(item.duration_seconds),
        "status": item.status,
        "error_text": item.error_text,
        "is_backoff": bool(next_attempt_str),
        "next_attempt_str": next_attempt_str,
        "is_sub": is_sub,
        # True regardless of status (including 'done') — an auto-substituted
        # item can be playable and simply wrong; this is the only place that
        # ever surfaces it without checking the database directly.
        "needs_alt_review": bool(item.alt_source_url) and not item.alt_source_reviewed,
        # Prefilled default for the "Selbst suchen" panel: title + show/album
        # context (e.g. the subscription's playlist title), not just the
        # bare title — mirrors what a person doing this search by hand
        # already does. See downloader.default_search_query().
        "search_hint": downloader.default_search_query(item.title, context_title),
    }


@router.get("/kanal/{n}", response_class=HTMLResponse)
def channel_detail(n: int, request: Request, db: Session = Depends(get_db)):
    channel = crud.get_channel(db, n)
    if channel is None:
        raise HTTPException(status_code=404, detail="Diesen Knopf gibt es nicht.")
    items = crud.list_active_items(db, n)
    total_seconds = sum((i.duration_seconds or 0) for i in items if i.status == "done")
    subs = crud.list_subscriptions(db, n)
    abo_enabled = any(s.enabled for s in subs)
    has_abo = len(subs) > 0

    jobs_by_item = crud.latest_jobs_for_items(db, [i.id for i in items])
    sub_titles = {s.id: s.title for s in subs}

    # Group consecutive items sharing a subscription_id into one "block";
    # a lone item (subscription_id is None) is a block of size 1.
    # Note: the per-block list is deliberately named "entries", not "items" —
    # a dict key called "items" shadows Python dict's built-in .items() method
    # when accessed as b.items in Jinja2 (attribute lookup wins over
    # subscript), which silently breaks template rendering.
    blocks = []
    for item in items:
        context_title = sub_titles.get(item.subscription_id)
        if (blocks and item.subscription_id is not None
                and blocks[-1]["subscription_id"] == item.subscription_id):
            blocks[-1]["entries"].append(
                _item_view(item, jobs_by_item, is_sub=True, channel_id=n, context_title=context_title)
            )
        else:
            is_block = item.subscription_id is not None
            blocks.append({
                "subscription_id": item.subscription_id,
                "is_block": is_block,
                "title": (sub_titles.get(item.subscription_id) or item.title) if is_block else None,
                "entries": [_item_view(item, jobs_by_item, is_sub=is_block, channel_id=n, context_title=context_title)],
            })

    ctx = {
        "request": request,
        "channel": channel,
        "blocks": blocks,
        "all_channels": crud.list_channels(db),
        "total_playtime": _fmt_playtime(total_seconds),
        "abo_enabled": abo_enabled,
        "has_abo": has_abo,
        **_footer_context(),
    }
    return templates.TemplateResponse(request, "channel.html", ctx)


def _qr_data_url(text: str) -> str:
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


@router.get("/einrichtung", response_class=HTMLResponse)
def setup(request: Request, db: Session = Depends(get_db)):
    base_url = str(request.base_url).rstrip("/")
    channels = crud.list_channels(db)
    addresses = []
    for ch in channels:
        addr = f"{base_url}/feed/{ch.id}.xml"
        addresses.append({
            "channel": ch,
            "address": addr,
            "qr": _qr_data_url(addr),
        })
    ctx = {
        "request": request,
        "addresses": addresses,
        "cookies_ok": _cookies_path() is not None,
        "max_items_per_list": crud.get_settings(db).max_items_per_list,
        "max_playlist_length": crud.get_settings(db).max_playlist_length,
        "audio_channels": crud.get_settings(db).audio_channels,
        **_footer_context(),
    }
    return templates.TemplateResponse(request, "setup.html", ctx)


@router.get("/bearbeiten", response_class=HTMLResponse)
def bearbeiten(request: Request, db: Session = Depends(get_db)):
    """Selection page: pick a button to open its edit page."""
    channels = crud.list_channels(db)
    ctx = {
        "request": request,
        "channels": channels,
        "problem_channels": crud.channels_with_problems(db),
        "unreviewed_channels": crud.channels_with_unreviewed_alts(db),
        **_footer_context(),
    }
    return templates.TemplateResponse(request, "bearbeiten.html", ctx)


@router.get("/belegung", response_class=HTMLResponse)
def belegung(request: Request, db: Session = Depends(get_db)):
    """Show active (non-parked) files across all channels with option to delete.

    Parked (Bibliothek) items are deliberately excluded here — Belegung is
    the active-occupancy view, /bibliothek is the only place parked content
    is shown.
    """
    channels_data = []
    for ch in crud.list_channels(db):
        channel_dir = config.AUDIO_DIR / str(ch.id)
        active_names = crud.active_filenames(db, ch.id)
        files = []
        total_bytes = 0
        if channel_dir.exists():
            for file in sorted(channel_dir.glob("*.mp3")):
                if file.name.startswith("_"):  # skip temp files
                    continue
                if file.name not in active_names:  # skip parked files
                    continue
                size = file.stat().st_size
                total_bytes += size
                files.append({
                    "filename": file.name,
                    "size_mb": f"{size / (1024*1024):.1f}",
                })

        channels_data.append({
            "channel": ch,
            "files": files,
            "file_count": len(files),
            "total_size_mb": f"{total_bytes / (1024*1024):.1f}",
        })

    ctx = {
        "request": request,
        "channels": channels_data,
        "total_files": sum(ch["file_count"] for ch in channels_data),
        "disk": worker.disk_usage_summary(),
        "storage_warn_mb": config.STORAGE_WARN_MB,
        **_footer_context(),
    }
    return templates.TemplateResponse(request, "belegung.html", ctx)


@router.get("/bibliothek", response_class=HTMLResponse)
def library_page(request: Request, db: Session = Depends(get_db)):
    """Parked content: playlists/tracks kept off the active channels."""
    items = crud.list_library_items(db)
    sub_ids = {i.subscription_id for i in items if i.subscription_id}
    subs = {s.id: s for s in db.query(Subscription).filter(Subscription.id.in_(sub_ids)).all()} if sub_ids else {}

    groups = []
    seen_subs = set()
    for item in items:
        if item.subscription_id and item.subscription_id in seen_subs:
            continue
        item_view = {
            "id": item.id,
            "title": item.title,
            "filename": item.filename,
            "channel": crud.get_channel(db, item.channel_id),
        }
        if item.subscription_id:
            seen_subs.add(item.subscription_id)
            members = [i for i in items if i.subscription_id == item.subscription_id]
            sub = subs.get(item.subscription_id)
            groups.append({
                "is_block": True,
                "subscription_id": item.subscription_id,
                "title": (sub.title if sub and sub.title else item.title),
                "entries": [{
                    "id": m.id,
                    "title": m.title,
                    "filename": m.filename,
                    "channel": crud.get_channel(db, m.channel_id),
                } for m in members],
            })
        else:
            groups.append({"is_block": False, "subscription_id": None, "entries": [item_view]})

    ctx = {
        "request": request,
        "groups": groups,
        "all_channels": crud.list_channels(db),
        **_footer_context(),
    }
    return templates.TemplateResponse(request, "bibliothek.html", ctx)


@router.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request, lines: int = 300):
    """Recent app log lines, for debugging without needing SSH access.

    Reads the same rotating file the app itself logs to (see main.py) —
    survives restarts, capped at ~6MB total across current + 2 backups so
    it never grows unbounded.
    """
    from ..main import LOG_PATH  # local import: main imports this router, avoid a cycle

    lines = max(10, min(lines, 2000))
    content = ""
    if LOG_PATH.exists():
        all_lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
        content = "\n".join(all_lines[-lines:])
    ctx = {
        "request": request,
        "content": content,
        "lines": lines,
        **_footer_context(),
    }
    return templates.TemplateResponse(request, "logs.html", ctx)
