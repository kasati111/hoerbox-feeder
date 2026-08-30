"""GET /audio/{kanal}/{filename} with HTTP Range support.

Range support and a correct Content-Length are required by the device player.
"""
import logging
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from .. import config
from ..device_fingerprint import client_info

router = APIRouter()

logger = logging.getLogger("hoerbox.media")

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
_CHUNK = 1024 * 256

# In-memory only, per (kanal, filename) -- reverse-engineering aid for the
# device's retry behaviour on a 404 (e.g. a stale enclosure it kept in its
# own queue after the episode was deleted server-side): each "not_found"
# rejection logs the gap since the last one for the same file, so the
# retry interval/backoff pattern shows up directly in the log without
# manually diffing timestamps. Not meant to survive a restart.
_last_not_found_at: dict = {}


def _retry_gap(kanal: int, filename: str) -> str:
    key = (kanal, filename)
    now = datetime.utcnow()
    prev = _last_not_found_at.get(key)
    _last_not_found_at[key] = now
    if prev is None:
        return "since_last=first"
    total_s = int((now - prev).total_seconds())
    if total_s < 60:
        return f"since_last={total_s}s"
    m, s = divmod(total_s, 60)
    if m < 60:
        return f"since_last={m}m{s}s"
    h, m = divmod(m, 60)
    return f"since_last={h}h{m}m"


def _safe_path(kanal: int, filename: str, request: Request) -> Path:
    # prevent path traversal
    if "/" in filename or ".." in filename or "\\" in filename:
        logger.warning(
            "audio_rejected kanal=%s filename=%s reason=invalid_filename %s",
            kanal, filename, client_info(request),
        )
        raise HTTPException(status_code=400, detail="Ungültiger Dateiname.")
    path = (config.AUDIO_DIR / str(kanal) / filename).resolve()
    root = (config.AUDIO_DIR / str(kanal)).resolve()
    if not str(path).startswith(str(root)):
        logger.warning(
            "audio_rejected kanal=%s filename=%s reason=invalid_path %s",
            kanal, filename, client_info(request),
        )
        raise HTTPException(status_code=400, detail="Ungültiger Pfad.")
    return path


@router.api_route("/audio/{kanal}/{filename}", methods=["GET", "HEAD"])
def get_audio(kanal: int, filename: str, request: Request):
    path = _safe_path(kanal, filename, request)
    if not path.exists() or not path.is_file():
        logger.warning(
            "audio_rejected kanal=%s filename=%s reason=not_found %s %s",
            kanal, filename, client_info(request), _retry_gap(kanal, filename),
        )
        raise HTTPException(status_code=404, detail="Datei nicht gefunden.")

    file_size = path.stat().st_size
    range_header = request.headers.get("range")

    logger.info(
        "audio_access kanal=%s filename=%s method=%s range=%s %s",
        kanal, filename, request.method, range_header or "-", client_info(request),
    )

    if request.method == "HEAD":
        # See feed_routes.py's HEAD handling for why this is needed: a
        # device player commonly HEADs an enclosure URL (to check size
        # before it starts a real download) before ever issuing the GET.
        return Response(
            status_code=200,
            media_type="audio/mpeg",
            headers={"Accept-Ranges": "bytes", "Content-Length": str(file_size)},
        )

    status_code = 200
    start, end = 0, file_size - 1

    if range_header is not None:
        match = _RANGE_RE.match(range_header)
        if not match:
            logger.warning(
                "audio_rejected kanal=%s filename=%s reason=range_unparseable range=%s %s",
                kanal, filename, range_header, client_info(request),
            )
            raise HTTPException(status_code=416, detail="Range nicht verarbeitbar.")

        start_s, end_s = match.groups()
        start = int(start_s) if start_s else 0
        end = int(end_s) if end_s else file_size - 1
        end = min(end, file_size - 1)
        if start > end or start >= file_size:
            logger.warning(
                "audio_rejected kanal=%s filename=%s reason=range_not_satisfiable "
                "range=%s file_size=%s %s",
                kanal, filename, range_header, file_size, client_info(request),
            )
            return Response(
                status_code=416,
                headers={"Content-Range": f"bytes */{file_size}"},
            )
        status_code = 206

    length = end - start + 1
    client_desc = client_info(request)

    def iterfile():
        sent = 0
        try:
            with open(path, "rb") as fh:
                fh.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = fh.read(min(_CHUNK, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    sent += len(chunk)
                    yield chunk
        finally:
            # A device that drops the connection mid-transfer (WLAN hiccup,
            # box powered off, player gives up) closes this generator via
            # GeneratorExit before `remaining` reaches 0 -- that's the
            # signal a "download fehlgeschlagen" report on the box actually
            # started fine on the server side but didn't finish.
            if sent < length:
                logger.warning(
                    "audio_transfer_incomplete kanal=%s filename=%s sent=%s of=%s %s",
                    kanal, filename, sent, length, client_desc,
                )
            else:
                logger.info(
                    "audio_transfer_complete kanal=%s filename=%s bytes=%s %s",
                    kanal, filename, sent, client_desc,
                )

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Type": "audio/mpeg",
    }
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"

    return StreamingResponse(iterfile(), status_code=status_code, headers=headers,
                             media_type="audio/mpeg")
