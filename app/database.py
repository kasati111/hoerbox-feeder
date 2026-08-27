"""SQLAlchemy engine and session factory."""
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from . import config

Base = declarative_base()

# check_same_thread=False so the worker/scheduler threads can share the engine.
_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        config.ensure_dirs()
        _engine = create_engine(
            f"sqlite:///{config.DB_PATH}",
            connect_args={"check_same_thread": False},
            future=True,
        )
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), autoflush=False, autocommit=False, future=True
        )
    return _SessionLocal


def init_db() -> None:
    """Create all tables."""
    from . import models  # noqa: F401 (register models)

    Base.metadata.create_all(bind=get_engine())


@contextmanager
def session_scope():
    """Provide a transactional scope around a series of operations."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# FastAPI dependency
def get_db():
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()
