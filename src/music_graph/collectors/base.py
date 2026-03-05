"""Abstract collector interface and platform-agnostic data classes."""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from music_graph.models.base import SourcePlatform


@dataclass
class RawTrack:
    """Platform-agnostic intermediate track representation."""

    platform: SourcePlatform
    platform_id: str
    title: str
    artist_name: str
    artist_ids: list[str] = field(default_factory=list)
    duration_ms: int | None = None
    isrc: str | None = None
    genres: list[str] = field(default_factory=list)
    raw_json: dict | None = None


@dataclass
class RawPlaylist:
    """Platform-agnostic intermediate playlist representation."""

    platform: SourcePlatform
    platform_id: str
    name: str
    owner_name: str | None = None
    track_count: int = 0
    raw_json: dict | None = None


@dataclass
class RawArtist:
    """Platform-agnostic intermediate artist representation."""

    platform: SourcePlatform
    platform_id: str
    name: str
    genres: list[str] = field(default_factory=list)
    raw_json: dict | None = None


@runtime_checkable
class AbstractCollector(Protocol):
    """Protocol for platform-specific collectors."""

    platform: SourcePlatform

    def search_playlists(self, query: str, limit: int = 10) -> list[RawPlaylist]:
        """Search for playlists by keyword."""
        ...

    def get_playlist_tracks(self, playlist_id: str) -> list[RawTrack]:
        """Get all tracks from a playlist."""
        ...

    def get_artist_details(self, artist_id: str) -> RawArtist:
        """Get artist details including genres."""
        ...

    def search_tracks(self, query: str, limit: int = 10) -> list[RawTrack]:
        """Search for tracks by keyword."""
        ...
