# hoerbox-feeder – Developer Documentation

*[Deutsche Version](DEVELOPER.md)*

> **Audience:** Developers taking over, maintaining, or extending this
> project. This document explains the architecture, all relevant design
> decisions, and known pitfalls.

---

## 1. Overview

**hoerbox-feeder** is a self-hosted web application (FastAPI + SQLite) that
automatically downloads audio content from YouTube, Spotify, and podcasts
onto an SD card for the [hörbert](https://www.hoerbert.com/) – an audio
player for children. hoerbox-feeder is an unofficial community project with
no connection to the hörbert's manufacturer.

```
User (browser) → FastAPI (port 8080) → yt-dlp/spotdl → audio files
                                        ↓
                                   SQLite DB (queue/status)
                                        ↓
                                   APScheduler (subscription sync)
                                        ↓
                                   worker thread (download)
```

The hörbert itself has **9 buttons (0–8)**, each corresponding to a button
(SD-card directory `0/` – `8/`). The app manages content for all 9 buttons.

---

## 2. Directory structure

```
hoerbox-feeder/
├── app/
│   ├── main.py          – FastAPI app, lifespan (startup/shutdown)
│   ├── config.py        – configuration (env vars, paths)
│   ├── database.py      – SQLAlchemy setup + session helpers
│   ├── models.py        – ORM models (Channel, Item, Subscription)
│   ├── crud.py          – database operations
│   ├── i18n.py           – central translation table + t()/channel_label() helpers
│   ├── downloader.py    – yt-dlp + Spotify integration
│   ├── audio.py         – ffmpeg pipeline (loudnorm, mono/stereo, MP3)
│   ├── worker.py        – download worker thread
│   ├── scheduler.py     – APScheduler (subscription sync, yt-dlp update)
│   ├── feed.py          – podcast feed generator (feedgen)
│   ├── sd_export.py     – SD-card export helper functions
│   └── routers/
│       ├── ui.py        – HTML routes (Jinja2)
│       ├── api.py       – REST API routes (JSON)
│       ├── feed_routes.py – RSS/Atom feed routes
│       └── media.py     – media file serving
├── templates/           – Jinja2 HTML templates
├── static/              – CSS, JS, icons
├── tests/               – pytest tests
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── schnellstart.sh      – installation script for Raspberry Pi / Linux servers
```

---

## 3. Data flow

### One-off download (manual)

```
POST /api/channels/{n}/items   (URL from the user)
  → crud.create_item() → status: 'queued'
  → worker.py pulls the job off the queue
  → downloader.analyze(url) – detect type, expand playlist
  → downloader.download_audio(url, dest_dir) – yt-dlp
  → audio.py – ffmpeg loudnorm + mono/stereo + 128k MP3
  → CRUD: status 'done', save file path
```

### Subscription sync (automatic)

```
APScheduler → scheduler.py → crud.list_due_subscriptions()
  → downloader.analyze(sub_url) – fetch new entries
  → only new URLs (idempotency via URL hash) → worker queue
```

---

## 4. Dependencies and version requirements

### 4.1 Python packages (`requirements.txt`)

| Package | Minimum version | Why it matters |
|---|---|---|
| `fastapi` | ≥ 0.110 | Modern lifespan API |
| `starlette` | ≥ 1.0.0 | **Critical – see §5.1** |
| `uvicorn[standard]` | ≥ 0.27 | Websocket support in the `[standard]` extra |
| `yt-dlp[default]` | ≥ 2026.1.1 | EJS solver for YouTube's n-challenge |
| `apscheduler` | ≥ 3.10 | Subscription-sync scheduler |
| `feedgen` | ≥ 1.0 | RSS/Atom feed generation |
| `sqlalchemy` | ≥ 2.0 | New session API |

### 4.2 System dependencies (Dockerfile / schnellstart.sh)

| Tool | Version | Purpose |
|---|---|---|
| `ffmpeg` | any | Audio conversion (loudnorm, mono/stereo, MP3) |
| `node` | **≥ 22** | yt-dlp EJS solver for YouTube's n-challenge |
| `spotdl` | ≥ 4.5 | Spotify metadata (metadata only, no download!) |

**Node.js 22** must be installed via NodeSource – the Debian/Ubuntu
`nodejs` package ships v18, which yt-dlp rejects as of 2026.

### 4.3 spotdl installation (special case)

spotdl declares `fastapi<0.104`, we need `fastapi≥0.110`. Solution:

```dockerfile
# work around spotdl's fastapi conflict:
RUN pip install --no-cache-dir \
        beautifulsoup4 python-slugify soundcloud-v2 spotipyfree \
    && pip install --no-cache-dir --no-deps spotdl
```

`--no-deps` installs spotdl without forcing its dependencies. The missing
deps are installed manually beforehand. spotdl only uses fastapi for its
optional OAuth web UI – which we don't use; Spotify metadata works fine
without fastapi.

---

## 5. Known pitfalls

### 5.1 starlette API version break (MOST IMPORTANT POINT)

The `TemplateResponse` signature changed between starlette 0.27 and 1.0:

```python
# starlette < 1.0 (OLD – DO NOT USE):
templates.TemplateResponse("index.html", {"request": request, ...})
#                           ^ name first, request INSIDE the context dict

# starlette ≥ 1.0 (NEW – current code):
templates.TemplateResponse(request, "index.html", {...})
#                           ^ request first, name second parameter
```

The project uses starlette ≥ 1.0 (`requirements.txt` + `fastapi≥0.110`
pulls in starlette 1.x automatically). **All calls in `app/routers/ui.py`
must use the new format.** The old format produces this error under
starlette ≥ 1.0:

```
TypeError: unhashable type: 'dict'   (internal Starlette error)
→ FastAPI returns HTTP 500 Internal Server Error
```

This was the main bug that used to break this project's home page from the
start. Never downgrade to starlette < 1.0 – that would break every route in
`ui.py`.

### 5.2 yt-dlp: ytsearch1 returns a playlist dict

When `ytsearch1:artist - title` is passed as a URL (used by the Spotify
integration), yt-dlp returns a meta-dict with `_type: 'playlist'` and
`entries: [...]`. The actual result is in `entries[0]`.

The code in `download_audio()` therefore contains this unwrap:

```python
if info.get("_type") == "playlist" and info.get("entries"):
    real = info["entries"][0]
    if real is not None:
        info = real
```

**Without this unwrap, `info["requested_downloads"]` is missing and the
file cannot be located** → RuntimeError.

### 5.3 spotdl singleton

`SpotifyClient` (in spotdl) may only be initialized once per process. A
second `Spotdl(...)` in the same process raises an exception.

Solution in `downloader.py`: module-level singleton with a
`threading.Lock`:

```python
_spotdl_instance = None
_spotdl_lock = threading.Lock()

def _get_spotdl():
    global _spotdl_instance
    if _spotdl_instance is None:
        with _spotdl_lock:
            if _spotdl_instance is None:
                _spotdl_instance = Spotdl(client_id=..., client_secret=...)
    return _spotdl_instance
```

### 5.4 Node.js path for yt-dlp

yt-dlp looks for `node` on the PATH. Inside the Docker container
`/usr/bin/node` is present, but if someone installs Node.js elsewhere, the
EJS solver fails silently → every YouTube download fails with error 403.

`_base_ydl_opts()` in `downloader.py` therefore explicitly searches for
`node`:

```python
def _node_path() -> Optional[str]:
    for candidate in ("node", "/usr/bin/node", "/usr/local/bin/node"):
        found = shutil.which(candidate)
        if found:
            return found
    return None
```

And sets `opts["js_runtimes"] = {"node": {"path": node}}`.

### 5.5 yt-dlp: `prepare_filename()` unavailable outside the `with` block

The yt-dlp object closes its cache after the `with` block.
`ydl.prepare_filename(info)` can no longer be called afterward. File
location is therefore based on
`info["requested_downloads"][0]["filepath"]` or the pattern
`dest_dir / f"{info['id']}.{info['ext']}"`.

### 5.6 anyio version conflict via spotdl pre-deps

`soundcloud-v2` and `spotipyfree` (manually installed before spotdl) have
dependencies that can downgrade `anyio` to 3.x. But `fastapi`/`uvicorn`
need `anyio>=4.0`.

The symptom is an HTTP 500 on **every page** with this log error:

```
KeyError: 'asyncio'
ImportError: cannot import name 'ExceptionGroup' from 'anyio._core._exceptions'
```

**Cause:** `anyio 3.x` has no `ExceptionGroup` in `_exceptions.py`, but
`anyio 4.x` expects it there. If the pre-deps downgrade anyio after the
main `pip install`, the state becomes inconsistent.

**Fix in the Dockerfile:** force anyio explicitly after the spotdl install
block:

```dockerfile
RUN pip install --no-cache-dir \
        beautifulsoup4 python-slugify soundcloud-v2 spotipyfree \
    && pip install --no-cache-dir --no-deps spotdl \
    && pip install --no-cache-dir "anyio>=4.0,<5"
```

`anyio>=4.0` is additionally documented as the minimum version in
`requirements.txt`.

### 5.7 spotdl: metadata only, no audio

`_resolve_spotify()` calls spotdl **only for metadata** (artist, title).
The actual download happens via yt-dlp with a `ytsearch1:` query. This
matters because spotdl has its own internal yt-dlp process that doesn't
know about our cookies file or Node.js configuration.

### 5.8 GET-only routes answer HEAD with 405 (starlette 1.x)

In starlette < 1.0, a `HEAD` request was automatically accepted by any
route that declares `GET` (falls back to the `GET` handler, body dropped).
**In the starlette 1.x version used here, that no longer happens** — a
route declaring only `@router.get(...)` answers `HEAD` with
`405 Method Not Allowed`.

Concretely this hit `GET /feed/{n}.xml` (`feed_routes.py`) and
`GET /audio/{kanal}/{filename}` (`media.py`) — exactly the two endpoints a
device/podcast client actually calls during sync. Many player
implementations send a `HEAD` before downloading a new episode (checking
file size/reachability before starting the real GET download). A 405 in
response got read by the client as an error instead of falling back to
GET — the new episode never synced, while episodes already downloaded
earlier (no fresh HEAD needed) kept working unnoticed. That made the bug
deceptive: it only showed up for freshly-added content, never for the rest
of the already-synced library — from the outside it looked like "this one
item won't sync," not a global API bug.

**Fix:** both routes now explicitly declare `methods=["GET", "HEAD"]`
(`@router.api_route(...)` instead of `@router.get(...)`) and handle
`request.method == "HEAD"` separately — headers (in particular a correct
`Content-Length`) as for GET, but no body. Regression test:
`tests/test_head_requests.py`.

For any new route a device/external client (not just the browser) calls
directly: declare `HEAD` explicitly, don't rely on implicit framework
behavior.

---

## 6. Configuration

All settings are controlled via environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `DATA_DIR` | `/data` | Base directory for all data |
| `AUDIO_DIR` | `$DATA_DIR/audio` | Audio files per button (`0/` – `8/`) |
| `DB_DIR` | `$DATA_DIR/db` | Directory of the SQLite database |
| `DB_PATH` | `$DB_DIR/hoerbert.sqlite3` | Full DB path |
| `PORT` | `8080` | HTTP port |
| `HOST` | `0.0.0.0` | Bind address |
| `TZ` | `Europe/Berlin` | Timezone for the scheduler |
| `AUDIO_BITRATE` | `128k` | CBR bitrate of the MP3 output |
| `AUDIO_SAMPLE_RATE` | `44100` | Sample rate of the MP3 output |
| `DEFAULT_RETENTION` | `20` | Default number of files per button |
| `MAX_INITIAL_PLAYLIST_ITEMS` | `60` | Maximum items on the first subscription sync |
| `STORAGE_WARN_MB` | `100` | Free-space warning threshold in MB |
| `LANG` | `de` | Seed default for `Settings.language` (`de`/`en`) on first start. Invalid values silently fall back to `de` (see §17). Changeable live afterward via the Setup page, no restart needed. |
| `SELFTEST_URL` | *(empty)* | URL for the weekly self-test |

For Docker: set under `environment:` in `docker-compose.yml`.
For local development: as a shell export before starting:

```bash
DATA_DIR=/tmp/hoerbox-test python -m uvicorn app.main:app --port 8080
```

---

## 7. Spotify integration

### How it works

1. User enters a Spotify URL (track, album, or playlist).
2. `_is_spotify(url)` recognizes `open.spotify.com`.
3. `_resolve_spotify(url)` calls spotdl → gets a list of `Song` objects
   with artist and title.
4. For each song, a `SourceEntry(url="ytsearch1:Artist - Title")` is
   created.
5. `download_audio("ytsearch1:...")` searches YouTube and downloads the
   first result.
6. Fallback: if YouTube finds nothing → `ytsearchmusic1:...` (YouTube
   Music).

### Credentials

The client ID/secret in `downloader.py` are spotdl's public demo
credentials (publicly visible in spotdl's source code). They can be
replaced with your own Spotify app credentials:

```python
_SPOTDL_CLIENT_ID = "..."   # from https://developer.spotify.com/dashboard
_SPOTDL_CLIENT_SECRET = "..."
```

---

## 8. Deployment

Two ways, depending on whether the target server has direct access to
GitHub.

### Route A: Git-based (recommended, see also README)

```bash
git clone https://github.com/kasati111/hoerbox-feeder.git
cd hoerbox-feeder
docker compose up -d --build

# follow logs
docker compose logs -f
```

### Route B: Tarball-based (no Git/internet access on the target server)

For servers with no access to GitHub (e.g. an isolated home-network device
reachable only via `scp`). Build the archive locally and transfer it:

```bash
# Locally, in the repo directory:
tar czf hoerbox-feeder-deploy.tar.gz --exclude=.git .
scp hoerbox-feeder-deploy.tar.gz user@target-server:/opt/
```

**Initial install** – `schnellstart.sh` checks for Docker, creates
`/opt/hoerbox-feeder`, unpacks the archive there, and builds/starts the
container (`docker compose up -d --build`):

```bash
cd /opt
chmod +x schnellstart.sh   # from the unpacked archive, if not already
sudo ./schnellstart.sh
```

**Updating** an existing tarball install – `update.sh` checks the new
archive for completeness (catches interrupted uploads), backs up the
current code to `backup_<timestamp>/` (rollback possible), unpacks the new
archive over it, rebuilds the image without cache (`--no-cache`, so
changed templates/static files are reliably picked up), and then runs a
brief health check:

```bash
cd /opt/hoerbox-feeder
# have the new hoerbox-feeder-deploy.tar.gz copied there beforehand
./update.sh
```

Rollback instructions on failure are printed at the end of the script's
output (`cp -r backup_<timestamp>/* . && docker compose up -d --build`).

For **both routes**: button colors/names are automatically synced from
`app/config.py` on container start (see `crud.seed_channels()`) – no
manual database command needed, not even after an update.

### Production URL

Default: `http://<your-server-ip>:8080`

The server listens on all interfaces (`0.0.0.0`). **Do not expose it
directly to the internet** – no auth, no TLS.

### Cookies (YouTube authentication)

To work around YouTube restrictions on server IPs:

1. Export browser cookies with the "Get cookies.txt LOCALLY" extension (on
   a regular PC, while logged into a YouTube account).
2. Save the file at: `/opt/hoerbox-feeder-data/cookies.txt` (mounted in
   Docker as `/data/cookies.txt`).
3. `downloader._cookies_path()` detects the file automatically and sets
   `cookiefile` in the yt-dlp options.

---

## 9. Local development

```bash
# Virtual environment
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# Run the app locally (DATA_DIR must point to a writable directory)
DATA_DIR=/tmp/hoerbox-dev uvicorn app.main:app --reload --port 8080
```

Important: `DATA_DIR` must exist and be writable. `/data` only exists
inside the Docker container.

---

## 10. Tests

```bash
# Run all tests
DATA_DIR=/tmp/hoerbox-test pytest tests/ -v

# Single test file
pytest tests/test_downloader.py -v
```

### Test coverage

| File | What it tests |
|---|---|
| `test_channel_seed.py` | Initialization and idempotency of the 9 buttons |
| `test_idempotency.py` | Duplicate-URL detection per button |
| `test_playlist_limit.py` | MAX_INITIAL_PLAYLIST_ITEMS limit |
| `test_queue_position.py` | Queue position (1-based) |
| `test_retention.py` | Retention policy (deleting oldest files) |
| `test_sort_index.py` | Order of items per button |
| `test_subscription_sync.py` | Subscription sync: new/known entries |

The tests use an in-memory SQLite database and mock yt-dlp (no real
network access).

---

## 11. Architecture decisions

### Why no celery/redis?

The project runs on a Raspberry Pi without Redis. A simple Python
`threading.Thread` as a worker is sufficient and has no external
dependencies.

### Why SQLite instead of PostgreSQL?

Single-user, no high-load scenario. SQLite requires less maintenance and
no separate database installation.

### Why `_base_ydl_opts()` as a central function?

All yt-dlp calls (in `analyze()` and `download_audio()`) share the same
base options (cookies, js_runtimes, quiet). If a parameter changes (e.g. a
new Node path), it only needs to be adjusted in one place.

### Why spotdl only for metadata?

spotdl has its own internal yt-dlp process that doesn't know about our
configuration (cookies, Node.js path). It would fail on server IPs. By
using spotdl only for Spotify API metadata and running the actual download
through our configured yt-dlp, the Spotify integration also works in
restricted network environments.

---

## 12. Changelog (Session 2025-08)

These changes were introduced in a development session:

### Bug fixed: HTTP 500 Internal Server Error (home page)

**Cause:** `fastapi≥0.110` pulls in `starlette≥1.0` as a dependency. In
starlette 1.0, `TemplateResponse` has a new signature: `(request, name,
context)` instead of `(name, context)`. The old code used the outdated
signature → `TypeError: unhashable type: 'dict'` internally → HTTP 500 on
**every** HTML page.

**Fix:** In `app/routers/ui.py`, all 5 `TemplateResponse` calls were
changed from `templates.TemplateResponse("name.html", ctx)` to
`templates.TemplateResponse(request, "name.html", ctx)`. `starlette>=1.0.0`
is now explicitly documented in `requirements.txt`.

### Spotify support added

- `app/downloader.py`: `_is_spotify()`, `_resolve_spotify()`,
  `_get_spotdl()` (singleton), `_ytmusic_fallback_url()`,
  `_try_download()`.
- `app/downloader.py`: `download_audio()` unwraps the `ytsearch1:` playlist
  wrapper from yt-dlp.
- `app/main.py`: spotdl is automatically updated alongside yt-dlp on
  startup.
- `Dockerfile`: Node.js 22 via NodeSource; spotdl installed with
  `--no-deps`.
- `requirements.txt`: `starlette>=1.0.0`; spotdl removed from requirements
  (installed via the Dockerfile instead).
- `templates/index.html`: placeholder text "YouTube, Spotify, or a
  podcast".

---

## 13. Common problems

| Symptom | Likely cause | Fix |
|---|---|---|
| HTTP 500 + `KeyError: 'asyncio'` + `ImportError: ExceptionGroup` | anyio 3.x via spotdl pre-deps | Dockerfile: `pip install "anyio>=4.0,<5"` at the end of the spotdl RUN line (§5.6) |
| HTTP 500 on every page | Wrong `TemplateResponse` signature | Check the starlette version; verify ui.py calls (§5.1) |
| YouTube downloads fail with 403 | Node.js missing or too old | `node --version` in the container; NodeSource v22 required |
| YouTube downloads fail with 403 (despite Node) | Missing cookies | Provide cookies.txt (§8) |
| Spotify URL → "No content found" | spotdl not installed or outdated | `pip install --upgrade --no-deps spotdl` |
| `SpotifyClient already initialized` | spotdl singleton violated | Only use `_get_spotdl()`, never construct `Spotdl(...)` directly |
| "File could not be loaded" | ytsearch wrapper not unwrapped | Check `download_audio()` → unwrap block (§5.2) |
| Scheduler won't start | APScheduler version | apscheduler≥3.10 |
| "No space left" appears immediately when adding | `STORAGE_WARN_MB` too high; host filesystem has less free space than the threshold | Default is 100 MB. Check with `df -h /opt/hoerbox-feeder-data` on the host. Adjust the threshold via env var: `STORAGE_WARN_MB=50` in `docker-compose.yml`. |
| Icons have a black or dark border | Browser/PWA cache showing an old version | Clear the browser cache (hard refresh: Ctrl+Shift+R). The PNG icons have a transparent background. |
| Clipboard button (📋) does nothing or throws an error | No HTTPS (the Clipboard API requires a secure context) | See §13.1 |

### 13.1 Clipboard paste doesn't work (missing HTTPS)

The 📋 button next to the URL field on the home page uses
`navigator.clipboard.readText()` (`static/app.js`, event listener on
`#paste-btn`). Across all major browsers, this Clipboard API is only
available in a *secure context*: HTTPS, or `http://localhost` /
`http://127.0.0.1`. hoerbox-feeder runs over plain HTTP on a LAN address by
default (e.g. `http://192.168.1.20:8080`) — on most devices the button will
therefore fail as expected. This isn't a bug in the app itself, it's a
**platform limitation from running without SSL**.

**Built-in fallback:** when `readText()` fails, `app.js` catches the error
and instead focuses/selects the URL field so the user can paste manually
with Ctrl+V (or long-press → "Paste" on mobile). This always works
regardless of HTTPS or browser — the 📋 button is a convenience, not a
required part of the workflow.

**Browser-specific fixes, if you want the 📋 button to work anyway:**

- **Recommended, all browsers:** put a reverse proxy (nginx, Caddy,
  Traefik) with a certificate (self-signed, or Let's Encrypt via a local
  domain) in front of hoerbox-feeder. This serves the app over HTTPS and
  the button works everywhere with no further steps.
- **Chrome / Edge (only fixes it for your own admin browser, not a fix for
  every family device):** open
  `chrome://flags/#unsafely-treat-insecure-origin-as-secure`, add the
  server address (e.g. `http://192.168.1.20:8080`), restart the browser.
  This treats the origin as secure and unlocks the Clipboard API.
- **Firefox / Safari:** no equivalent flag exists — neither vendor
  supports (or plans to support) bypassing the secure-context requirement
  for clipboard access. The only options are the reverse-proxy fix above,
  or manual paste via Ctrl+V.

---

## 14. Future work

### Ideas / open items

- **Authentication:** Currently none – put Basic Auth or a VPN in front of
  it if exposed publicly.
- **Multi-user:** Enable SQLite WAL mode if multiple users are active
  concurrently.
- **Spotify playlist as a subscription:** Currently a Spotify playlist is
  fully downloaded on first use. In the future, it could periodically
  check for new entries (like a YouTube subscription).
- **Test coverage for the downloader:** The tests mock yt-dlp. A real
  integration test would be desirable (requires internet in CI).

---

## 15. Changelog (Follow-up session August 2026)

### Bug fixed: "No space left" appears immediately

**Cause:** `STORAGE_WARN_MB` defaulted to **500 MB**. On a typical home
server or Raspberry Pi, the space on the root filesystem is often tighter
than 500 MB – the storage guard therefore triggered immediately, even when
there was still enough room for audio files.

**Fix:** Default in `app/config.py` lowered to **100 MB**. Anyone needing a
different threshold sets `STORAGE_WARN_MB=…` in `docker-compose.yml`.

### Bug fixed: icons have a dark border (black outline)

**Cause:** The PNG icon files (`apple-touch-icon.png`, `icon-192.png`,
`favicon.png`) had an opaque dark-blue background square (#0b1d33). In
modern browsers and on the home screen, this appeared as a black or
dark-blue border around the logo.

**Fix:** All three PNGs were re-rendered with Pillow – the dark background
was replaced with alpha transparency (pixels near the corner background
color → `alpha=0`, with a smooth transition for anti-aliasing). The logo
(a yellow Pac-Man with a white "h") remains fully visible. `favicon.ico`
was also regenerated from the transparent PNG.

---

## 16. Changelog (Follow-up session August 2026, part 2)

### Critical fix: directory structure had been flattened

When the deployment was copied/unpacked onto a different system, all
modules from `app/`, `app/routers/`, `templates/`, and `static/` ended up
flat in the project root by mistake. The code itself (relative imports,
the Dockerfile's `COPY app ./app`) requires exactly the package structure
– neither `docker compose up` nor `uvicorn app.main:app` would start.
Structure was restored based on the imports and a reference deployment
archive (verified byte-identical).

### Fix: `STORAGE_WARN_MB=500` in `docker-compose.yml` re-undid the §15 fix

The fix documented in §15 only lowered the Python default in `config.py`.
`docker-compose.yml` (the recommended deploy route) still explicitly set
the environment variable to 500 MB. The line was removed; the app default
(100 MB) now also applies under Docker.

### Fix: Spotify downloads never worked (`ModuleNotFoundError: rapidfuzz`)

spotdl was installed with `--no-deps`, plus a manually maintained partial
list of supposedly missing dependencies (§4.3). spotdl 4.5.2 actually needs
significantly more (among others `rapidfuzz`, `platformdirs`, `pykakasi`,
`datastar-py`, `syncedlyrics`, `spotipy`, `ytmusicapi`) – every Spotify
import failed at runtime with `ModuleNotFoundError`, which `downloader.py`
masked as a generic "spotdl is not installed".

**Fix:** spotdl is now installed WITH its full dependency tree in the
`Dockerfile` and `app/main.py._update_yt_dlp()`, after which only the
packages that actually collide (`fastapi`/`starlette`/`anyio`/`uvicorn`,
because of spotdl's unused web UI) are pinned back to the versions the app
needs. More robust than a manual partial list that can break again with
every spotdl update. §4.3 is now superseded – this is the current
reference.

### Feature: browser-native SD export (ZIP download)

The existing server-path export (`POST /api/sd-export`, §7/§14) assumes an
SD card mounted on the *server* – impractical for a headless Raspberry Pi
without a card reader. New endpoint `GET /api/sd-export/zip`
(`app/routers/api.py`) delivers the same folder structure (`0/`–`8/`,
files named "NN Title.mp3") as a ZIP file via a normal browser download –
works from any device on the LAN, with no server-side card access needed.
Button on `/belegung` (only shown when files are present).

**Deliberately no `showDirectoryPicker()`/File System Access API:** That
would require a "secure context" (HTTPS or `localhost`); per §8 the app
runs exclusively over HTTP on the LAN IP, though – the picker simply
wouldn't be available there, and Firefox/Safari support is missing
entirely besides. ZIP download, by contrast, works in every browser
without TLS.

**Implementation:** `app/sd_export.py` – shared iteration logic
`_iter_export_files()` yields `(channel_id, dest_name, src_path)` for both
export variants; `build_export_zip()` writes uncompressed (`ZIP_STORED`,
MP3s are already compressed) to a real temp file on disk rather than in
memory (the library can grow to several hundred MB – too much for the
Pi's RAM). The temp file is automatically deleted after sending via
Starlette's `BackgroundTask`.

---

## 17. Internationalization (i18n) & button display

### Architecture

No gettext/Babel, no compiled `.po`/`.mo` catalogs, no build step –
consistent with the rest of the project (vanilla JS, Jinja2 without a
bundler). Instead, a single central table in `app/i18n.py`:

```python
STRINGS = {
    "nav.start": {"de": "Start", "en": "Home"},
    "api.entry_deleted": {"de": "Eintrag gelöscht.", "en": "Entry deleted."},
    ...
}

def t(key: str, lang: str, **kwargs) -> str:
    ...  # lookup + .format(**kwargs), falls back to "de", then to the key itself
```

`t()` is used both server-side (a Jinja context function, see below, and
directly in Python to build API error messages) and to embed a small,
targeted `js.*` subset as JSON in `templates/base.html`
(`window.HOERBOX_I18N`) – `static/app.js` has its own minimal
`i18n(key, params)` helper using the same `{name}` placeholder syntax as
Python.

### Language (`Settings.language`)

Follows exactly the pattern already established by
`Settings.audio_channels`:

- `config.LANG` reads the `LANG` env var (default `"de"`, validated
  against `{"de","en"}` – a system `LANG` like `C.UTF-8` silently falls
  back to `"de"` instead of changing the UI language).
- `crud.get_settings()` seeds `Settings.language` from `config.LANG` when
  the singleton row is first created.
- After that, the value lives exclusively in the DB and is changed via the
  Setup page (`POST /api/settings {"language": "de"|"en"}`) – effective
  immediately, no restart needed (every request re-reads
  `crud.get_settings(db).language`).
- `app/routers/ui.py::_base_context(db)` is the central context-injection
  point for all HTML routes: supplies `lang`, `skin`, `t`, and
  `channel_label`/`channel_color_hex` (see below) into the Jinja context.
  Background code without a request (worker, scheduler, `feed.py`) each
  read `crud.get_settings(db).language` from their own `session_scope()`.
- Historical, already-stored text (`item.error_text`, fallback titles like
  "Ohne Titel"/"Untitled") stays in whichever language it was created in –
  no retroactive change, analogous to `audio_channels` (switching the
  language also doesn't re-encode already-processed MP3s).

### Button display (`Settings.skin`)

A second, independent setting (`"colors"` default | `"numbers"`), also
switchable via the Setup page. `channel.color` (the existing,
language-independent identifier `violet`/`red`/`darkblue`/…) serves as the
translation lookup key for the color names – `channel.name` in the DB
remains unchanged as an internal/seed value (still synced from
`config.CHANNELS` by `crud.seed_channels()`), but is no longer rendered
directly anywhere user-visible.

```python
def channel_label(channel, lang, skin):
    if skin == "numbers":
        return t("channel.numbered_button", lang, n=channel.id + 1)  # "Taste 5"/"Button 5"
    return channel_color_name(channel.color, lang)                   # "Türkis"/"Turquoise"

def channel_color_hex(channel, skin):
    return NEUTRAL_SKIN_HEX if skin == "numbers" else channel.color_hex
```

In `"numbers"` skin, **every** button color in the UI is neutral gray
(`#667080`, reused from `--muted` in `static/style.css`) – including the
color dot, not just the name. Intended for hörbert variants/replicas with
numbered instead of colored buttons.

### Migration

```python
("settings", "language", "TEXT NOT NULL DEFAULT 'de'"),
("settings", "skin", "TEXT NOT NULL DEFAULT 'colors'"),
```

in `app/migrations.py::_NEW_COLUMNS`, like any other column added after the
fact (see the module docstring there).

---

*This document last updated: August 2026*
