"""Same URL in the same channel is never added twice."""
from app import crud


def test_duplicate_same_channel_rejected(db):
    first = crud.create_item(db, 0, "https://x/same", "Titel")
    second = crud.create_item(db, 0, "https://x/same", "Titel")
    assert first is not None
    assert second is None
    assert len(crud.list_items(db, 0)) == 1


def test_same_url_different_channel_allowed(db):
    a = crud.create_item(db, 0, "https://x/same", "Titel")
    b = crud.create_item(db, 1, "https://x/same", "Titel")
    assert a is not None and b is not None
    assert len(crud.list_items(db, 0)) == 1
    assert len(crud.list_items(db, 1)) == 1


def test_item_exists_lookup(db):
    crud.create_item(db, 0, "https://x/one", "Eins")
    assert crud.item_exists(db, 0, "https://x/one") is not None
    assert crud.item_exists(db, 0, "https://x/two") is None
    assert crud.item_exists(db, 1, "https://x/one") is None
