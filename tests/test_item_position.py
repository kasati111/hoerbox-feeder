"""_item_view()'s position/over_limit numbering, used by the channel page
to show at a glance how many of the device's max_playlist_length track
slots are filled."""
from app import crud
from app.routers.ui import _item_view


def test_position_and_over_limit_flag(db):
    item = crud.create_item(db, 0, "https://x/1", "Folge 1")

    within = _item_view(item, {}, is_sub=False, lang="de", position=3, limit=5)
    assert within["position"] == 3
    assert within["over_limit"] is False

    beyond = _item_view(item, {}, is_sub=False, lang="de", position=6, limit=5)
    assert beyond["position"] == 6
    assert beyond["over_limit"] is True


def test_position_omitted_by_default(db):
    """Other callers of _item_view (if any future ones don't pass a
    position) must not accidentally render a stray number."""
    item = crud.create_item(db, 0, "https://x/1", "Folge 1")
    view = _item_view(item, {}, is_sub=False, lang="de")
    assert view["position"] is None
    assert view["over_limit"] is False
