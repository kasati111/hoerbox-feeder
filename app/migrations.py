"""Idempotent ALTER TABLE for columns added after the initial release.

There's no Alembic here — database.init_db() only does
Base.metadata.create_all(), which creates brand-new tables but never alters
existing ones. Safe to call on every startup: each entry is skipped once the
column already exists, mirroring the existing "safe to re-run" philosophy of
crud.seed_channels().
"""
import logging

from sqlalchemy import inspect, text

from . import config

logger = logging.getLogger("hoerbox.migrations")

_NEW_COLUMNS = [
    ("item", "in_library", "INTEGER NOT NULL DEFAULT 0"),
    ("item", "library_added_at", "DATETIME"),
    ("subscription", "title", "TEXT"),
    ("settings", "max_playlist_length", "INTEGER NOT NULL DEFAULT 30"),
    ("item", "alt_source_url", "TEXT"),
    ("item", "alt_source_reviewed", "INTEGER NOT NULL DEFAULT 0"),
    ("channel", "active", "INTEGER NOT NULL DEFAULT 1"),
    ("settings", "audio_channels", "INTEGER NOT NULL DEFAULT 1"),
    # Existing installs upgrading from a pre-i18n version get backfilled from
    # the current LANG env var here, same as a brand-new install's Settings
    # row would be seeded by crud.get_settings() -- a hardcoded 'de' default
    # would silently ignore an operator's LANG=en on upgrade.
    ("settings", "language", f"TEXT NOT NULL DEFAULT '{config.LANG}'"),
    ("settings", "skin", "TEXT NOT NULL DEFAULT 'colors'"),
]


def run_migrations(engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, column, ddl in _NEW_COLUMNS:
            if table not in existing_tables:
                continue
            existing_columns = {c["name"] for c in inspector.get_columns(table)}
            if column in existing_columns:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            logger.info("migrated: added %s.%s", table, column)
