"""Tests for channel seeding + automatic sync of name/colour on startup."""
from app import config, crud
from app.models import Channel


def test_seed_creates_all_channels(db):
    channels = crud.list_channels(db)
    assert len(channels) == len(config.CHANNELS)


def test_seed_syncs_existing_channel_name_and_colour(db):
    # Simulate an old DB state with outdated name/colour.
    ch0 = db.get(Channel, 0)
    ch0.name = "Grün"
    ch0.color = "green"
    ch0.color_hex = "#4CAF50"
    db.commit()

    # Running seed again (as happens on every startup) must refresh it.
    crud.seed_channels(db)

    ch0 = db.get(Channel, 0)
    expected = config.CHANNELS[0]
    assert ch0.name == expected["name"]
    assert ch0.color == expected["color"]
    assert ch0.color_hex == expected["color_hex"]


def test_seed_preserves_retention(db):
    # User-configured retention must survive a re-seed.
    ch3 = db.get(Channel, 3)
    ch3.retention = 42
    db.commit()

    crud.seed_channels(db)

    ch3 = db.get(Channel, 3)
    assert ch3.retention == 42


def test_seed_is_idempotent(db):
    crud.seed_channels(db)
    crud.seed_channels(db)
    assert len(crud.list_channels(db)) == len(config.CHANNELS)
