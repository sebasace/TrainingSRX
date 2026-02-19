"""Database engine and session management."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import DATABASE_URL, ensure_directories
from app.models import Base

# TODO: Switch to PostgreSQL URL + pooled engine settings in production.
ENGINE = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    """Initialize local database and create tables."""
    ensure_directories()
    Base.metadata.create_all(bind=ENGINE)


@contextmanager
def get_session() -> Iterator[Session]:
    """Yield a transactional SQLAlchemy session."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
