"""RSS 2.0 generator (one per channel), with stable GUIDs.

The feed is the machine-facing output consumed by the device; user-facing UI
text never mentions it by name.
"""
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from feedgen.feed import FeedGenerator
from sqlalchemy.orm import Session

from . import config, crud, i18n


def stable_guid(source_url: str) -> str:
    """Deterministic GUID based on the source URL (survives re-ordering)."""
    return hashlib.sha1(source_url.encode("utf-8")).hexdigest()


def _fmt_duration(seconds: Optional[int]) -> str:
    if not seconds:
        return "00:00:00"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_feed_xml(db: Session, channel_id: int, base_url: str) -> str:
    """Build the RSS 2.0 XML string for one channel.

    base_url e.g. "http://192.168.1.50:8080" (no trailing slash).
    """
    base_url = base_url.rstrip("/")
    lang, skin = crud.lang_skin(db)
    channel = crud.get_channel(db, channel_id)
    ch_name = i18n.channel_label(channel, lang, skin) if channel else str(channel_id)

    fg = FeedGenerator()
    fg.load_extension("podcast")
    fg.title(i18n.t("feed.channel_title", lang, name=ch_name))
    fg.link(href=f"{base_url}/feed/{channel_id}.xml", rel="self")
    fg.description(i18n.t("feed.channel_description", lang, id=channel_id))
    fg.language(lang)

    cover_url = f"{base_url}/static/cover.png"
    fg.image(url=cover_url, title=i18n.t("feed.channel_title", lang, name=ch_name), link=base_url)
    fg.podcast.itunes_image(cover_url)

    items = crud.list_done_items(db, channel_id)
    # feedgen prepends entries, so add in reverse to keep sort_index order.
    for item in sorted(items, key=lambda i: i.sort_index, reverse=True):
        if not item.filename:
            continue
        fe = fg.add_entry()
        fe.title(item.title)
        guid = stable_guid(item.source_url)
        fe.guid(guid, permalink=False)
        enclosure_url = f"{base_url}/audio/{channel_id}/{item.filename}"
        length = str(item.file_size_bytes or 0)
        fe.enclosure(enclosure_url, length, "audio/mpeg")
        fe.podcast.itunes_duration(_fmt_duration(item.duration_seconds))
        pub = item.created_at or datetime.utcnow()
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=UTC)
        fe.pubDate(pub)

    return fg.rss_str(pretty=True).decode("utf-8")


def write_feed_file(db: Session, channel_id: int, base_url: str) -> Path:
    """Write the feed to disk (optional cache). Returns the path."""
    xml = build_feed_xml(db, channel_id, base_url)
    out = config.AUDIO_DIR / str(channel_id) / "feed.xml"
    out.write_text(xml, encoding="utf-8")
    return out
