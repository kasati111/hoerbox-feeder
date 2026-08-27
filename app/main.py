"""FastAPI application entrypoint and startup logic."""
import logging
import subprocess
import sys
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import config, crud, migrations, scheduler, worker
from .database import get_engine, init_db, session_scope
from .routers import api, feed_routes, media, ui

# --- Logging -----------------------------------------------------------------
# INFO on our own app loggers (hoerbox.*) is the useful signal for
# debugging from the /logs page: job success/failure, sync results,
# migrations, storage warnings. uvicorn's access log and APScheduler's own
# internal chatter are pure noise at that level — the status page alone
# polls every 1.5s while a download is running, which would otherwise
# drown out everything else in the log within minutes.
_formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s :: %(message)s")
_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setFormatter(_formatter)

config.ensure_dirs()
LOG_PATH = config.DB_DIR / "app.log"  # lives on the persisted db volume, survives rebuilds
_file_handler = RotatingFileHandler(LOG_PATH, maxBytes=2_000_000, backupCount=2, encoding="utf-8")
_file_handler.setFormatter(_formatter)

logging.basicConfig(level=logging.INFO, handlers=[_stream_handler, _file_handler])
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

logger = logging.getLogger("hoerbox.main")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _update_yt_dlp() -> None:
    """Update yt-dlp and spotdl on startup (both change frequently).

    yt-dlp[default] also pulls in yt-dlp-ejs which is required since 2026
    to solve YouTube's n-challenge.

    spotdl is upgraded WITH its full dependency tree (mirrors the Dockerfile
    install — see Dockerfile comments). Upgrading spotdl with --no-deps looks
    safer at first glance, but it silently breaks Spotify support the moment
    a new spotdl release adds a new import: pip never installs it, and
    _resolve_spotify() fails at runtime with ModuleNotFoundError (this
    happened for real with rapidfuzz in spotdl 4.5.2). Letting pip resolve
    spotdl's real deps and then re-pinning the handful of packages spotdl
    wants to downgrade (fastapi/starlette/anyio/uvicorn) is the version that
    actually stays correct across upgrades.
    """
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "--quiet",
             "yt-dlp[default]"],
            check=False, timeout=300,
        )
        # Upgrade spotdl with its full dependency tree.
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "--quiet",
             "spotdl"],
            check=False, timeout=300,
        )
        # Re-pin the packages spotdl's own (incompatible) pins would
        # otherwise downgrade back to what our app actually needs.
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "fastapi>=0.110", "starlette>=1.0.0", "anyio>=4.0,<5",
             "uvicorn[standard]>=0.27"],
            check=False, timeout=120,
        )
        logger.info("yt-dlp + spotdl update attempted")
    except Exception as exc:  # noqa: BLE001
        logger.warning("yt-dlp/spotdl update failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup begin")
    config.ensure_dirs()

    # 1) update the downloader tool
    _update_yt_dlp()

    # 2) initialise DB + seed channels
    init_db()
    migrations.run_migrations(get_engine())
    with session_scope() as db:
        crud.seed_channels(db)
        crud.get_settings(db)  # seed the Settings singleton row
        # 3) reset stuck jobs from a previous run
        reset = crud.reset_running_jobs(db)
        logger.info("reset %s stuck jobs", reset)

    # 4) start worker + scheduler
    worker.start_worker()
    scheduler.start_scheduler()
    logger.info("startup complete on port %s", config.PORT)

    yield

    logger.info("shutdown begin")
    scheduler.stop_scheduler()
    worker.stop_worker()
    logger.info("shutdown complete")


app = FastAPI(title="hoerbox-feeder", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(ui.router)
app.include_router(api.router)
app.include_router(feed_routes.router)
app.include_router(media.router)


@app.get("/health")
def health():
    return {
        "ok": True,
        "free_mb": worker.free_space_mb(),
        "storage_ok": worker.storage_ok(),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=config.HOST,
        port=config.PORT,
        reload=False,
    )
