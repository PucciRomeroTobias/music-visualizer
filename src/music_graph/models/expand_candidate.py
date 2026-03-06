"""Staging table for the expand pipeline — persists intermediate progress."""

import enum
from datetime import datetime, timezone

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class CandidateStatus(str, enum.Enum):
    """Status of an expand candidate playlist."""

    PENDING = "pending"        # Found by search, not yet probed
    QUALIFIED = "qualified"    # Probed, meets overlap threshold
    REJECTED = "rejected"      # Probed, below overlap threshold
    INGESTED = "ingested"      # Qualified and fully ingested


class ExpandCandidate(SQLModel, table=True):
    """Candidate playlist discovered during the expand pipeline.

    Persists Phase 2 (search) and Phase 3 (probe) results so the pipeline
    can resume across batches without repeating API calls.
    """

    __tablename__ = "expand_candidate"

    id: int | None = Field(default=None, primary_key=True)
    playlist_platform_id: str = Field(index=True, unique=True)
    playlist_name: str
    platform: str = "DEEZER"
    status: CandidateStatus = Field(default=CandidateStatus.PENDING)
    overlap_score: int | None = None
    source_artist_pid: str | None = None  # Which discovered artist led to this
    raw_playlist_json: dict | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
