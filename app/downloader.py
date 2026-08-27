"""yt-dlp integration.

yt-dlp is used exclusively as a Python library (import yt_dlp) — never as a
shell command.
"""
import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yt_dlp

logger = logging.getLogger("hoerbox.downloader")


@dataclass
class SourceEntry:
    """A single resolvable audio source (one future item)."""
    url: str
    title: str


@dataclass
class SourceInfo:
    """Result of analysing a user-provided URL."""
    kind: str  # 'single' | 'youtube_playlist' | 'youtube_channel' | 'podcast'
    is_series: bool
    entries: List[SourceEntry] = field(default_factory=list)
    list_title: Optional[str] = None  # playlist/show title, for block headers


@dataclass
class SearchCandidate:
    """One result from search_candidates() — enough for a human to visually
    pick the right one (thumbnail/title/uploader/length) without downloading
    anything, unlike the blind ytsearch1: used by the automatic/legacy
    "Andere Quelle suchen" path."""
    url: str
    title: str
    uploader: Optional[str]
    duration_seconds: Optional[int]
    thumbnail_url: Optional[str]


# Titles that mean "yt-dlp/spotdl had nothing real to report", set as a
# fallback in a few places below (SourceEntry title, DownloadResult title via
# _resolve_spotify). Searching YouTube for one of these literally (e.g.
# "ytsearch1:Ohne Titel") is guaranteed to match an arbitrary unrelated video
# that happens to share the same placeholder as its real title — this is
# exactly the "Gugus" bug found this session, discovered only by manually
# checking the database after the fact.
_PLACEHOLDER_TITLES = {"ohne titel", "unbekannt", "untitled", "unknown", "n/a", "na", ""}


def is_placeholder_title(title: Optional[str]) -> bool:
    return (title or "").strip().casefold() in _PLACEHOLDER_TITLES


def default_search_query(title: str, context_title: Optional[str] = None) -> str:
    """Build the default search query for an item: its own title plus its
    show/album context (typically the subscription's playlist title), e.g.
    "Kleine Festrede" + "Füenf - Ein Fest für König Gugubo" instead of just
    "Kleine Festrede" alone. Mirrors what a person doing this search by hand
    already does — the bare episode title alone often matches an unrelated,
    same-named upload; the show name reliably steers toward the right one.

    Parenthetical qualifiers ("(Full Album)", "(Urgeschichten und
    Höhlensongs)") are stripped from context_title first: on real playlist
    titles seen this session, they were consistently marketing/format noise
    rather than identifying information, and only add query length without
    adding precision.
    """
    query = (title or "").strip()
    if context_title:
        cleaned = re.sub(r"\s*\([^)]*\)", "", context_title).strip()
        if cleaned and cleaned.casefold() not in query.casefold():
            query = f"{query} {cleaned}".strip()
    return query[:100]


def _cookies_path() -> Optional[str]:
    """Return path to cookies.txt if it exists in the data directory.

    Lives under DB_DIR (/data/db), not the bare DATA_DIR (/data) — DB_DIR is
    the one actually mounted as a persistent named volume in
    docker-compose.yml (hoerbert_db). A file written straight to /data sits
    on the container's own writable layer and silently vanishes on every
    `docker compose up` that recreates the container (i.e. on every code
    update) — cookies.txt needs to survive exactly that.
    """
    from . import config
    p = config.DB_DIR / "cookies.txt"
    if p.exists() and p.stat().st_size > 0:
        return str(p)
    return None


def _node_path() -> Optional[str]:
    """Find the node binary for yt-dlp's JS challenge solver."""
    import shutil
    # Standard system paths first, then common install locations.
    for candidate in ("node", "/usr/bin/node", "/usr/local/bin/node"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def _base_ydl_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": False,
        "ignoreerrors": True,
        "extract_flat": False,
        # Prevent cache-file conflicts when analyze() and download_audio() run
        # at the same time (two parallel YoutubeDL instances).
        "no_cache_dir": True,
        # Without an explicit socket timeout, a stalled connection (server
        # accepts the connection but stops sending data) blocks yt-dlp's
        # network read forever — and with it the single worker thread, since
        # yt-dlp runs in-process here rather than as a subprocess we could
        # kill. This bounds that: a dead socket now raises after 30s instead
        # of hanging indefinitely.
        "socket_timeout": 30,
    }
    # If a cookies.txt is present (exported from a logged-in browser), use it.
    # This bypasses YouTube's bot-detection on server IPs.
    cookies = _cookies_path()
    if cookies:
        opts["cookiefile"] = cookies
    # yt-dlp >= 2026 needs an external JS runtime to solve YouTube's n-challenge.
    # Without it every YouTube URL fails. Point explicitly to node so yt-dlp
    # finds it even when it's not on the default PATH.
    node = _node_path()
    if node:
        # js_runtimes expects a dict: {runtime_name: {config}}
        # 'path' points yt-dlp to the node binary when it's not on the system PATH.
        opts["js_runtimes"] = {"node": {"path": node}}
    return opts


def get_yt_dlp_version() -> str:
    try:
        return yt_dlp.version.__version__
    except Exception:  # pragma: no cover
        return "unbekannt"


# ---------------------------------------------------------------------------
# Spotify support
# ---------------------------------------------------------------------------

def _is_spotify(url: str) -> bool:
    """Return True if *url* points to a Spotify track, album, or playlist."""
    return "open.spotify.com" in url


def _normalize_spotify_url(url: str) -> str:
    """Strip the optional intl-XX locale segment from a Spotify URL.

    Spotify's web player sometimes generates locale-prefixed URLs such as:
        https://open.spotify.com/intl-de/track/2QnAg9u1MmoNpm4O7zrYA4
    spotdl only accepts the canonical form without the locale prefix:
        https://open.spotify.com/track/2QnAg9u1MmoNpm4O7zrYA4
    """
    return re.sub(r"(open\.spotify\.com)/intl-[a-z]+/", r"\1/", url)


# ---------------------------------------------------------------------------
# spotdl singleton – SpotifyClient can only be initialized once per process.
# ---------------------------------------------------------------------------
_SPOTDL_CLIENT_ID = "5f573c9620494bae87890c0f08a60293"
_SPOTDL_CLIENT_SECRET = "212476d9b0f3472eaa762d90b19b0ba8"
_spotdl_instance = None
_spotdl_lock = threading.Lock()


def _get_spotdl():
    """Return a cached Spotdl instance (singleton, thread-safe)."""
    global _spotdl_instance
    if _spotdl_instance is None:
        with _spotdl_lock:
            if _spotdl_instance is None:
                from spotdl import Spotdl  # lazy – optional dependency
                _spotdl_instance = Spotdl(
                    client_id=_SPOTDL_CLIENT_ID,
                    client_secret=_SPOTDL_CLIENT_SECRET,
                    headless=True,
                )
    return _spotdl_instance


def _resolve_spotify(spotify_url: str) -> "SourceInfo":
    """Resolve a Spotify URL to a SourceInfo by using spotdl for metadata.

    spotdl is used **only** to query the Spotify API (track name, artist,
    etc.).  The actual audio download stays with our own yt-dlp instance
    (which has cookies + js_runtimes correctly configured) via a YouTube
    search URL of the form ``ytsearch1:artist - title``.

    This avoids all issues with spotdl's internal yt-dlp instance, which
    does not know about our Node.js path or our cookies file.
    """
    try:
        from spotdl import Spotdl  # noqa: F401 – ensure import available
    except ImportError:
        raise RuntimeError(
            "spotdl ist nicht installiert. "
            "Bitte 'pip install spotdl' ausführen."
        )

    # Spotify web links may carry an intl-XX locale prefix that spotdl
    # does not understand → strip it before querying the Spotify API.
    spotify_url = _normalize_spotify_url(spotify_url)
    logger.info("Spotify-Adresse auflösen: %s", spotify_url)
    try:
        spotdl_client = _get_spotdl()
        songs = spotdl_client.search([spotify_url])
    except Exception as exc:
        raise RuntimeError(
            f"Spotify konnte nicht gelesen werden: {exc}"
        ) from exc

    if not songs:
        raise RuntimeError("Kein passender Inhalt auf Spotify gefunden.")

    entries: List[SourceEntry] = []
    for song in songs:
        artist = getattr(song, "artist", "") or ""
        name = getattr(song, "name", "") or "Ohne Titel"
        query = f"{artist} - {name}" if artist else name
        # Use yt-dlp's native YouTube search extractor.
        # download_audio() calls _base_ydl_opts() which provides cookies
        # and js_runtimes, so this search + download works correctly.
        entries.append(SourceEntry(url=f"ytsearch1:{query}", title=query))

    # Determine kind and is_series from the Spotify URL structure.
    if "/playlist/" in spotify_url or "/album/" in spotify_url:
        kind = "youtube_playlist"  # reuse for subscription compatibility
        is_series = True
    else:
        kind = "single"
        is_series = len(entries) > 1

    return SourceInfo(kind=kind, is_series=is_series, entries=entries)


def _classify(info: dict, url: str) -> str:
    """Determine the source type from extracted info."""
    extractor = (info.get("extractor_key") or info.get("extractor") or "").lower()
    itype = info.get("_type")
    if itype == "playlist" or info.get("entries") is not None:
        if "youtube" in extractor:
            # A channel URL yields a playlist too; distinguish loosely.
            if "/channel/" in url or "/@" in url or "/c/" in url or "/user/" in url:
                return "youtube_channel"
            return "youtube_playlist"
        # Generic feed with multiple entries -> treat as podcast series.
        return "podcast"
    return "single"


def analyze(url: str) -> SourceInfo:
    """Analyse a URL and expand playlists into individual entries.

    Spotify URLs are resolved via spotdl (metadata only); all other URLs go
    through yt-dlp's flat extraction.
    """
    if _is_spotify(url):
        return _resolve_spotify(_normalize_spotify_url(url))

    opts = _base_ydl_opts()
    opts["extract_flat"] = "in_playlist"
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if info is None:
        raise RuntimeError("Die Adresse konnte nicht gelesen werden.")

    kind = _classify(info, url)
    entries: List[SourceEntry] = []
    list_title: Optional[str] = None

    raw_entries = info.get("entries")
    if raw_entries:
        for entry in raw_entries:
            if not entry:
                continue
            entry_url = _normalize_entry_url(entry)
            if not entry_url:
                continue
            entries.append(
                SourceEntry(
                    url=entry_url,
                    title=entry.get("title") or "Ohne Titel",
                )
            )
        is_series = True
        list_title = info.get("title")
    else:
        entries.append(
            SourceEntry(
                url=info.get("webpage_url") or url,
                title=info.get("title") or "Ohne Titel",
            )
        )
        is_series = False

    return SourceInfo(kind=kind, is_series=is_series, entries=entries, list_title=list_title)


def _normalize_entry_url(entry: dict) -> Optional[str]:
    """Resolve a flat-extraction entry dict to a full, directly usable URL.
    extract_flat may give bare video ids for YouTube results instead of a
    full URL — build one so callers never have to special-case it. Shared
    by analyze() and search_candidates()."""
    entry_url = entry.get("url") or entry.get("webpage_url") or entry.get("id")
    if not entry_url:
        return None
    if not str(entry_url).startswith("http"):
        entry_url = f"https://www.youtube.com/watch?v={entry_url}"
    return entry_url


def resolve_real_title(url: Optional[str]) -> Optional[str]:
    """One-off, non-flat metadata lookup for a single URL — used to recover a
    real title that a flat playlist listing didn't provide (confirmed live:
    SoundCloud sets give every entry title=None under analyze()'s
    extract_flat="in_playlist", but a plain extract_info() of that same
    entry URL resolves it fine, including for the api-v2.soundcloud.com
    track-id fallback URL form some entries get). Returns None if the title
    is genuinely unavailable (dead link, private video, ...) or itself just
    another placeholder."""
    if not url or url.startswith("ytsearch"):
        return None
    opts = _base_ydl_opts()
    opts["noplaylist"] = True
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        return None
    if not info:
        return None
    title = info.get("title")
    return None if is_placeholder_title(title) else title


def search_candidates(query: str, limit: int = 5) -> List[SearchCandidate]:
    """Search YouTube for *query* and return up to *limit* lightweight
    candidates (title/uploader/duration/thumbnail, no per-candidate
    download) for a human to visually pick from — the manual, verifiable
    counterpart to the blind ytsearch1: used by the automatic escalation and
    the legacy "Andere Quelle suchen". yt-dlp may return fewer than *limit*
    results; that's not an error, just return whatever came back. Sorted by
    title similarity to *query* (cheap stdlib heuristic, not AI — see the
    session's plan notes on why an LLM scorer wasn't worth it here) so the
    most plausible match surfaces first without deciding anything on its
    own; a human still picks.
    """
    from difflib import SequenceMatcher

    opts = _base_ydl_opts()
    opts["extract_flat"] = "in_playlist"
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)

    candidates: List[SearchCandidate] = []
    for entry in (info or {}).get("entries") or []:
        if not entry:
            continue
        url = _normalize_entry_url(entry)
        if not url:
            continue
        thumbnail_url = entry.get("thumbnail")
        if not thumbnail_url:
            thumbs = entry.get("thumbnails") or []
            thumbnail_url = thumbs[0].get("url") if thumbs else None
        duration = entry.get("duration")
        candidates.append(SearchCandidate(
            url=url,
            title=entry.get("title") or "Ohne Titel",
            uploader=entry.get("uploader") or entry.get("channel"),
            duration_seconds=int(duration) if duration else None,
            thumbnail_url=thumbnail_url,
        ))

    candidates.sort(
        key=lambda c: SequenceMatcher(None, c.title.casefold(), query.casefold()).ratio(),
        reverse=True,
    )
    return candidates


_UMLAUT_TRANSLIT = str.maketrans({
    "ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss",
})


def sanitize_filename(title: str, max_len: int = 50) -> str:
    """Make a filename-safe, pure-ASCII slug from a title.

    Must stay ASCII end to end: this string becomes a path segment in the
    RSS enclosure URL the playback device downloads from. German umlauts are
    transliterated first (readability), then anything else non-ASCII —
    any other script, emoji, stray glitch bytes — is dropped outright via
    the ascii/"ignore" round-trip below, rather than passed through raw.
    Some device firmware percent-encodes the URL and then naively derives a
    local filename by replacing "%" with "_" without decoding first, turning
    any non-ASCII byte into a literal, unplayable "_XX" sequence — this
    happened for real with German umlauts, and nothing guarantees umlauts
    are the only script that would trigger it (a Japanese- or
    Arabic-titled podcast would hit the exact same bug otherwise).

    max_len bounds this slug; the full on-disk filename adds a two-digit
    sort prefix and ".mp3" (see worker.py). Kept well under typical 255-byte
    filesystem limits, with headroom for whatever directory/UUID prefix the
    device's own SD-card layout adds on top (observed to be ~80+ chars).
    """
    title = title.translate(_UMLAUT_TRANSLIT)
    title = title.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^\w\s\-.]", "", title)
    cleaned = re.sub(r"\s+", "_", cleaned.strip())
    return (cleaned[:max_len] or "titel").strip("._")


@dataclass
class DownloadResult:
    audio_path: Path
    title: str
    duration_seconds: Optional[int]
    thumbnail_path: Optional[Path]


def _ytmusic_fallback_url(url: str) -> Optional[str]:
    """Return a YouTube Music search URL if *url* is a ytsearch1: query.

    Used when a track is not found on regular YouTube but may exist on
    YouTube Music (e.g. audio-only releases, region-blocked music videos).
    Returns None for all other URL types (no fallback needed).
    """
    prefix = "ytsearch1:"
    if url.startswith(prefix):
        return "ytsearchmusic1:" + url[len(prefix):]
    return None


def _try_download(url: str, opts: dict, dest_dir: Path):
    """Run yt-dlp for *url* and return (ydl, info) or (None, None) on miss."""
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    return info


def download_audio(
    url: str, dest_dir: Path, progress_hook=None
) -> DownloadResult:
    """Download the best audio stream to a temporary file in dest_dir.

    Returns the path to the downloaded (not yet processed) audio plus metadata.
    A cover thumbnail is written next to it if available.

    For Spotify-sourced search URLs (``ytsearch1:…``) a YouTube Music fallback
    (``ytsearchmusic1:…``) is tried automatically when YouTube returns nothing.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(dest_dir / "%(id)s.%(ext)s")

    hooks = []
    if progress_hook is not None:
        hooks.append(progress_hook)

    opts = _base_ydl_opts()
    opts.update({
        "noplaylist": True,
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "writethumbnail": True,
        "progress_hooks": hooks,
        "postprocessors": [],
        # _base_ydl_opts() sets ignoreerrors=True for analyze()'s benefit
        # (skip broken entries while listing a playlist) — wrong here: for
        # an actual single-item download it silently swallowed yt-dlp's
        # real error and returned None, which this function then reported
        # to the user as a generic, useless "Der Inhalt ist nicht
        # verfügbar." regardless of the real cause (bot-check, rate limit,
        # geo-block, ...). Overridden so real failures raise with their
        # real message instead.
        "ignoreerrors": False,
    })

    # Build list of URLs to try: primary URL first, YouTube Music fallback second
    # (fallback is only added for ytsearch1: queries originating from Spotify).
    urls_to_try = [url]
    fallback = _ytmusic_fallback_url(url)
    if fallback:
        urls_to_try.append(fallback)

    info = None
    last_error: Optional[Exception] = None
    for attempt_url in urls_to_try:
        if attempt_url != url:
            logger.info("YouTube: kein Treffer – versuche YouTube Music: %s", attempt_url)
        try:
            info = _try_download(attempt_url, opts, dest_dir)
        except Exception as exc:  # noqa: BLE001 — real yt-dlp error, preserved below
            logger.warning("download attempt failed for %s: %s", attempt_url, exc)
            last_error = exc
            info = None
            continue
        if info is not None:
            break  # success

    if info is None:
        if last_error is not None:
            raise RuntimeError(str(last_error)) from last_error
        raise RuntimeError("Der Inhalt ist nicht verfügbar.")

    # ytsearch1:/ytsearchmusic1: wrap the real entry in a playlist dict.
    # Unwrap to the first entry so all subsequent field access works uniformly.
    if info.get("_type") == "playlist" and info.get("entries"):
        real = info["entries"][0]
        if real is not None:
            info = real

    # locate downloaded audio file
    downloaded = info.get("requested_downloads")
    audio_path = None
    if downloaded:
        audio_path = Path(downloaded[0]["filepath"])
    else:
        # Reconstruct the expected filename from outtmpl pattern.
        vid = info.get("id", "")
        ext = info.get("ext", "")
        if vid and ext:
            candidate = dest_dir / f"{vid}.{ext}"
            if candidate.exists():
                audio_path = candidate
    if audio_path is None or not audio_path.exists():
        # Last resort: glob for any file whose stem matches the video id.
        vid = info.get("id", "")
        matches = list(dest_dir.glob(f"{vid}.*"))
        matches = [m for m in matches if m.suffix.lower() not in (".jpg", ".png", ".webp")]
        if matches:
            audio_path = matches[0]
    if audio_path is None or not audio_path.exists():
        raise RuntimeError("Die Datei konnte nicht geladen werden.")

    # thumbnail
    thumb_path = None
    vid = info.get("id", "")
    for ext in ("jpg", "png", "webp"):
        cand = dest_dir / f"{vid}.{ext}"
        if cand.exists():
            thumb_path = cand
            break

    return DownloadResult(
        audio_path=audio_path,
        title=info.get("title") or "Ohne Titel",
        duration_seconds=int(info["duration"]) if info.get("duration") else None,
        thumbnail_path=thumb_path,
    )
