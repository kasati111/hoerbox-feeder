"""GET /audio/{kanal}/{filename} with HTTP Range support.

Range support and a correct Content-Length are required by the device player.
"""
import logging
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from .. import config
from ..device_fingerprint import client_info

router = APIRouter()

logger = logging.getLogger("hoerbox.media")

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
_CHUNK = 1024 * 256


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
            "audio_rejected kanal=%s filename=%s reason=not_found %s",
            kanal, filename, client_info(request),
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
