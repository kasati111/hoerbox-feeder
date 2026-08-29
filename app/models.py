"""ORM models: channel, item, job, subscription."""
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .database import Base


class Channel(Base):
    __tablename__ = "channel"

    id = Column(Integer, primary_key=True)  # 0..8
    name = Column(String, nullable=False)
    color = Column(String, nullable=False)
    color_hex = Column(String, nullable=False)
    retention = Column(Integer, nullable=False, default=20)
    active = Column(Integer, nullable=False, default=1)  # 0/1: vom Feeder bespielbar

    items = relationship("Item", back_populates="channel")
    subscriptions = relationship("Subscription", back_populates="channel")


class Item(Base):
    __tablename__ = "item"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(Integer, ForeignKey("channel.id"), nullable=False)
    source_url = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    filename = Column(Text)  # relative to /data/audio/<channel>/
    duration_seconds = Column(Integer)
    file_size_bytes = Column(Integer)
    sort_index = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="queued")  # queued/downloading/done/failed
    error_text = Column(Text)
    # Contract: sort_index for a subscription_id-tagged item must only ever be
    # assigned by crud.insert_into_block / reorder_blocks / reorder_subscription_items,
    # so that all items sharing a subscription_id stay contiguous (the channel
    # view groups them into one "block" based on that contiguity).
    subscription_id = Column(Integer, ForeignKey("subscription.id"))
    # When set, the worker downloads from here instead of source_url (which
    # stays the stable identity key for duplicate/subscription-sync
    # matching) — used by "Andere Quelle suchen" to swap in a working
    # alternative without breaking future sync idempotency.
    alt_source_url = Column(Text, nullable=True)
    # 0 = alt_source_url was set blindly (automatic escalation or the old
    # find-alternative), never seen by a human. 1 = a human explicitly picked
    # it via the search-and-pick flow, or confirmed it's actually correct —
    # see api.pick_alternative()/confirm_alternative(). Needed as a separate
    # column rather than just checking alt_source_url IS NOT NULL: without
    # it, a reviewed pick would be indistinguishable from an unreviewed
    # blind guess, so the "please check this" UI hint could never clear.
    alt_source_reviewed = Column(Integer, nullable=False, default=0)
    in_library = Column(Integer, nullable=False, default=0)  # 0/1: parked in the Bibliothek
    library_added_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    channel = relationship("Channel", back_populates="items")
    jobs = relationship("Job", back_populates="item")
    subscription = relationship("Subscription", back_populates="items")


class Job(Base):
    __tablename__ = "job"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(Integer, ForeignKey("item.id"))
    status = Column(String, nullable=False, default="queued")  # queued/running/done/failed
    progress = Column(Integer, default=0)  # 0-100
    error_text = Column(Text)
    attempt_count = Column(Integer, default=0)
    next_attempt_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    item = relationship("Item", back_populates="jobs")


class Subscription(Base):
    __tablename__ = "subscription"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(Integer, ForeignKey("channel.id"), nullable=False)
    source_url = Column(Text, nullable=False)
    type = Column(String, nullable=False)  # podcast/youtube_playlist/youtube_channel/single
    interval_hours = Column(Integer, default=6)
    last_run_at = Column(DateTime)
    last_success_at = Column(DateTime)
    enabled = Column(Integer, default=1)
    title = Column(Text, nullable=True)  # playlist/show title, for block headers in the UI

    channel = relationship("Channel", back_populates="subscriptions")
    items = relationship("Item", back_populates="subscription")


class SubscriptionExclusion(Base):
    """Tombstone for a source_url a user explicitly deleted from an active
    subscription's items. Without this, sync_subscription() has no way to
    tell "never downloaded" apart from "downloaded, then the user deleted
    it" -- the deleted item's row is just gone, so the next periodic sync
    sees that URL as new again and silently re-downloads it. Recorded by
    crud.delete_item(); checked by scheduler.sync_subscription()."""

    __tablename__ = "subscription_exclusion"

    id = Column(Integer, primary_key=True, autoincrement=True)
    subscription_id = Column(Integer, ForeignKey("subscription.id"), nullable=False)
    source_url = Column(Text, nullable=False)
    excluded_at = Column(DateTime, default=datetime.utcnow)


class Settings(Base):
    """Singleton row (id=1) for global, user-editable settings."""

    __tablename__ = "settings"

    id = Column(Integer, primary_key=True)
    max_items_per_list = Column(Integer, nullable=False)
    max_playlist_length = Column(Integer, nullable=False)  # aka retention: episodes kept per channel
    audio_channels = Column(Integer, nullable=False, default=1)  # 1 = mono, 2 = stereo
    language = Column(String, nullable=False, default="de")  # "de" | "en"
    skin = Column(String, nullable=False, default="colors")  # "colors" | "numbers"
