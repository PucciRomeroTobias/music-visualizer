"""Collection pipeline — BFS orchestrator and ingester."""

from collections import deque
from datetime import datetime

from loguru import logger
from sqlmodel import Session, select

from music_graph.collectors.base import RawArtist, RawPlaylist, RawTrack
from music_graph.collectors.spotify import SpotifyCollector
from music_graph.config import load_seeds, load_settings
from music_graph.models.artist import Artist, ArtistGenre, ArtistSource
from music_graph.models.base import ArtistRole, SourcePlatform
from music_graph.models.genre import Genre
from music_graph.models.playlist import Playlist, PlaylistTrack
from music_graph.models.track import Track, TrackArtist, TrackSource


class Ingester:
    """Ingests raw data into the database, handling deduplication."""

    def __init__(self, session: Session):
        self._session = session
        self._genre_cache: dict[str, Genre] = {}

    def ingest_track(
        self, raw: RawTrack, playlist_id: str | None = None, position: int = 0
    ) -> Track:
        """Ingest a raw track, dedup by (platform, platform_id)."""
        # Check existing source
        existing_source = self._session.exec(
            select(TrackSource).where(
                TrackSource.platform == raw.platform,
                TrackSource.platform_id == raw.platform_id,
            )
        ).first()

        if existing_source:
            track = self._session.get(Track, existing_source.track_id)
        else:
            # Try ISRC match
            track = None
            if raw.isrc:
                track = self._session.exec(
                    select(Track).where(Track.isrc == raw.isrc)
                ).first()

            if track is None:
                track = Track(
                    canonical_title=raw.title,
                    canonical_artist_name=raw.artist_name,
                    duration_ms=raw.duration_ms,
                    isrc=raw.isrc,
                )
                self._session.add(track)
                self._session.flush()

            source = TrackSource(
                track_id=track.id,
                platform=raw.platform,
                platform_id=raw.platform_id,
                title=raw.title,
                artist_name=raw.artist_name,
                raw_json=raw.raw_json,
                collected_at=datetime.utcnow(),
            )
            self._session.add(source)

        # Link to playlist if provided
        if playlist_id and track:
            existing_link = self._session.exec(
                select(PlaylistTrack).where(
                    PlaylistTrack.playlist_id == playlist_id,
                    PlaylistTrack.track_id == track.id,
                )
            ).first()
            if not existing_link:
                self._session.add(
                    PlaylistTrack(
                        playlist_id=playlist_id,
                        track_id=track.id,
                        position=position,
                    )
                )

        return track

    def ingest_artist(self, raw: RawArtist) -> Artist:
        """Ingest a raw artist, dedup by (platform, platform_id)."""
        existing_source = self._session.exec(
            select(ArtistSource).where(
                ArtistSource.platform == raw.platform,
                ArtistSource.platform_id == raw.platform_id,
            )
        ).first()

        if existing_source:
            artist = self._session.get(Artist, existing_source.artist_id)
        else:
            artist = Artist(canonical_name=raw.name)
            self._session.add(artist)
            self._session.flush()

            source = ArtistSource(
                artist_id=artist.id,
                platform=raw.platform,
                platform_id=raw.platform_id,
                name=raw.name,
                raw_json=raw.raw_json,
                collected_at=datetime.utcnow(),
            )
            self._session.add(source)

        # Ingest genres
        for genre_name in raw.genres:
            self._link_artist_genre(artist, genre_name, raw.platform)

        return artist

    def link_track_artist(
        self, track: Track, artist: Artist, role: ArtistRole = ArtistRole.PRIMARY
    ) -> None:
        """Link a track to an artist."""
        existing = self._session.exec(
            select(TrackArtist).where(
                TrackArtist.track_id == track.id,
                TrackArtist.artist_id == artist.id,
            )
        ).first()
        if not existing:
            self._session.add(
                TrackArtist(track_id=track.id, artist_id=artist.id, role=role)
            )

    def ingest_playlist(self, raw: RawPlaylist, depth: int = 0) -> Playlist:
        """Ingest a raw playlist, dedup by (platform, platform_id)."""
        existing = self._session.exec(
            select(Playlist).where(
                Playlist.platform == raw.platform,
                Playlist.platform_id == raw.platform_id,
            )
        ).first()

        if existing:
            return existing

        playlist = Playlist(
            platform=raw.platform,
            platform_id=raw.platform_id,
            name=raw.name,
            owner_name=raw.owner_name,
            track_count=raw.track_count,
            collected_at=datetime.utcnow(),
            collection_depth=depth,
        )
        self._session.add(playlist)
        self._session.flush()
        return playlist

    def _get_or_create_genre(self, name: str, source: SourcePlatform) -> Genre:
        """Get or create a genre by lowercase name."""
        key = name.lower()
        if key in self._genre_cache:
            return self._genre_cache[key]

        genre = self._session.exec(
            select(Genre).where(Genre.name == key)
        ).first()
        if not genre:
            genre = Genre(name=key, source=source)
            self._session.add(genre)
            self._session.flush()

        self._genre_cache[key] = genre
        return genre

    def _link_artist_genre(
        self, artist: Artist, genre_name: str, platform: SourcePlatform
    ) -> None:
        """Link an artist to a genre."""
        genre = self._get_or_create_genre(genre_name, platform)
        existing = self._session.exec(
            select(ArtistGenre).where(
                ArtistGenre.artist_id == artist.id,
                ArtistGenre.genre_id == genre.id,
                ArtistGenre.platform == platform,
            )
        ).first()
        if not existing:
            self._session.add(
                ArtistGenre(
                    artist_id=artist.id,
                    genre_id=genre.id,
                    platform=platform,
                )
            )


class BFSOrchestrator:
    """BFS collection across playlists starting from seed keywords."""

    def __init__(self, session: Session, collector: SpotifyCollector):
        self._session = session
        self._collector = collector
        self._ingester = Ingester(session)
        self._seen_playlists: set[str] = set()
        self._seen_artists: set[str] = set()
        self._settings = load_settings()
        self._seeds = load_seeds()

    def run(self, max_depth: int | None = None) -> None:
        """Run BFS collection from seed keywords."""
        if max_depth is None:
            max_depth = self._settings.get("collection", {}).get("max_depth", 2)

        search_terms = self._seeds.get("keywords", {}).get("search_terms", [])
        genre_scope = set(
            g.lower()
            for g in self._seeds.get("genre_scope", {}).get("include", [])
        )

        # Queue: (playlist_platform_id, depth)
        queue: deque[tuple[str, int]] = deque()

        # Step 1: Search playlists by seed keywords
        for term in search_terms:
            playlists = self._collector.search_playlists(term)
            for raw_pl in playlists:
                if raw_pl.platform_id not in self._seen_playlists:
                    self._seen_playlists.add(raw_pl.platform_id)
                    self._ingester.ingest_playlist(raw_pl, depth=0)
                    queue.append((raw_pl.platform_id, 0))

        self._session.commit()
        logger.info("Seeded {} playlists from search", len(queue))

        # Step 2: BFS
        while queue:
            playlist_pid, depth = queue.popleft()
            if depth > max_depth:
                continue

            logger.info(
                "Processing playlist {} at depth {} ({} remaining)",
                playlist_pid,
                depth,
                len(queue),
            )

            # Fetch tracks
            raw_tracks = self._collector.get_playlist_tracks(playlist_pid)

            # Get the playlist DB record
            playlist = self._session.exec(
                select(Playlist).where(
                    Playlist.platform_id == playlist_pid,
                    Playlist.platform == SourcePlatform.SPOTIFY,
                )
            ).first()
            if not playlist:
                continue

            for i, raw_track in enumerate(raw_tracks):
                track = self._ingester.ingest_track(
                    raw_track, playlist_id=playlist.id, position=i
                )

                # Fetch artist details for new artists
                for artist_pid in raw_track.artist_ids:
                    if artist_pid in self._seen_artists:
                        continue
                    self._seen_artists.add(artist_pid)

                    try:
                        raw_artist = self._collector.get_artist_details(artist_pid)
                        artist = self._ingester.ingest_artist(raw_artist)
                        self._ingester.link_track_artist(track, artist)

                        # Check if artist is in scope for BFS expansion
                        if depth < max_depth and genre_scope:
                            artist_genres = set(
                                g.lower() for g in raw_artist.genres
                            )
                            if artist_genres & genre_scope:
                                # Find more playlists for this artist's tracks
                                more_playlists = (
                                    self._collector.find_playlists_containing_track(
                                        raw_track.title, raw_artist.name, limit=5
                                    )
                                )
                                for rp in more_playlists:
                                    if rp.platform_id not in self._seen_playlists:
                                        self._seen_playlists.add(rp.platform_id)
                                        self._ingester.ingest_playlist(
                                            rp, depth=depth + 1
                                        )
                                        queue.append((rp.platform_id, depth + 1))
                    except Exception:
                        logger.exception(
                            "Failed to fetch artist {}", artist_pid
                        )

            self._session.commit()
            logger.info(
                "Committed playlist {} ({} tracks)", playlist_pid, len(raw_tracks)
            )

        logger.info(
            "BFS complete. Processed {} playlists, {} artists",
            len(self._seen_playlists),
            len(self._seen_artists),
        )
