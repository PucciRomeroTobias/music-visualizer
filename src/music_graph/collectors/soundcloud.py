"""SoundCloud data collector — unofficial v2 API."""

import os

import requests
from loguru import logger

from music_graph.collectors.base import RawArtist, RawPlaylist, RawTrack
from music_graph.collectors.rate_limiter import RateLimiter
from music_graph.config import load_settings
from music_graph.models.base import SourcePlatform

BASE_URL = "https://api-v2.soundcloud.com"


class SoundCloudCollector:
    """Collects data from SoundCloud's unofficial v2 API.

    Auth via oauth_token (browser cookie) + client_id (page script).
    Rate limit ~2 req/s.
    """

    platform = SourcePlatform.SOUNDCLOUD

    def __init__(self, rate_limiter: RateLimiter | None = None):
        self._session = requests.Session()
        self._oauth_token = os.environ["SOUNDCLOUD_OAUTH_TOKEN"]
        self._client_id = os.environ["SOUNDCLOUD_CLIENT_ID"]
        self._session.headers["Authorization"] = f"OAuth {self._oauth_token}"
        self._session.headers["User-Agent"] = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )

        if rate_limiter is None:
            settings = load_settings()
            rl_config = settings.get("rate_limits", {}).get("soundcloud", {})
            rate_limiter = RateLimiter(
                rate=rl_config.get("requests_per_second", 2),
                burst=rl_config.get("burst", 5),
                retry_after_default=rl_config.get("retry_after_default", 5),
            )
        self._limiter = rate_limiter

    def _get(self, endpoint: str, params: dict | None = None) -> dict:
        """Make a rate-limited GET request to SoundCloud API."""
        self._limiter.acquire()
        url = f"{BASE_URL}/{endpoint}"
        if params is None:
            params = {}
        params.setdefault("client_id", self._client_id)

        resp = self._session.get(url, params=params, timeout=(10, 30))

        if resp.status_code == 429:
            self._limiter.handle_retry_after()
            resp = self._session.get(url, params=params, timeout=(10, 30))

        if resp.status_code == 404:
            logger.warning("SoundCloud resource not found: {}", endpoint)
            return {}

        resp.raise_for_status()
        return resp.json()

    def get_user_playlists(self, user_id: str) -> list[RawPlaylist]:
        """Get all playlists for a user (including private if authed)."""
        logger.info("Fetching playlists for SoundCloud user {}", user_id)
        playlists: list[RawPlaylist] = []
        params: dict = {"limit": 50}
        endpoint = f"users/{user_id}/playlists"

        while True:
            data = self._get(endpoint, params=params)
            collection = data.get("collection", [])
            if not collection:
                break

            for item in collection:
                playlists.append(
                    RawPlaylist(
                        platform=SourcePlatform.SOUNDCLOUD,
                        platform_id=str(item["id"]),
                        name=item.get("title", ""),
                        owner_name=item.get("user", {}).get("username"),
                        track_count=item.get("track_count", 0),
                        raw_json=item,
                    )
                )

            next_href = data.get("next_href")
            if not next_href:
                break
            # next_href is absolute; extract relative part
            endpoint = next_href.replace(BASE_URL + "/", "")
            params = {}  # params encoded in next_href

        logger.info("Found {} playlists for user {}", len(playlists), user_id)
        return playlists

    def get_playlist_tracks(self, playlist_id: str) -> list[RawTrack]:
        """Get all tracks from a playlist, batch-fetching incomplete ones."""
        logger.info("Fetching tracks for SoundCloud playlist {}", playlist_id)
        data = self._get(f"playlists/{playlist_id}")
        if not data:
            return []

        tracks_data = data.get("tracks", [])

        # SoundCloud only populates first ~5 tracks fully; rest are ID-only
        complete = []
        incomplete_ids = []
        for t in tracks_data:
            if t.get("title"):
                complete.append(t)
            elif t.get("id"):
                incomplete_ids.append(str(t["id"]))

        # Batch-fetch incomplete tracks (max 50 per request)
        for i in range(0, len(incomplete_ids), 50):
            batch = incomplete_ids[i : i + 50]
            ids_str = ",".join(batch)
            batch_data = self._get("tracks", params={"ids": ids_str})
            if isinstance(batch_data, list):
                complete.extend(batch_data)
            elif isinstance(batch_data, dict) and "collection" in batch_data:
                complete.extend(batch_data["collection"])

        tracks = []
        for item in complete:
            uploader = item.get("user", {}).get("username", "Unknown")
            tracks.append(
                RawTrack(
                    platform=SourcePlatform.SOUNDCLOUD,
                    platform_id=str(item["id"]),
                    title=item.get("title", ""),
                    artist_name=uploader,
                    artist_ids=[],
                    duration_ms=item.get("duration"),
                    isrc=None,
                    raw_json=item,
                )
            )

        logger.info(
            "Fetched {} tracks from SoundCloud playlist {}",
            len(tracks),
            playlist_id,
        )
        return tracks

    def search_playlists(self, query: str, limit: int = 25) -> list[RawPlaylist]:
        """Search for playlists by keyword."""
        logger.info("Searching SoundCloud playlists for '{}'", query)
        data = self._get("search/playlists", params={"q": query, "limit": limit})
        playlists = []
        for item in data.get("collection", []):
            playlists.append(
                RawPlaylist(
                    platform=SourcePlatform.SOUNDCLOUD,
                    platform_id=str(item["id"]),
                    name=item.get("title", ""),
                    owner_name=item.get("user", {}).get("username"),
                    track_count=item.get("track_count", 0),
                    raw_json=item,
                )
            )
        logger.info("Found {} playlists for '{}'", len(playlists), query)
        return playlists

    def get_artist_details(self, artist_id: str) -> RawArtist:
        """Get user/artist details."""
        logger.debug("Fetching SoundCloud user details for {}", artist_id)
        data = self._get(f"users/{artist_id}")
        return RawArtist(
            platform=SourcePlatform.SOUNDCLOUD,
            platform_id=str(data.get("id", artist_id)),
            name=data.get("username", "Unknown"),
            raw_json=data,
        )

    def search_tracks(self, query: str, limit: int = 25) -> list[RawTrack]:
        """Search for tracks by keyword."""
        logger.info("Searching SoundCloud tracks for '{}'", query)
        data = self._get("search/tracks", params={"q": query, "limit": limit})
        tracks = []
        for item in data.get("collection", []):
            uploader = item.get("user", {}).get("username", "Unknown")
            tracks.append(
                RawTrack(
                    platform=SourcePlatform.SOUNDCLOUD,
                    platform_id=str(item["id"]),
                    title=item.get("title", ""),
                    artist_name=uploader,
                    artist_ids=[],
                    duration_ms=item.get("duration"),
                    isrc=None,
                    raw_json=item,
                )
            )
        logger.info("Found {} tracks for '{}'", len(tracks), query)
        return tracks
