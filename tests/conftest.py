"""Shared pytest fixtures: in-memory SQLite database."""
import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Make the package importable.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import (
    crud,  # noqa: E402
    models,  # noqa: E402,F401
)
from app.database import Base  # noqa: E402


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, future=True)
    session = Session()
    crud.seed_channels(session)
    try:
        yield session
    finally:
        session.close()
