"""
Database session management and connection pooling.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool, QueuePool
from typing import Generator

from story_spec.core.config import DATABASE_URL

# Configure engine based on environment
if DATABASE_URL:
    # For production, use QueuePool with connection pooling
    engine = create_engine(
        DATABASE_URL,
        poolclass=QueuePool,
        pool_size=20,
        max_overflow=40,
        pool_pre_ping=True,  # Verify connections before using
        echo=False,  # Set to True for SQL debugging
    )
else:
    # For testing/dev, use NullPool (no pooling)
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )

# Session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db() -> Generator[Session, None, None]:
    """Dependency to get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Initialize database tables."""
    from story_spec.db.models import Base
    Base.metadata.create_all(bind=engine)


def drop_db() -> None:
    """Drop all database tables (for testing)."""
    from story_spec.db.models import Base
    Base.metadata.drop_all(bind=engine)
