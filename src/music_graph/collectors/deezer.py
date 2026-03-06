"""Deezer data collector — no authentication required."""

import requests
from loguru import logger

from music_graph.collectors.base import RawArtist, RawPlaylist, RawTrack
from music_graph.collectors.rate_limiter import RateLimiter
from music_graph.config import load_settings
from music_graph.models.base import SourcePlatform

BASE_URL = "https://api.deezer.com"


class DeezerCollector:
    """Collects data from Deezer's public API.

    No authentication required. Rate limit ~50 req/5s.
    """

    platform = SourcePlatform.DEEZER

    def __init__(self, rate_limiter: RateLimiter | None = None):
        self._session = requests.Session()
        if rate_limiter is None:
            settings = load_settings()
            rl_config = settings.get("rate_limits", {}).get("deezer", {})
            rate_limiter = RateLimiter(
                rate=rl_config.get("requests_per_second", 8),
                burst=rl_config.get("burst", 15),
                retry_after_default=rl_config.get("retry_after_default", 5),
            )
        self._limiter = rate_limiter

    def _get(self, endpoint: str, params: dict | None = None) -> dict:
        """Make a rate-limited GET request to Deezer API."""
        self._limiter.acquire()
        url = f"{BASE_URL}/{endpoint}"
        resp = self._session.get(url, params=params, timeout=(10, 30))
        data = resp.json()
        if "error" in data:
            error = data["error"]
            if error.get("code") == 4:
                # Rate limited
                self._limiter.handle_retry_after()
                resp = self._session.get(url, params=params, timeout=(10, 30))
                data = resp.json()
            elif error.get("code") == 800:
                logger.warning("Deezer resource not found: {}", endpoint)
                return {}
            else:
                logger.error("Deezer API error: {}", error)
        return data

    def search_playlists(self, query: str, limit: int = 25) -> list[RawPlaylist]:
        """Search for playlists by keyword."""
        logger.info("Searching Deezer playlists for '{}'", query)
        data = self._get("search/playlist", params={"q": query, "limit": limit})
        playlists = []
        for item in data.get("data", []):
            playlists.append(
                RawPlaylist(
                    platform=SourcePlatform.DEEZER,
                    platform_id=str(item["id"]),
                    name=item["title"],
                    owner_name=item.get("user", {}).get("name"),
                    track_count=item.get("nb_tracks", 0),
                    raw_json=item,
                )
            )
        logger.info("Found {} playlists for '{}'", len(playlists), query)
        return playlists

    def get_playlist_tracks(self, playlist_id: str) -> list[RawTrack]:
        """Get all tracks from a playlist, handling pagination."""
        logger.info("Fetching tracks for Deezer playlist {}", playlist_id)
        tracks = []
        url = f"playlist/{playlist_id}/tracks"
        params = {"limit": 100}

        while url:
            data = self._get(url, params=params)
            for item in data.get("data", []):
                artist = item.get("artist", {})
                tracks.append(
                    RawTrack(
                        platform=SourcePlatform.DEEZER,
                        platform_id=str(item["id"]),
                        title=item["title"],
                        artist_name=artist.get("name", "Unknown"),
                        artist_ids=[str(artist["id"])] if artist.get("id") else [],
                        duration_ms=item.get("duration", 0) * 1000,
                        raw_json=item,
                    )
                )
            # Pagination
            next_url = data.get("next")
            if next_url:
                # next_url is absolute, extract relative part
                url = next_url.replace(BASE_URL + "/", "")
                params = None  # params are in the URL already
            else:
                break

        logger.info(
            "Fetched {} tracks from Deezer playlist {}", len(tracks), playlist_id
        )
        return tracks

    def get_track_details(self, track_id: str) -> RawTrack | None:
        """Get full track details including ISRC."""
        data = self._get(f"track/{track_id}")
        if not data or not data.get("id"):
            return None
        artist = data.get("artist", {})
        contributors = data.get("contributors", [])
        artist_ids = [str(c["id"]) for c in contributors if c.get("id")]
        if not artist_ids and artist.get("id"):
            artist_ids = [str(artist["id"])]

        return RawTrack(
            platform=SourcePlatform.DEEZER,
            platform_id=str(data["id"]),
            title=data["title"],
            artist_name=artist.get("name", "Unknown"),
            artist_ids=artist_ids,
            duration_ms=data.get("duration", 0) * 1000,
            isrc=data.get("isrc"),
            raw_json=data,
        )

    def get_artist_details(self, artist_id: str) -> RawArtist:
        """Get artist details."""
        logger.debug("Fetching Deezer artist details for {}", artist_id)
        data = self._get(f"artist/{artist_id}")
        return RawArtist(
            platform=SourcePlatform.DEEZER,
            platform_id=str(data.get("id", artist_id)),
            name=data.get("name", "Unknown"),
            raw_json=data,
        )

    def get_related_artists(self, artist_id: str, limit: int = 20) -> list[RawArtist]:
        """Get related artists from Deezer."""
        logger.debug("Fetching related artists for {}", artist_id)
        data = self._get(f"artist/{artist_id}/related", params={"limit": limit})
        artists = []
        for item in data.get("data", []):
            artists.append(
                RawArtist(
                    platform=SourcePlatform.DEEZER,
                    platform_id=str(item["id"]),
                    name=item.get("name", "Unknown"),
                    raw_json=item,
                )
            )
        return artists

    def get_album_genres(self, album_id: str) -> list[str]:
        """Get genre names from an album."""
        data = self._get(f"album/{album_id}")
        genres_data = data.get("genres", {}).get("data", [])
        return [g["name"] for g in genres_data if g.get("name")]

    def get_track_genres(self, track_id: str) -> list[str]:
        """Get genres for a track via its album."""
        data = self._get(f"track/{track_id}")
        album = data.get("album", {})
        if album.get("id"):
            return self.get_album_genres(str(album["id"]))
        return []

    def search_tracks(self, query: str, limit: int = 25) -> list[RawTrack]:
        """Search for tracks by keyword."""
        logger.info("Searching Deezer tracks for '{}'", query)
        data = self._get("search/track", params={"q": query, "limit": limit})
        tracks = []
        for item in data.get("data", []):
            artist = item.get("artist", {})
            tracks.append(
                RawTrack(
                    platform=SourcePlatform.DEEZER,
                    platform_id=str(item["id"]),
                    title=item["title"],
                    artist_name=artist.get("name", "Unknown"),
                    artist_ids=[str(artist["id"])] if artist.get("id") else [],
                    duration_ms=item.get("duration", 0) * 1000,
                    raw_json=item,
                )
            )
        logger.info("Found {} tracks for '{}'", len(tracks), query)
        return tracks

    def find_playlists_containing_track(
        self, track_name: str, artist_name: str, limit: int = 10
    ) -> list[RawPlaylist]:
        """Find playlists by searching for track name + artist."""
        query = f"{track_name} {artist_name}"
        return self.search_playlists(query, limit=limit)
