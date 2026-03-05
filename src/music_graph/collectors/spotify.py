"""Spotify data collector using spotipy."""

import os

from loguru import logger
from spotipy import Spotify
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyClientCredentials

from music_graph.collectors.base import RawArtist, RawPlaylist, RawTrack
from music_graph.collectors.rate_limiter import RateLimiter
from music_graph.config import load_settings
from music_graph.models.base import SourcePlatform


class SpotifyCollector:
    """Collects data from Spotify API via spotipy.

    Uses client credentials flow (no user login required).
    """

    platform = SourcePlatform.SPOTIFY

    def __init__(self, rate_limiter: RateLimiter | None = None):
        client_id = os.environ.get("SPOTIFY_CLIENT_ID")
        client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise ValueError(
                "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set in .env"
            )

        auth_manager = SpotifyClientCredentials(
            client_id=client_id,
            client_secret=client_secret,
        )
        self._sp = Spotify(auth_manager=auth_manager)

        if rate_limiter is None:
            settings = load_settings()
            rl_config = settings.get("rate_limits", {}).get("spotify", {})
            rate_limiter = RateLimiter(
                rate=rl_config.get("requests_per_second", 5),
                burst=rl_config.get("burst", 10),
                retry_after_default=rl_config.get("retry_after_default", 5),
            )
        self._limiter = rate_limiter

    def _api_call(self, func, *args, **kwargs):
        """Execute an API call with rate limiting and retry on 429."""
        self._limiter.acquire()
        try:
            return func(*args, **kwargs)
        except SpotifyException as e:
            if e.http_status == 429:
                retry_after = float(e.headers.get("Retry-After", 5))
                self._limiter.handle_retry_after(retry_after)
                return func(*args, **kwargs)
            raise

    def search_playlists(self, query: str, limit: int = 10) -> list[RawPlaylist]:
        """Search for playlists by keyword."""
        logger.info("Searching Spotify playlists for '{}'", query)
        results = self._api_call(
            self._sp.search, q=query, type="playlist", limit=limit
        )
        playlists = []
        for item in results.get("playlists", {}).get("items", []):
            if item is None:
                continue
            playlists.append(
                RawPlaylist(
                    platform=SourcePlatform.SPOTIFY,
                    platform_id=item["id"],
                    name=item["name"],
                    owner_name=item.get("owner", {}).get("display_name"),
                    track_count=item.get("tracks", {}).get("total", 0),
                    raw_json=item,
                )
            )
        logger.info("Found {} playlists for '{}'", len(playlists), query)
        return playlists

    def get_playlist_tracks(self, playlist_id: str) -> list[RawTrack]:
        """Get all tracks from a playlist, handling pagination."""
        logger.info("Fetching tracks for playlist {}", playlist_id)
        tracks = []
        offset = 0
        batch_size = 100

        while True:
            results = self._api_call(
                self._sp.playlist_items,
                playlist_id,
                offset=offset,
                limit=batch_size,
                fields="items(track(id,name,artists,duration_ms,external_ids,album)),next",
            )
            items = results.get("items", [])
            for item in items:
                track_data = item.get("track")
                if track_data is None or track_data.get("id") is None:
                    continue  # Skip local files or unavailable tracks

                artists = track_data.get("artists", [])
                artist_name = artists[0]["name"] if artists else "Unknown"
                artist_ids = [a["id"] for a in artists if a.get("id")]

                isrc = (
                    track_data.get("external_ids", {}).get("isrc")
                    if track_data.get("external_ids")
                    else None
                )

                tracks.append(
                    RawTrack(
                        platform=SourcePlatform.SPOTIFY,
                        platform_id=track_data["id"],
                        title=track_data["name"],
                        artist_name=artist_name,
                        artist_ids=artist_ids,
                        duration_ms=track_data.get("duration_ms"),
                        isrc=isrc,
                        raw_json=track_data,
                    )
                )

            if results.get("next") is None:
                break
            offset += batch_size

        logger.info("Fetched {} tracks from playlist {}", len(tracks), playlist_id)
        return tracks

    def get_artist_details(self, artist_id: str) -> RawArtist:
        """Get artist details including genres."""
        logger.debug("Fetching artist details for {}", artist_id)
        data = self._api_call(self._sp.artist, artist_id)
        return RawArtist(
            platform=SourcePlatform.SPOTIFY,
            platform_id=data["id"],
            name=data["name"],
            genres=data.get("genres", []),
            raw_json=data,
        )

    def search_tracks(self, query: str, limit: int = 10) -> list[RawTrack]:
        """Search for tracks by keyword."""
        logger.info("Searching Spotify tracks for '{}'", query)
        results = self._api_call(
            self._sp.search, q=query, type="track", limit=limit
        )
        tracks = []
        for item in results.get("tracks", {}).get("items", []):
            if item is None:
                continue
            artists = item.get("artists", [])
            artist_name = artists[0]["name"] if artists else "Unknown"
            artist_ids = [a["id"] for a in artists if a.get("id")]
            isrc = item.get("external_ids", {}).get("isrc")

            tracks.append(
                RawTrack(
                    platform=SourcePlatform.SPOTIFY,
                    platform_id=item["id"],
                    title=item["name"],
                    artist_name=artist_name,
                    artist_ids=artist_ids,
                    duration_ms=item.get("duration_ms"),
                    isrc=isrc,
                    raw_json=item,
                )
            )
        logger.info("Found {} tracks for '{}'", len(tracks), query)
        return tracks

    def find_playlists_containing_track(self, track_name: str, artist_name: str, limit: int = 10) -> list[RawPlaylist]:
        """Find playlists containing a specific track by searching."""
        query = f'"{track_name}" {artist_name}'
        return self.search_playlists(query, limit=limit)
