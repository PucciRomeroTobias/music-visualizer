"""SQLite database engine and session management."""

from pathlib import Path

from loguru import logger
from sqlmodel import Session, SQLModel, create_engine

from music_graph.config import PROJECT_ROOT, load_settings


def get_db_path() -> Path:
    """Get database path from settings."""
    settings = load_settings()
    relative_path = settings.get("database", {}).get("path", "data/music_graph.db")
    return PROJECT_ROOT / relative_path


def get_engine(db_path: Path | None = None):
    """Create SQLAlchemy engine for SQLite."""
    if db_path is None:
        db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{db_path}"
    logger.debug("Using database at {}", db_path)
    return create_engine(url, echo=False)


def init_db(engine=None) -> None:
    """Create all tables."""
    if engine is None:
        engine = get_engine()
    # Import all models so SQLModel registers them
    import music_graph.models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    logger.info("Database initialized")


def get_session(engine=None) -> Session:
    """Create a new database session."""
    if engine is None:
        engine = get_engine()
    return Session(engine)
