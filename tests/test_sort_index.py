"""Sort index is written correctly and reorder affects the feed order."""
from app import crud, feed


def test_sort_index_increments(db):
    a = crud.create_item(db, 0, "https://x/1", "Eins")
    b = crud.create_item(db, 0, "https://x/2", "Zwei")
    c = crud.create_item(db, 0, "https://x/3", "Drei")
    assert [a.sort_index, b.sort_index, c.sort_index] == [1, 2, 3]


def test_sort_index_per_channel(db):
    a = crud.create_item(db, 0, "https://x/1", "Eins")
    b = crud.create_item(db, 1, "https://x/2", "Zwei")
    assert a.sort_index == 1
    assert b.sort_index == 1  # independent per channel


def test_reorder_updates_indices(db):
    a = crud.create_item(db, 0, "https://x/1", "Eins")
    b = crud.create_item(db, 0, "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4e/Cartesian_Product_qtl1.svg/1280px-Cartesian_Product_qtl1.svg.png?utm_source=en.wikipedia.org&utm_campaign=index&utm_content=thumbnail", "Zwei")
    c = crud.create_item(db, 0, "https://x/3", "Drei")

    crud.reorder_items(db, 0, [c.id, a.id, b.id])

    items = crud.list_items(db, 0)
    ordered_titles = [i.title for i in items]
    assert ordered_titles == ["Drei", "Eins", "Zwei"]


def test_reorder_reflected_in_feed(db):
    a = crud.create_item(db, 0, "https://x/1", "Eins")
    b = crud.create_item(db, 0, "https://x/2", "Zwei")
    for item, name in ((a, "01_eins.mp3"), (b, "02_zwei.mp3")):
        crud.update_item(db, item.id, status="done", filename=name,
                         duration_seconds=60, file_size_bytes=1000)

    crud.reorder_items(db, 0, [b.id, a.id])
    xml = feed.build_feed_xml(db, 0, "http://host:8080")

    # In the feed, the first <item> title should be "Zwei" after reordering.
    pos_zwei = xml.find("<title>Zwei</title>")
    pos_eins = xml.find("<title>Eins</title>")
    assert pos_zwei != -1 and pos_eins != -1
    assert pos_zwei < pos_eins
