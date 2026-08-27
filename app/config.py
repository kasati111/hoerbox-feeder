"""Central configuration for hoerbox-feeder.

All settings can be overridden via environment variables so the operator can
tune the running service without touching the code.
"""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from . import i18n

# --- Timezone (Europe/Berlin everywhere) ------------------------------------
TIMEZONE_NAME = os.getenv("TZ", "Europe/Berlin")
TZ = ZoneInfo(TIMEZONE_NAME)

# --- Language -----------------------------------------------------------------
# Seed default only (like AUDIO_CHANNELS below) -- once the app has started,
# the live value lives in Settings.language and is editable on the Setup
# page. Validated against the supported set: this container doesn't set a
# system LANG itself, but if an operator's environment ever does (locale
# vars are common), a value like "C.UTF-8" must not silently become the
# app's UI language -- fall back to i18n.DEFAULT_LANG instead.
_lang_env = os.getenv("LANG", i18n.DEFAULT_LANG).split(".")[0].split("_")[0].lower()
LANG = _lang_env if _lang_env in i18n.LANGS else i18n.DEFAULT_LANG

# --- Paths ------------------------------------------------------------------
# Inside the container these live on named volumes (see docker-compose.yml).
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
AUDIO_DIR = Path(os.getenv("AUDIO_DIR", str(DATA_DIR / "audio")))
DB_DIR = Path(os.getenv("DB_DIR", str(DATA_DIR / "db")))
# Filename intentionally left as "hoerbert.sqlite3" (not renamed alongside
# the project) -- existing deployments have real data under this exact
# name; renaming the default here would make the app silently start a
# fresh, empty database on the next update instead of finding it.
DB_PATH = Path(os.getenv("DB_PATH", str(DB_DIR / "hoerbert.sqlite3")))

# --- Network ----------------------------------------------------------------
HOST = os.getenv("HOST", "0.0.0.0")  # LAN bind only; never expose to WAN.
PORT = int(os.getenv("PORT", "8080"))
# Base URL the scheduler uses when (re)writing per-channel feed files during
# a background subscription sync (see scheduler.py::sync_subscription) --
# there's no incoming request there to read a host/scheme from. Defaults to
# localhost+PORT; override for environments where that's not reachable
# (e.g. a reverse proxy in front, or a different container network setup).
FEED_BASE_URL = os.getenv("FEED_BASE_URL", f"http://localhost:{PORT}")

# --- Storage guard ----------------------------------------------------------
# Reject new jobs / subscription runs when free space drops below this many MB.
# Default 100 MB – sane for most home servers / NAS systems.
# Raise via env var STORAGE_WARN_MB if you want a higher safety margin.
STORAGE_WARN_MB = int(os.getenv("STORAGE_WARN_MB", "100"))

# --- Retention / scheduling defaults ---------------------------------------
DEFAULT_RETENTION = int(os.getenv("DEFAULT_RETENTION", "60"))
DEFAULT_INTERVAL_HOURS = int(os.getenv("DEFAULT_INTERVAL_HOURS", "6"))
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "3"))
# Stagger offset between subscriptions: id * this many minutes.
SUBSCRIPTION_STAGGER_MINUTES = int(os.getenv("SUBSCRIPTION_STAGGER_MINUTES", "5"))

# Playlist limit: prevent large playlists (1000+ videos) from overwhelming the system.
# Only the newest N items from a playlist are queued initially; subscriptions fetch new ones automatically.
MAX_INITIAL_PLAYLIST_ITEMS = int(os.getenv("MAX_INITIAL_PLAYLIST_ITEMS", "60"))

# --- Audio settings ---------------------------------------------------------
AUDIO_BITRATE = os.getenv("AUDIO_BITRATE", "128k")   # CBR
AUDIO_SAMPLE_RATE = int(os.getenv("AUDIO_SAMPLE_RATE", "44100"))
# Seed default only (1=mono, 2=stereo) -- once the app has started, the live
# value lives in Settings.audio_channels and is editable on the Setup page,
# not here.
AUDIO_CHANNELS = 1
LOUDNORM_I = -16.0
LOUDNORM_TP = -1.5
LOUDNORM_LRA = 11.0

# --- Self-test --------------------------------------------------------------
# A public-domain audio URL used for the weekly self-test.
SELFTEST_URL = os.getenv(
    "SELFTEST_URL",
    "https://archive.org/download/testmp3testfile/mpthreetest.mp3",
)

# --- Channel definitions ----------------------------------------------------
# Fixed mapping of the nine coloured buttons (0..8).
# Order: left-to-right, top-to-bottom on the device.
# Row 1: Violett, Rot, Dunkelblau
# Row 2: Grün, Gelb, Türkis
# Row 3: Hellblau, Orange, Dunkelgrün
#
# This list is the actual source of truth for name/color/color_hex, not just
# the initial seed: crud.seed_channels() re-syncs every existing channel row
# from here on every startup (so config changes take effect after an update
# without a manual migration) — a channel 0/3 rename done directly in the
# database earlier got silently reverted back to "Schwarz"/the old green on
# the next container restart for exactly this reason. Edit here, not the DB.
CHANNELS = [
    {"id": 0, "name": "Violett",    "color": "violet",    "color_hex": "#4A148C"},
    {"id": 1, "name": "Rot",        "color": "red",       "color_hex": "#D32F2F"},
    {"id": 2, "name": "Dunkelblau", "color": "darkblue",  "color_hex": "#1976D2"},
    {"id": 3, "name": "Grün",       "color": "green",     "color_hex": "#8BC34A"},
    {"id": 4, "name": "Gelb",       "color": "yellow",    "color_hex": "#FBC02D"},
    {"id": 5, "name": "Türkis",     "color": "cyan",      "color_hex": "#00ACC1"},
    {"id": 6, "name": "Hellblau",   "color": "lightblue", "color_hex": "#2196F3"},
    {"id": 7, "name": "Orange",     "color": "orange",    "color_hex": "#F57C00"},
    {"id": 8, "name": "Dunkelgrün", "color": "darkgreen", "color_hex": "#2E7D32"},
]


def ensure_dirs() -> None:
    """Create the data directories if they do not exist yet."""
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    DB_DIR.mkdir(parents=True, exist_ok=True)
    for ch in CHANNELS:
        (AUDIO_DIR / str(ch["id"])).mkdir(parents=True, exist_ok=True)
