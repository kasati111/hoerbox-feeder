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
    settings = crud.get_settings(db)
    lang, skin = settings.language, settings.skin
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

    # list_done_items() is already sort_index-ascending (oldest first).
    # feedgen's add_entry() prepends by default, so adding in that order
    # flips it to newest-first in the final XML -- the RSS/podcast
    # convention (pubDate descending) that generic podcast apps assume when
    # they treat "first <item>" as "newest episode".
    #
    # A device that just plays through the feed in document order (rather
    # than letting a person pick an episode) ends up playing newest-first
    # too, which is backwards for a story told in sequential episodes --
    # hence "chronological" (oldest first in the document, matching sort_index
    # order) as the default. "newest_first" keeps the RSS-convention behavior
    # for setups that rely on it (e.g. a generic podcast app showing this
    # feed's latest episode at the top). See Settings.feed_order / the Setup
    # page.
    items = crud.list_done_items(db, channel_id)
    if settings.feed_order != "newest_first":
        items = list(reversed(items))
    for item in items:
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
