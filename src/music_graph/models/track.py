"""Track and TrackSource models."""

import uuid
from datetime import datetime

from sqlmodel import JSON, Column, Field, Relationship, SQLModel

from music_graph.models.base import ArtistRole, SourcePlatform


class TrackArtist(SQLModel, table=True):
    """Junction table linking tracks to artists with role."""

    __tablename__ = "track_artist"

    track_id: str = Field(foreign_key="track.id", primary_key=True)
    artist_id: str = Field(foreign_key="artist.id", primary_key=True)
    role: ArtistRole = Field(default=ArtistRole.PRIMARY)


class TrackGenre(SQLModel, table=True):
    """Junction table for track-level genre tags (e.g. from Last.fm)."""

    __tablename__ = "track_genre"

    track_id: str = Field(foreign_key="track.id", primary_key=True)
    genre_id: int = Field(foreign_key="genre.id", primary_key=True)
    weight: float = Field(default=1.0)


class Track(SQLModel, table=True):
    """Canonical track entity (platform-agnostic)."""

    __tablename__ = "track"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    canonical_title: str
    canonical_artist_name: str
    duration_ms: int | None = None
    isrc: str | None = Field(default=None, index=True)
    musicbrainz_id: str | None = None

    sources: list["TrackSource"] = Relationship(back_populates="track")


class TrackSource(SQLModel, table=True):
    """Platform-specific track record linked to a canonical Track."""

    __tablename__ = "track_source"

    id: int | None = Field(default=None, primary_key=True)
    track_id: str = Field(foreign_key="track.id", index=True)
    platform: SourcePlatform
    platform_id: str = Field(index=True)
    title: str
    artist_name: str
    raw_json: dict | None = Field(default=None, sa_column=Column(JSON))
    collected_at: datetime = Field(default_factory=datetime.utcnow)

    track: Track = Relationship(back_populates="sources")
