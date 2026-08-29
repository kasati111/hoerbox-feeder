"""Shared pytest fixtures: in-memory SQLite database."""
import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Make the package importable.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import (
    crud,  # noqa: E402
    models,  # noqa: E402,F401
)
from app.database import Base  # noqa: E402


@pytest.fixture()
def db():
    # StaticPool: keeps the one in-memory connection alive and shared across
    # threads. Without it, SQLAlchemy's default pooling for sqlite:///:memory:
    # hands each thread its own separate (and un-seeded) in-memory database --
    # invisible for tests that only touch `db` from the test's own thread, but
    # breaks any test that goes through a TestClient, since FastAPI/Starlette
    # runs sync route handlers in a worker thread.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, future=True)
    session = Session()
    crud.seed_channels(session)
    try:
        yield session
    finally:
        session.close()
