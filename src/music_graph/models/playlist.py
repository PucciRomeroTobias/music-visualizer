"""Playlist and PlaylistTrack models."""

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from music_graph.models.base import SourcePlatform


class PlaylistTrack(SQLModel, table=True):
    """Junction table linking playlists to tracks with position."""

    __tablename__ = "playlist_track"

    playlist_id: str = Field(foreign_key="playlist.id", primary_key=True)
    track_id: str = Field(foreign_key="track.id", primary_key=True)
    position: int = Field(default=0)


class Playlist(SQLModel, table=True):
    """Playlist entity."""

    __tablename__ = "playlist"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    platform: SourcePlatform
    platform_id: str = Field(index=True)
    name: str
    owner_name: str | None = None
    track_count: int = Field(default=0)
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    collection_depth: int = Field(default=0)
    tracks_collected: bool = Field(default=False)
    relevance_tier: int | None = Field(default=None, index=True)
    relevance_genre: str | None = Field(default=None)
