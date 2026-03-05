"""Artist and ArtistSource models."""

import uuid
from datetime import datetime

from sqlmodel import JSON, Column, Field, Relationship, SQLModel

from music_graph.models.base import SourcePlatform


class ArtistGenre(SQLModel, table=True):
    """Junction table linking artists to genres with platform and weight."""

    __tablename__ = "artist_genre"

    artist_id: str = Field(foreign_key="artist.id", primary_key=True)
    genre_id: int = Field(foreign_key="genre.id", primary_key=True)
    platform: SourcePlatform = Field(primary_key=True)
    weight: float = Field(default=1.0)


class Artist(SQLModel, table=True):
    """Canonical artist entity (platform-agnostic)."""

    __tablename__ = "artist"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    canonical_name: str
    musicbrainz_id: str | None = None

    sources: list["ArtistSource"] = Relationship(back_populates="artist")


class ArtistSource(SQLModel, table=True):
    """Platform-specific artist record linked to a canonical Artist."""

    __tablename__ = "artist_source"

    id: int | None = Field(default=None, primary_key=True)
    artist_id: str = Field(foreign_key="artist.id", index=True)
    platform: SourcePlatform
    platform_id: str = Field(index=True)
    name: str
    raw_json: dict | None = Field(default=None, sa_column=Column(JSON))
    collected_at: datetime = Field(default_factory=datetime.utcnow)

    artist: Artist = Relationship(back_populates="sources")
