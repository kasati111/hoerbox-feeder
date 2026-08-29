"""GET /feed/{n}.xml — per-channel RSS output."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from .. import crud, feed
from ..database import get_db

router = APIRouter()


@router.api_route("/feed/{n}.xml", methods=["GET", "HEAD"])
def get_feed(n: int, request: Request, db: Session = Depends(get_db)):
    if n < 0 or n > 8 or crud.get_channel(db, n) is None:
        raise HTTPException(status_code=404, detail="Kanal nicht gefunden.")
    base_url = str(request.base_url).rstrip("/")
    xml = feed.build_feed_xml(db, n, base_url)
    if request.method == "HEAD":
        # Some device/podcast clients HEAD-probe a feed (or a new episode's
        # enclosure, see media.py) before committing to a GET -- without
        # explicit HEAD support here, that probe got a plain 405 (this
        # route only declared GET; unlike older starlette, 1.x does not
        # auto-add HEAD for a GET-only route, see DEVELOPER.md §5.1), which
        # a minimal HTTP client can read as "feed unavailable" and abort
        # the sync instead of falling back to GET.
        return Response(
            status_code=200,
            media_type="application/rss+xml; charset=utf-8",
            headers={"Content-Length": str(len(xml.encode("utf-8")))},
        )
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")
