"""GET /feed/{n}.xml — per-channel RSS output."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from .. import crud, feed
from ..database import get_db

router = APIRouter()


@router.get("/feed/{n}.xml")
def get_feed(n: int, request: Request, db: Session = Depends(get_db)):
    if n < 0 or n > 8 or crud.get_channel(db, n) is None:
        raise HTTPException(status_code=404, detail="Kanal nicht gefunden.")
    base_url = str(request.base_url).rstrip("/")
    xml = feed.build_feed_xml(db, n, base_url)
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")
