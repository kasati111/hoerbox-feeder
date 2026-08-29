"""GET /audio/{kanal}/{filename} with HTTP Range support.

Range support and a correct Content-Length are required by the device player.
"""
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from .. import config

router = APIRouter()

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
_CHUNK = 1024 * 256


def _safe_path(kanal: int, filename: str) -> Path:
    # prevent path traversal
    if "/" in filename or ".." in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Ungültiger Dateiname.")
    path = (config.AUDIO_DIR / str(kanal) / filename).resolve()
    root = (config.AUDIO_DIR / str(kanal)).resolve()
    if not str(path).startswith(str(root)):
        raise HTTPException(status_code=400, detail="Ungültiger Pfad.")
    return path


@router.api_route("/audio/{kanal}/{filename}", methods=["GET", "HEAD"])
def get_audio(kanal: int, filename: str, request: Request):
    path = _safe_path(kanal, filename)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Datei nicht gefunden.")

    file_size = path.stat().st_size

    if request.method == "HEAD":
        # See feed_routes.py's HEAD handling for why this is needed: a
        # device player commonly HEADs an enclosure URL (to check size
        # before it starts a real download) before ever issuing the GET.
        return Response(
            status_code=200,
            media_type="audio/mpeg",
            headers={"Accept-Ranges": "bytes", "Content-Length": str(file_size)},
        )

    range_header = request.headers.get("range") or request.headers.get("Range")

    if range_header is None:
        return FileResponse(
            str(path),
            media_type="audio/mpeg",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
            },
        )

    match = _RANGE_RE.match(range_header)
    if not match:
        raise HTTPException(status_code=416, detail="Range nicht verarbeitbar.")

    start_s, end_s = match.groups()
    start = int(start_s) if start_s else 0
    end = int(end_s) if end_s else file_size - 1
    end = min(end, file_size - 1)
    if start > end or start >= file_size:
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    length = end - start + 1

    def iterfile():
        with open(path, "rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(_CHUNK, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Type": "audio/mpeg",
    }
    return StreamingResponse(iterfile(), status_code=206, headers=headers,
                             media_type="audio/mpeg")
